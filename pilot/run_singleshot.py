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
    extract_findings,
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
    parser.add_argument("--retries", type=int, default=2, help="retries per run on transient API errors")
    parser.add_argument(
        "--run-timeout",
        type=float,
        default=300.0,
        help="per-request deadline in seconds; a stall must cost one run, not the batch",
    )
    return parser.parse_args()


def one_run(client, fixture, reviewer: str, task: str, args) -> dict:
    """Runs the single-shot reviewer once and returns a transcript record."""
    started = time.monotonic()
    response = client.messages.create(
        model=args.model,
        max_tokens=args.max_tokens,
        timeout=args.run_timeout,
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
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        findings, parse_error = [], f"JSONDecodeError: {error}"
    else:
        findings, parse_error = extract_findings(payload)

    usage = response.usage
    run_cost = cost_usd(
        args.model,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_creation_input_tokens or 0,
        usage.cache_read_input_tokens or 0,
    )

    return {
        "mode": "single_shot",
        "fixture": fixture.name,
        "reviewer": reviewer,
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
    }


def run_with_retries(run_fn, retries: int, label: str) -> tuple[dict | None, str | None]:
    """Calls `run_fn`, retrying transient failures with a linear backoff.

    Returns `(record, None)` on success or `(None, last_error)` once the
    retries are spent — never raises, because the caller's job is to record the
    dead run and carry on to the next one.

    A named function rather than an inline `try` so the failure path can be
    tested without an API key. The bug being fixed here was an *untested*
    failure path: this script had no `try` at all, so a single transient error
    aborted the batch and silently skipped every run after it.
    """
    last_error: str | None = None
    for attempt in range(1, retries + 2):
        try:
            return run_fn(), None
        except Exception as error:  # noqa: BLE001 - deliberately broad
            last_error = f"{type(error).__name__}: {error}"
            print(f"   {label} attempt {attempt} failed: {error}")
            if attempt <= retries:
                time.sleep(5 * attempt)
    return None, last_error


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
            # Backported from run_agentic.py, where it was added mid-pilot after
            # a transient error aborted a batch. This path had no `try` at all,
            # so one bad call discarded every run after it as well as the runs
            # already paid for. Retry, then record the failure and keep going —
            # a dropped run is a smaller lie than a dropped batch, and a
            # recorded failure is a smaller lie than a silent gap.
            record, error = run_with_retries(
                # `rev=reviewer` binds the loop variable rather than closing
                # over it — harmless today because the call is immediate, a
                # cross-reviewer mix-up the moment it is not.
                lambda rev=reviewer: one_run(client, fixture, rev, task, args),
                args.retries,
                f"run {run_index}",
            )
            if record is None:
                # Recorded, not skipped. A gap in the transcripts would let
                # analyze.py report a smaller n as if it were the intended K.
                append_record(
                    path,
                    {
                        "mode": "single_shot",
                        "fixture": fixture.name,
                        "reviewer": reviewer,
                        "run_index": run_index,
                        "stamp": stamp,
                        "failed": True,
                        "error": error,
                    },
                )
                continue

            record["run_index"] = run_index
            record["stamp"] = stamp
            append_record(path, record)
            total_cost += record["cost_usd"]

            parse_error = record["parse_error"]
            print(
                f"   run {run_index}: {len(record['findings']):2d} findings  "
                f"cache_read={record['usage']['cache_read_input_tokens']:>6}  "
                f"${record['cost_usd']:.4f}"
                + (f"  PARSE ERROR {parse_error}" if parse_error else "")
            )

    print(f"total spend this invocation: ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
