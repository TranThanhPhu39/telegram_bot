"""Bounded CPU smoke test for the configured Vietnamese sentiment model."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    import torch

    name = os.getenv("SENTIMENT_MODEL_NAME", "FiinGroup/phobert-finetuned")
    cache = os.getenv("SENTIMENT_MODEL_CACHE_DIR", ".model-cache/huggingface")
    tokenizer = AutoTokenizer.from_pretrained(name, cache_dir=cache)
    model = AutoModelForSequenceClassification.from_pretrained(name, cache_dir=cache)
    model.to("cpu")
    model.eval()
    encoded = tokenizer(
        "ACB công bố lợi nhuận tăng mạnh trong quý mới",
        return_tensors="pt", truncation=True, max_length=256,
    )
    with torch.no_grad():
        probabilities = torch.softmax(model(**encoded).logits, dim=-1)[0].tolist()
    print(json.dumps({
        "model": name,
        "labels": model.config.id2label,
        "probabilities": probabilities,
        "sum": sum(probabilities),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
