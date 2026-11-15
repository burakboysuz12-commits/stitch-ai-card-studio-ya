"""
mini_agent_history.db içindeki sohbetleri EVREN MLOps / LoRA ince ayar (SFT)
eğitimi için OpenAI/TRL uyumlu JSONL formatına dönüştürür.
"""

import argparse
import json
import os
import sqlite3
from pathlib import Path

DEFAULT_SYSTEM_PROMPT = (
    "Sen Burak'ın asistanı olarak çalışan, zeki, empatik ve yardımsever bir yapay zekâ asistanısın. "
    "Her zaman doğal, akıcı ve dilbilgisi açısından doğru Türkçe konuş."
)


def export_conversations_to_jsonl(
    db_path: str,
    output_dir: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    only_rated: bool = False,
    eval_ratio: float = 0.1,
) -> dict:
    """
    SQLite sohbet geçmişini eğitim (train) ve doğrulama (eval) JSONL dosyalarına aktarır.
    Her satır: {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Veritabanı bulunamadı: {db_path}")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        has_rating = "rating" in cols
        select_cols = "conversation_id, role, content, rating" if has_rating else "conversation_id, role, content, 0"
        rows = conn.execute(
            f"SELECT {select_cols} FROM messages "
            "WHERE role IN ('user', 'assistant') "
            "ORDER BY conversation_id ASC, created_at ASC"
        ).fetchall()

    # Konuşmaları sırayla grupla ve geçerli çok-turlu diyaloglar oluştur
    grouped: dict[str, list[dict]] = {}
    for conv_id, role, content, rating in rows:
        text = (content or "").strip()
        if not text:
            continue
        grouped.setdefault(conv_id, []).append({
            "role": role,
            "content": text,
            "rating": int(rating or 0),
        })

    samples: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for turns in grouped.values():
        # Ardışık aynı rolleri temizle ve (user -> assistant) çiftleri kur
        clean_turns: list[dict] = []
        for t in turns:
            if not clean_turns and t["role"] != "user":
                continue
            if clean_turns and clean_turns[-1]["role"] == t["role"]:
                clean_turns[-1] = t
            else:
                clean_turns.append(t)

        if len(clean_turns) < 2:
            continue

        # Eğer sadece beğenilen (rating == 1) cevaplar isteniyorsa filtrele
        if only_rated:
            for idx in range(len(clean_turns) - 1):
                u_turn, a_turn = clean_turns[idx], clean_turns[idx + 1]
                if u_turn["role"] == "user" and a_turn["role"] == "assistant" and a_turn["rating"] == 1:
                    key = (u_turn["content"], a_turn["content"])
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    samples.append({
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": u_turn["content"]},
                            {"role": "assistant", "content": a_turn["content"]},
                        ]
                    })
        else:
            # Son mesaj assistant değilse kırp
            if clean_turns[-1]["role"] != "assistant":
                clean_turns = clean_turns[:-1]
            if len(clean_turns) < 2:
                continue
            pair_key = (clean_turns[0]["content"], clean_turns[-1]["content"])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            msgs = [{"role": "system", "content": system_prompt}]
            msgs.extend({"role": t["role"], "content": t["content"]} for t in clean_turns)
            samples.append({"messages": msgs})

    eval_count = max(1, int(len(samples) * eval_ratio)) if len(samples) >= 5 else 0
    train_samples = samples[:-eval_count] if eval_count else samples
    eval_samples = samples[-eval_count:] if eval_count else []

    train_file = out_path / "dataset_train.jsonl"
    eval_file = out_path / "dataset_eval.jsonl"

    with open(train_file, "w", encoding="utf-8") as f:
        for item in train_samples:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(eval_file, "w", encoding="utf-8") as f:
        for item in eval_samples:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return {
        "total": len(samples),
        "train_count": len(train_samples),
        "eval_count": len(eval_samples),
        "train_file": str(train_file),
        "eval_file": str(eval_file),
    }


def main():
    root_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="EVREN SFT JSONL Veri Seti Oluşturucu")
    parser.add_argument("--db", default=str(root_dir / "mini_agent_history.db"), help="SQLite veritabanı yolu")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent), help="Çıktı klasörü")
    parser.add_argument("--only-rated", action="store_true", help="Sadece 👍 (rating=1) işaretli cevapları aktar")
    args = parser.parse_args()

    stats = export_conversations_to_jsonl(
        db_path=args.db,
        output_dir=args.out,
        only_rated=args.only_rated,
    )
    print(
        f"Tamamlandı: Toplam {stats['total']} örnek "
        f"(Train: {stats['train_count']} -> {stats['train_file']}, "
        f"Eval: {stats['eval_count']} -> {stats['eval_file']})"
    )


if __name__ == "__main__":
    main()
