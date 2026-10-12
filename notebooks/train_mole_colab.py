"""
train_mole_colab.py - Self-Contained Google Colab MoLE Multi-Expert Training Script

Designed for free Google Colab (Tesla T4 GPU, 15GB VRAM).
Trains the 3 MoLE LoRA adapters in sequence:
1. `expert_bgp_protocol` (73 episodes)
2. `expert_clos_fabric` (5 episodes)
3. `expert_template_gate` (4 fixtures)

Saves all trained adapters and bundles them into `mole_trained_adapters.zip`.
"""

import os
os.environ["TORCH_COMPILE_DISABLE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys
import json
import time
import shutil
import zipfile
import logging
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"

EXPERT_CONFIGS = {
    "expert_bgp_protocol": {
        "dataset_file": "mole_expert_bgp.jsonl",
        "r": 16,
        "lora_alpha": 32,
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        "lora_dropout": 0.05,
        "num_epochs": 3,
        "lr": 2e-4
    },
    "expert_clos_fabric": {
        "dataset_file": "mole_expert_clos.jsonl",
        "r": 16,
        "lora_alpha": 32,
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        "lora_dropout": 0.05,
        "num_epochs": 5,
        "lr": 2e-4
    },
    "expert_template_gate": {
        "dataset_file": "mole_expert_template.jsonl",
        "r": 8,
        "lora_alpha": 16,
        "target_modules": ["q_proj", "v_proj"],
        "lora_dropout": 0.05,
        "num_epochs": 5,
        "lr": 2e-4
    }
}


def load_dataset_records(dataset_path: str) -> List[Dict[str, Any]]:
    records = []
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Dataset not found at {dataset_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def format_records_for_training(records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    formatted = []
    for r in records:
        convs = r.get("conversations", [])
        if len(convs) >= 3:
            sys_m = convs[0]["value"]
            usr_m = convs[1]["value"]
            ast_m = convs[2]["value"]
            text = (
                f"<|im_start|>system\n{sys_m}<|im_end|>\n"
                f"<|im_start|>user\n{usr_m}<|im_end|>\n"
                f"<|im_start|>assistant\n{ast_m}<|im_end|>"
            )
            formatted.append({"text": text})
    return formatted


def train_single_expert(
    expert_name: str,
    cfg: Dict[str, Any],
    dataset_dir: str,
    output_base_dir: str
):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import Dataset

    out_dir = os.path.join(output_base_dir, f"mole-{expert_name}")
    os.makedirs(out_dir, exist_ok=True)
    dataset_path = os.path.join(dataset_dir, cfg["dataset_file"])

    logging.info(f"\n=======================================================")
    logging.info(f"   TRAINING MoLE EXPERT: {expert_name}")
    logging.info(f"=======================================================")
    raw_records = load_dataset_records(dataset_path)
    formatted = format_records_for_training(raw_records)
    logging.info(f"Loaded and formatted {len(formatted)} examples from {cfg['dataset_file']}.")

    # 4-bit NF4 Quantization configuration
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16
    )

    logging.info(f"Loading base model {BASE_MODEL} in 4-bit NF4...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True
    )
    model = prepare_model_for_kbit_training(model)

    # LoRA Adapter Configuration
    peft_config = LoraConfig(
        r=cfg["r"],
        lora_alpha=cfg["lora_alpha"],
        target_modules=cfg["target_modules"],
        lora_dropout=cfg["lora_dropout"],
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # Tokenize
    ds = Dataset.from_list(formatted)
    def tokenize_fn(sample):
        return tokenizer(sample["text"], truncation=True, max_length=512, padding="max_length")

    tokenized_ds = ds.map(tokenize_fn, batched=True)

    training_args = TrainingArguments(
        output_dir=out_dir,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        num_train_epochs=cfg["num_epochs"],
        learning_rate=cfg["lr"],
        optim="paged_adamw_8bit",
        logging_steps=5,
        save_strategy="no",
        fp16=True,
        report_to="none"
    )

    from transformers import Trainer, DataCollatorForLanguageModeling
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    )

    t0 = time.time()
    trainer.train()
    elapsed = time.time() - t0
    logging.info(f"[+] Completed training for {expert_name} in {elapsed:.2f}s.")

    # Save fine-tuned adapter weights
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)

    # Write training metadata
    meta = {
        "expert_name": expert_name,
        "base_model": BASE_MODEL,
        "lora_rank": cfg["r"],
        "lora_alpha": cfg["lora_alpha"],
        "target_modules": cfg["target_modules"],
        "training_time_sec": round(elapsed, 2),
        "examples_trained": len(formatted),
        "epochs": cfg["num_epochs"],
        "status": "TRAINED_SUCCESS"
    }
    with open(os.path.join(out_dir, "training_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # Cleanup GPU memory for next adapter
    del model
    del trainer
    torch.cuda.empty_cache()


def package_adapters_zip(models_dir: str, output_zip: str):
    logging.info(f"Packaging all trained adapters into {output_zip}...")
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(models_dir):
            for file in files:
                if "mole-" in root:
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, models_dir)
                    zf.write(full_p, rel_p)
    logging.info(f"[+] Successfully generated {output_zip} ({os.path.getsize(output_zip) / (1024**2):.2f} MB).")


def run_full_mole_pipeline(dataset_dir: str = "dataset", models_dir: str = "models"):
    os.makedirs(models_dir, exist_ok=True)
    for exp_name, cfg in EXPERT_CONFIGS.items():
        train_single_expert(exp_name, cfg, dataset_dir, models_dir)
    package_adapters_zip(models_dir, "mole_trained_adapters.zip")
    logging.info("\n[★] ALL 3 MoLE EXPERTS TRAINED AND PACKAGED SUCCESSFULLY!")


if __name__ == "__main__":
    run_full_mole_pipeline()
