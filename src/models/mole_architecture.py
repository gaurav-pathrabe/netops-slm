"""
mole_architecture.py - Mixture of LoRA Experts (MoLE) Specification & Multi-Adapter Engine

Defines the multi-expert PEFT LoRA architecture for NetOps-SLM:
- Base Model: Qwen2.5-Coder-1.5B-Instruct (4-bit NF4 for edge; 7B on cloud)
- Expert 1: `expert_bgp_protocol` (r=16, alpha=32) -> BGP FSM & Peering
- Expert 2: `expert_clos_fabric` (r=16, alpha=32) -> CLOS Multi-path & ECMP
- Expert 3: `expert_template_gate` (r=8, alpha=16) -> Schema & CLI Templates

Provides multi-adapter loading, switching, and routing integration.
"""

import os
import sys
import json
import logging
from typing import Dict, Any, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.models.mole_router import MoLERouter


EXPERT_CONFIGS = {
    MoLERouter.EXPERT_BGP: {
        "r": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.05,
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        "description": "BGP finite state machine and peering specialist"
    },
    MoLERouter.EXPERT_CLOS: {
        "r": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.05,
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        "description": "4-Node Spine-Leaf CLOS Fabric, ECMP multi-path, and MTU specialist"
    },
    MoLERouter.EXPERT_TEMPLATE: {
        "r": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.05,
        "target_modules": ["q_proj", "v_proj"],
        "description": "Deterministic TypedActionGate schema and Jinja2 CLI template specialist"
    }
}


class MoLEEngine:
    """
    Manages multi-adapter LoRA routing and execution over a single shared quantized base model.
    """

    def __init__(
        self,
        base_model_name: str = "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        models_dir: Optional[str] = None
    ):
        self.base_model_name = base_model_name
        self.models_dir = models_dir or os.path.join(PROJECT_ROOT, "models")
        self.router = MoLERouter()
        self.model = None
        self.tokenizer = None
        self.active_expert = None

    def get_adapter_path(self, expert_name: str) -> str:
        return os.path.join(self.models_dir, f"mole-{expert_name}")

    def load_model(self, device_map: str = "auto", load_in_4bit: bool = True):
        """Loads base model with PEFT multi-adapter capability if PyTorch is available."""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            from peft import PeftModel, LoraConfig, get_peft_model
        except ImportError:
            logging.warning("PyTorch/PEFT not installed in current environment. Operating in architectural simulation mode.")
            return False

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=load_in_4bit,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16
        ) if load_in_4bit else None

        logging.info(f"Loading tokenizer: {self.base_model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(self.base_model_name, trust_remote_code=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        logging.info(f"Loading base model: {self.base_model_name}")
        self.model = AutoModelForCausalLM.from_pretrained(
            self.base_model_name,
            quantization_config=bnb_config,
            device_map=device_map,
            trust_remote_code=True
        )

        # Register expert adapters
        for exp_name, cfg in EXPERT_CONFIGS.items():
            adapter_path = self.get_adapter_path(exp_name)
            if os.path.exists(os.path.join(adapter_path, "adapter_model.safetensors")):
                logging.info(f"Loading existing adapter for {exp_name} from {adapter_path}")
                self.model.load_adapter(adapter_path, adapter_name=exp_name)
            else:
                logging.info(f"Initializing adapter configuration for {exp_name}")
                lora_cfg = LoraConfig(
                    r=cfg["r"],
                    lora_alpha=cfg["lora_alpha"],
                    target_modules=cfg["target_modules"],
                    lora_dropout=cfg["lora_dropout"],
                    bias="none",
                    task_type="CAUSAL_LM"
                )
                self.model.add_adapter(lora_cfg, adapter_name=exp_name)

        return True

    def set_active_expert(self, expert_name: str):
        """Switches active PEFT LoRA adapter in < 0.1 ms."""
        if expert_name not in EXPERT_CONFIGS:
            raise ValueError(f"Unknown expert '{expert_name}'. Available: {list(EXPERT_CONFIGS.keys())}")
        self.active_expert = expert_name
        if self.model is not None and hasattr(self.model, "set_adapter"):
            self.model.set_adapter(expert_name)
        logging.info(f"[MoLE] Switched active adapter to -> {expert_name}")

    def route_and_dispatch(self, snapshot: Dict[str, Any]) -> Tuple[str, Dict[str, float]]:
        """Determines optimal expert for telemetry snapshot and activates adapter."""
        best_expert, weights = self.router.route(snapshot)
        self.set_active_expert(best_expert)
        return best_expert, weights


if __name__ == "__main__":
    engine = MoLEEngine()
    print("=================================================================")
    print("           NetOps-SLM MoLE Architecture Specification             ")
    print("=================================================================")
    print(f"Base Model:       {engine.base_model_name}")
    print(f"Quantization:     4-bit NF4 (Double Quantization)")
    print(f"Experts Defined:  {len(EXPERT_CONFIGS)}")
    for name, cfg in EXPERT_CONFIGS.items():
        print(f"\n  [Expert] {name}")
        print(f"    Description:    {cfg['description']}")
        print(f"    Rank (r):       {cfg['r']}, Alpha: {cfg['lora_alpha']}")
        print(f"    Target Modules: {cfg['target_modules']}")
    print("=================================================================")
