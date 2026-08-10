#!/usr/bin/env python3
"""Upload datasets/harness-llm/huggingface to the Hugging Face Hub.

Requires: pip install huggingface_hub
Auth: huggingface-cli login  OR  HF_TOKEN env var

Example:
  python3 datasets/harness-llm/scripts/upload_huggingface.py \\
    --repo-id SafetyMP/corporate-site-harness-training-data
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HF_DIR = Path(__file__).resolve().parents[1] / "huggingface"
DEFAULT_DATASET_REPO = "SafetyMP/corporate-site-harness-training-data"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_DATASET_REPO,
        help=f"Hub dataset repo (default: {DEFAULT_DATASET_REPO})",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create/update as a private dataset",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HF_TOKEN"),
        help="HF token (default: HF_TOKEN env)",
    )
    args = parser.parse_args()

    if not HF_DIR.is_dir() or not (HF_DIR / "data" / "train.jsonl").is_file():
        print(
            "Missing export. Run: python3 datasets/harness-llm/scripts/export_huggingface.py",
            file=sys.stderr,
        )
        return 1

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Install huggingface_hub: pip install huggingface_hub", file=sys.stderr)
        return 1

    api = HfApi(token=args.token)
    api.create_repo(
        repo_id=args.repo_id,
        repo_type="dataset",
        private=args.private,
        exist_ok=True,
    )
    api.upload_folder(
        folder_path=str(HF_DIR),
        repo_id=args.repo_id,
        repo_type="dataset",
        commit_message="Upload corporate-site-harness LLM SFT dataset",
    )
    print(f"Uploaded: https://huggingface.co/datasets/{args.repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
