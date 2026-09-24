"""Show how candidate decay policies distribute weight across news age."""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intelligence.news.benchmark import benchmark_decay_profiles


def main() -> int:
    ages = (0, 24, 72, 168, 720)
    print("Synthetic age-only sensitivity profile; no live news or financial data.")
    print("Article ages (hours): " + ", ".join(str(age) for age in ages))
    for profile in benchmark_decay_profiles(ages):
        weights = ", ".join(f"{weight:.1%}" for weight in profile.normalized_weights)
        print(
            f"{profile.name}: weights=[{weights}] "
            f"newest={profile.newest_share:.1%} oldest={profile.oldest_share:.3%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
