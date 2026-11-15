"""
EVREN AI (evren.ssyz.org.tr) H200 GPU Kümesi veya CUDA GPU üzerinde
açık ağırlıklı büyük dil modellerini (Qwen / Llama / DeepSeek vb.)
LoRA / QLoRA yöntemiyle kendi JSONL veri setinle eğitme betiği.
"""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="EVREN LoRA / QLoRA SFT Eğitim Betiği")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-14B-Instruct", help="Temel açık ağırlıklı model ID veya yerel yol")
    parser.add_argument("--dataset", default="dataset_train.jsonl", help="Eğitim JSONL dosyası")
    parser.add_argument("--eval-dataset", default="dataset_eval.jsonl", help="Doğrulama JSONL dosyası (isteğe bağlı)")
    parser.add_argument("--output-dir", default="./outputs/evren-custom-lora", help="Eğitim çıktı klasörü")
    parser.add_argument("--epochs", type=int, default=3, help="Epoch sayısı")
    parser.add_argument("--batch-size", type=int, default=2, help="Cihaz başına batch size")
    parser.add_argument("--grad-accum", type=int, default=8, help="Gradient accumulation adımı")
    parser.add_argument("--lr", type=float, default=2e-4, help="Öğrenme oranı")
    parser.add_argument("--lora-r", type=int, default=32, help="LoRA rank değeri")
    parser.add_argument("--max-seq-len", type=int, default=4096, help="Maksimum bağlam uzunluğu")
    parser.add_argument("--qlora", action="store_true", help="4-bit QLoRA kullan (VRAM tasarrufu)")
    parser.add_argument("--merge", action="store_true", help="Eğitim sonrası LoRA ağırlıklarını temel modelle birleştir")
    args = parser.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Eğitim veri seti bulunamadı: {dataset_path}")

    data_files = {"train": str(dataset_path)}
    eval_path = Path(args.eval_dataset)
    has_eval = eval_path.exists() and eval_path.stat().st_size > 0
    if has_eval:
        data_files["validation"] = str(eval_path)

    ds = load_dataset("json", data_files=data_files)
    if len(ds["train"]) == 0:
        raise ValueError("Eğitim veri seti boş. Önce en az birkaç sohbet örneği oluşturun.")

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant_config = None
    if args.qlora:
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=quant_config,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_r * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    sft_config = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        bf16=True,
        logging_steps=5,
        save_strategy="epoch",
        eval_strategy="epoch" if has_eval else "no",
        max_length=args.max_seq_len,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=ds["train"],
        eval_dataset=ds["validation"] if has_eval else None,
        peft_config=lora_config,
        args=sft_config,
    )

    trainer.train()
    adapter_dir = Path(args.output_dir) / "lora_adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"LoRA adaptörü kaydedildi: {adapter_dir}")

    if args.merge and not args.qlora:
        merged_dir = Path(args.output_dir) / "merged_model"
        base = AutoModelForCausalLM.from_pretrained(
            args.base_model,
            torch_dtype=torch.bfloat16,
            device_map="cpu",
            trust_remote_code=True,
        )
        merged = PeftModel.from_pretrained(base, str(adapter_dir)).merge_and_unload()
        merged.save_pretrained(str(merged_dir))
        tokenizer.save_pretrained(str(merged_dir))
        print(f"Birleştirilmiş model kaydedildi: {merged_dir}")


if __name__ == "__main__":
    main()
