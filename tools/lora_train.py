"""Train a LoRA adapter for the small NPC model on tools/lora_data.py output, for gate G1. Needs a GPU and
`pip install torch transformers peft trl datasets` (tested: trl 0.19.1, peft 0.15.2, an NVIDIA A10).

    python tools/lora_train.py --data train.jsonl --base Qwen/Qwen3-1.7B --out adapter/

The prompt is rendered with the model's chat template and thinking turned off, as vLLM does when a node sets
"chat_template_kwargs": {"enable_thinking": false}; the loss is on the reply only. Serve the result with
`vllm serve Qwen/Qwen3-1.7B --enable-lora --lora-modules npc-g1=adapter/` and point a node's upstream_model at npc-g1."""
import argparse
import json

from datasets import Dataset
from peft import LoraConfig
from transformers import AutoTokenizer
from trl import SFTConfig, SFTTrainer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--rank", type=int, default=16)
    a = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(a.base)
    rows = [json.loads(x) for x in open(a.data, encoding="utf-8") if x.strip()]
    data = Dataset.from_list([{"prompt": tok.apply_chat_template(r["prompt"], tokenize=False, add_generation_prompt=True, enable_thinking=False),
                               "completion": r["completion"] + tok.eos_token} for r in rows])  # eos is <|im_end|>: the reply ends there
    cfg = SFTConfig(output_dir=a.out, num_train_epochs=a.epochs, per_device_train_batch_size=8, gradient_accumulation_steps=2,
                    model_init_kwargs={"torch_dtype": "bfloat16"}, learning_rate=2e-4, lr_scheduler_type="cosine",
                    warmup_ratio=0.05, logging_steps=10, save_strategy="no", bf16=True, completion_only_loss=True, report_to=[], seed=7)
    lora = LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    t = SFTTrainer(model=a.base, args=cfg, train_dataset=data, processing_class=tok, peft_config=lora)
    t.train()
    t.save_model(a.out)
    print(f"adapter saved to {a.out} from {len(rows)} examples")


if __name__ == "__main__":
    main()
