#!/usr/bin/env python3
"""Lean premium-model policy reminder for Cursor hooks (<1k tokens)."""

from __future__ import annotations

import argparse
import json
import sys


REMINDER = (
    "Premium model policy: run `corp-harness route-model` before Task/subagent. "
    "Sol/Fable only for hard_implement (or escalated packet_implement/remediate). "
    "Never premium for recapture/review/first remediate. Attest model_id/model_class/"
    "task_class on packets; PREMIUM_MODEL_POLICY fails gates."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default="sessionStart")
    args = parser.parse_args(argv)
    # Cursor hook contract: print JSON additional_context when useful.
    payload = {
        "additional_context": REMINDER,
        "event": args.event,
        "policy": "corporate-site-execution-policy/v1",
    }
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
