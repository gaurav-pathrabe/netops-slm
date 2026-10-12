"""
train_mole.py - NetOps-SLM Mixture of LoRA Experts (MoLE) Multi-Adapter Training Pipeline

Trains specialized 4-bit QLoRA adapters for the 3 MoLE experts:
1. `expert_bgp_protocol`: Trained on `dataset/mole_expert_bgp.jsonl`
2. `expert_clos_fabric`: Trained on `dataset/mole_expert_clos.jsonl`
3. `expert_template_gate`: Trained on `dataset/mole_expert_template.jsonl`

Supports local RTX 2050 (4GB VRAM) training via 4-bit NF4 quantization,
Paged AdamW 8-bit optimizer, and dry-run architectural validation.
"""

import os
os.environ["TORCH_COMPILE_DISABLE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys
import json
import time
import logging
import argparse
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.models.mole_architecture import EXPERT_CONFIGS, MoLEEngine
from src.models.mole_router import MoLERouter

DATASET_DIR = os.path.join(PROJECT_ROOT, "dataset")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")


def check_compute_environment() -> Dict[str, Any]:
    """Audits PyTorch, CUDA, and GPU hardware availability."""
    try:
        import torch
        cuda_avail = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if cuda_avail else "None"
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3) if cuda_avail else 0.0
        return {
            "torch_installed": True,
            "cuda_available": cuda_avail,
            "gpu_name": gpu_name,
            "vram_gb": round(vram_gb, 2)
        }
    except ImportError:
        return {
            "torch_installed": False,
            "cuda_available": False,
            "gpu_name": "None",
            "vram_gb": 0.0
        }


def load_expert_dataset(expert_name: str) -> List[Dict[str, Any]]:
    """Loads dataset corresponding to a specific expert."""
    filename_map = {
        MoLERouter.EXPERT_BGP: "mole_expert_bgp.jsonl",
        MoLERouter.EXPERT_CLOS: "mole_expert_clos.jsonl",
        MoLERouter.EXPERT_TEMPLATE: "mole_expert_template.jsonl"
    }
    path = os.path.join(DATASET_DIR, filename_map[expert_name])
    if not os.path.exists(path):
        raise FileNotFoundError(f"Expert dataset not found: {path}. Run curate_mole_datasets.py first.")

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def train_expert(
    expert_name: str,
    base_model_name: str = "Qwen/Qwen2.5-Coder-1.5B-Instruct",
    max_steps: int = 25,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Trains or validates QLoRA adapter for designated MoLE expert."""
    env = check_compute_environment()
    cfg = EXPERT_CONFIGS[expert_name]
    records = load_expert_dataset(expert_name)
    output_dir = os.path.join(MODELS_DIR, f"mole-{expert_name}")
    os.makedirs(output_dir, exist_ok=True)

    logging.info(f"=== Starting Training for MoLE Expert: {expert_name} ===")
    logging.info(f"Loaded {len(records)} training examples.")
    logging.info(f"Host Compute Environment: {env}")

    if dry_run or not env["cuda_available"]:
        logging.info("Dry-run mode or CUDA unavailable. Validating training specification:")
        summary = {
            "expert_name": expert_name,
            "base_model": base_model_name,
            "lora_rank": cfg["r"],
            "lora_alpha": cfg["lora_alpha"],
            "target_modules": cfg["target_modules"],
            "dataset_examples": len(records),
            "output_dir": output_dir,
            "status": "VALIDATED_READY_FOR_GPU",
            "timestamp": time.time()
        }
        with open(os.path.join(output_dir, "expert_training_metadata.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print("----------------------------------------------------------------")
        print(f"Expert Adapter:      {expert_name}")
        print(f"Rank / Alpha:        r={cfg['r']}, alpha={cfg['lora_alpha']}")
        print(f"Target Modules:      {cfg['target_modules']}")
        print(f"Dataset Size:        {len(records)} examples")
        print(f"Output Directory:    {output_dir}")
        print(f"Validation Result:   PASSED [OK]")
        print("----------------------------------------------------------------")
        return summary

    # Real GPU Training Execution
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import Dataset

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16
    )

    tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True
    )
    model = prepare_model_for_kbit_training(model)

    peft_config = LoraConfig(
        r=cfg["r"],
        lora_alpha=cfg["lora_alpha"],
        target_modules=cfg["target_modules"],
        lora_dropout=cfg["lora_dropout"],
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, peft_config)

    # Format texts
    formatted_texts = []
    for r in records:
        convs = r.get("conversations", [])
        if len(convs) >= 3:
            sys_m = convs[0]["value"]
            usr_m = convs[1]["value"]
            ast_m = convs[2]["value"]
            text = f"<|im_start|>system\n{sys_m}<|im_end|>\n<|im_start|>user\n{usr_m}<|im_end|>\n<|im_start|>assistant\n{ast_m}<|im_end|>"
            formatted_texts.append({"text": text})

    dataset = Dataset.from_list(formatted_texts)
    def tokenize(sample):
        return tokenizer(sample["text"], truncation=True, max_length=512, padding="max_length")

    tokenized_ds = dataset.map(tokenize, batched=True)

    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        max_steps=max_steps,
        learning_rate=2e-4,
        optim="paged_adamw_8bit",
        logging_steps=5,
        save_strategy="no",
        fp16=True
    )

    from transformers import Trainer, DataCollatorForLanguageModeling
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    )

    trainer.train()
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    logging.info(f"[+] Saved fine-tuned adapter for {expert_name} to {output_dir}")

    return {"expert_name": expert_name, "status": "TRAINED", "output_dir": output_dir}


def train_all_mole_experts(dry_run: bool = False):
    """Executes training / validation across all 3 MoLE experts."""
    results = {}
    for exp_name in [MoLERouter.EXPERT_BGP, MoLERouter.EXPERT_CLOS, MoLERouter.EXPERT_TEMPLATE]:
        res = train_expert(exp_name, dry_run=dry_run)
        results[exp_name] = res
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MoLE Multi-Expert Training Pipeline")
    parser.add_argument("--dry_run", action="store_true", default=False, help="Validate config without full GPU compute")
    args = parser.parse_args()

    train_all_mole_experts(dry_run=args.dry_run)
