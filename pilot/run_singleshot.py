#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic>=0.120"]
# ///
"""Single-shot reviewer: Client SDK, floor context only, no tools.

Answers Q1 (run-to-run variance, and therefore K) and contributes the
single-shot half of Q3 (caching) and Q4 (cost).

The fixture content goes **first** in the system block behind a cache
breakpoint, with the reviewer-specific instructions after it — the ordering
DESIGN's cost-controls table depends on. Run two different reviewers against
one fixture and the second should read the first one's cache.

    uv run pilot/run_singleshot.py --fixture small --runs 10
    uv run pilot/run_singleshot.py --fixture small --reviewers correctness,security
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import anthropic

from common import (
    DEFAULT_MODEL,
    FINDING_SCHEMA,
    REVIEWERS,
    append_record,
    cost_usd,
    load_fixture,
    review_task,
    transcript_path,
    utc_stamp,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, choices=["small", "medium", "large"])
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--reviewers", default="correctness")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-tokens", type=int, default=16_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixture = load_fixture(args.fixture)
    reviewers = [r.strip() for r in args.reviewers.split(",") if r.strip()]
    unknown = [r for r in reviewers if r not in REVIEWERS]
    if unknown:
        print(f"unknown reviewer(s): {unknown}; known: {list(REVIEWERS)}", file=sys.stderr)
        return 2

    client = anthropic.Anthropic()
    stamp = utc_stamp()
    task = review_task(fixture)

    total_cost = 0.0
    for reviewer in reviewers:
        path = transcript_path("singleshot", fixture.name, reviewer, stamp)
        print(f"→ {reviewer} x{args.runs} on {fixture.name} → {path.name}")

        for run_index in range(args.runs):
            started = time.monotonic()
            response = client.messages.create(
                model=args.model,
                max_tokens=args.max_tokens,
                output_config={
                    "effort": args.effort,
                    "format": {"type": "json_schema", "schema": FINDING_SCHEMA},
                },
                # Fixture first, behind the breakpoint. Reviewer instructions
                # after it, so every reviewer on this fixture shares a prefix.
                system=[
                    {
                        "type": "text",
                        "text": task,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": REVIEWERS[reviewer]},
                ],
                messages=[
                    {
                        "role": "user",
                        "content": "Review the change described in the system context.",
                    }
                ],
            )

            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                findings = json.loads(text)["findings"]
                parse_error = None
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                findings, parse_error = [], f"{type(error).__name__}: {error}"

            usage = response.usage
            run_cost = cost_usd(
                args.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_creation_input_tokens or 0,
                usage.cache_read_input_tokens or 0,
            )
            total_cost += run_cost

            append_record(
                path,
                {
                    "mode": "single_shot",
                    "fixture": fixture.name,
                    "reviewer": reviewer,
                    "run_index": run_index,
                    "model": response.model,
                    "stop_reason": response.stop_reason,
                    "source_file_count": len(fixture.source_files()),
                    "touched_files": fixture.touched_files(),
                    "findings": findings,
                    "parse_error": parse_error,
                    "usage": {
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
                        "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
                    },
                    "cost_usd": run_cost,
                    "wall_seconds": round(time.monotonic() - started, 2),
                    "tool_calls": [],
                    "stamp": stamp,
                },
            )

            print(
                f"   run {run_index}: {len(findings):2d} findings  "
                f"cache_read={usage.cache_read_input_tokens or 0:>6}  "
                f"${run_cost:.4f}"
                + (f"  PARSE ERROR {parse_error}" if parse_error else "")
            )

    print(f"total spend this invocation: ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
