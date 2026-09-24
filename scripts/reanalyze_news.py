"""Re-score stored news with the currently configured safe sentiment backend."""

from __future__ import annotations

import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import build_sentiment_model


def main() -> int:
    load_dotenv()
    repository = SQLiteNewsRepository(
        os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")
    )
    model = build_sentiment_model()
    changed = 0
    try:
        for item in repository.all_items():
            repository.update_sentiment(item.id, model.analyze(item))
            changed += 1
    finally:
        repository.connection.close()
    print(f"reanalyzed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
