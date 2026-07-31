"""Agentic reviewer: Agent SDK, floor context plus read-only repo navigation.

**Run this with the project venv, not `uv run --script`:**

    .venv/bin/python pilot/run_agentic.py --fixture medium --runs 2

The standalone-script header is gone because this now imports the real
answer-key boundary — and the reviewer's tool policy — from `assay.executor`.
That is the one place the pilot depends on production code, and it is
deliberate: the Phase 1 gate forbids any measurement run while the boundary is
unenforced, and the locality-verification run happens on this harness.
Duplicating the boundary here would mean the control that is tested and the
control that runs are different code. The same argument applies to
`READ_ONLY_TOOLS`/`DENIED_TOOLS`: they were duplicated once, drifted on
`TodoWrite`, and the probe that certifies the boundary was measuring a
configuration this script does not run. See `assay.executor.policy`.


Answers Q2 (is Glob/Grep navigation non-trivial at this repo size?) and the
agentic half of Q3 (caching) and Q4 (cost).

On Q3, note what this script can and cannot do. `ClaudeAgentOptions.system_prompt`
takes a **single string** — there is no way to pass several system blocks or to
place a `cache_control` breakpoint. So the fixture content is put at the *front*
of that one string and the reviewer instructions after it, which is the closest
reachable approximation of the DESIGN ordering. Whether that shared prefix
actually earns a cache read across reviewers is exactly what we measure:
compare `cache_read_input_tokens` on the second reviewer against the first.

    .venv/bin/python pilot/run_agentic.py --fixture medium --runs 2 \\
        --reviewers correctness,security
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from assay.executor.hooks import confinement_hooks
from assay.executor.policy import DENIED_TOOLS, READ_ONLY_TOOLS
from common import (
    DEFAULT_MODEL,
    FINDING_SCHEMA,
    REVIEWERS,
    append_record,
    extract_findings,
    load_fixture,
    review_task,
    transcript_path,
    utc_stamp,
)

USER_PROMPT = (
    "Review the change described in your instructions. You may read the "
    "repository with Read, Glob and Grep to check anything the diff does not "
    "show you. When you are done, return your findings."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, choices=["small", "medium", "large"])
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--reviewers", default="correctness")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--retries", type=int, default=2, help="retries per run on transient SDK errors")
    parser.add_argument(
        "--run-timeout",
        type=float,
        default=300.0,
        help="per-run wall-clock deadline in seconds; the SDK stream can stall indefinitely",
    )
    return parser.parse_args()


async def one_run(fixture, reviewer: str, args) -> dict:
    """Runs the agentic reviewer once and returns a transcript record."""
    # The answer-key boundary. `cwd` alone is not a control — the pilot's own
    # transcripts show 22 attempts at absolute paths outside it, which failed
    # only because those paths did not exist. This denies them for cause and
    # records every attempt.
    boundary, hooks = confinement_hooks(fixture.repo)

    options = ClaudeAgentOptions(
        model=args.model,
        effort=args.effort,
        cwd=str(fixture.repo),
        allowed_tools=READ_ONLY_TOOLS,
        disallowed_tools=DENIED_TOOLS,
        hooks=hooks,
        # Approval is not the control; the PreToolUse hook above is. Note that
        # this mode is precisely why the boundary cannot be a `can_use_tool`
        # callback — it would never be invoked. See `assay.executor.hooks`.
        permission_mode="bypassPermissions",
        # Do not inherit the operator's CLAUDE.md, settings or skills; they
        # would silently change what the reviewer is told.
        setting_sources=[],
        # Fixture content first, reviewer instructions after, so the leading
        # bytes are identical across reviewers on this fixture.
        system_prompt=review_task(fixture) + "\n\n" + REVIEWERS[reviewer],
        max_turns=args.max_turns,
        output_format={"type": "json_schema", "schema": FINDING_SCHEMA},
    )

    tool_calls: list[dict] = []
    tool_results: dict[str, dict] = {}
    result: ResultMessage | None = None
    started = time.monotonic()

    async for message in query(prompt=USER_PROMPT, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    tool_calls.append(
                        {"id": block.id, "name": block.name, "input": block.input}
                    )
        elif isinstance(message, UserMessage):
            for block in message.content if isinstance(message.content, list) else []:
                if isinstance(block, ToolResultBlock):
                    content = block.content
                    text = content if isinstance(content, str) else str(content)
                    tool_results[block.tool_use_id] = {
                        "chars": len(text),
                        "lines": text.count("\n") + 1,
                        "is_error": bool(getattr(block, "is_error", False)),
                    }
        elif isinstance(message, ResultMessage):
            result = message

    if result is None:
        raise RuntimeError("agent stream ended without a ResultMessage")

    for call in tool_calls:
        call["result"] = tool_results.get(call["id"])

    findings, parse_error = extract_findings(result.structured_output)

    model_usage = {
        name: dict(usage) for name, usage in (result.model_usage or {}).items()
    }
    cache_read = sum(u.get("cacheReadInputTokens", 0) for u in model_usage.values())
    cache_creation = sum(u.get("cacheCreationInputTokens", 0) for u in model_usage.values())

    return {
        "mode": "read_tools",
        "fixture": fixture.name,
        "reviewer": reviewer,
        "model": args.model,
        "source_file_count": len(fixture.source_files()),
        "touched_files": fixture.touched_files(),
        "findings": findings,
        "parse_error": parse_error,
        # Persisted, not just blocked: an attempted escape is evidence about
        # the fixture even when the boundary holds.
        "boundary_violations": boundary.records(),
        "boundary_violations_suppressed": boundary.suppressed_violations,
        "usage": {
            "input_tokens": sum(u.get("inputTokens", 0) for u in model_usage.values()),
            "output_tokens": sum(u.get("outputTokens", 0) for u in model_usage.values()),
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        },
        "model_usage": model_usage,
        # The Agent SDK reports cost directly; we trust it over our own table.
        "cost_usd": result.total_cost_usd,
        "num_turns": result.num_turns,
        "wall_seconds": round(time.monotonic() - started, 2),
        "tool_calls": tool_calls,
        "is_error": result.is_error,
    }


async def main_async() -> int:
    args = parse_args()
    fixture = load_fixture(args.fixture)
    reviewers = [r.strip() for r in args.reviewers.split(",") if r.strip()]
    unknown = [r for r in reviewers if r not in REVIEWERS]
    if unknown:
        print(f"unknown reviewer(s): {unknown}; known: {list(REVIEWERS)}", file=sys.stderr)
        return 2

    stamp = utc_stamp()
    total_cost = 0.0

    for reviewer in reviewers:
        path = transcript_path("agentic", fixture.name, reviewer, stamp)
        print(f"→ {reviewer} x{args.runs} on {fixture.name} → {path.name}")

        for run_index in range(args.runs):
            # The Agent SDK surfaces transient stream failures as bare
            # exceptions. One bad run must not discard the runs already paid
            # for, so retry a couple of times and then record the failure and
            # keep going — a dropped run is a smaller lie than a dropped batch.
            record = None
            for attempt in range(1, args.retries + 2):
                try:
                    # The SDK stream can stall indefinitely — observed once at
                    # ~29 minutes against an ~85s median. Without a deadline a
                    # sweep hangs rather than fails, which is worse: it burns
                    # wall clock and reports nothing.
                    record = await asyncio.wait_for(
                        one_run(fixture, reviewer, args), timeout=args.run_timeout
                    )
                    break
                except asyncio.TimeoutError:
                    print(f"   run {run_index} attempt {attempt} timed out after {args.run_timeout}s")
                    if attempt > args.retries:
                        append_record(
                            path,
                            {
                                "mode": "read_tools",
                                "fixture": fixture.name,
                                "reviewer": reviewer,
                                "run_index": run_index,
                                "stamp": stamp,
                                "failed": True,
                                "error": f"timed out after {args.run_timeout}s",
                            },
                        )
                except Exception as error:  # noqa: BLE001 - deliberately broad
                    print(f"   run {run_index} attempt {attempt} failed: {error}")
                    if attempt > args.retries:
                        append_record(
                            path,
                            {
                                "mode": "read_tools",
                                "fixture": fixture.name,
                                "reviewer": reviewer,
                                "run_index": run_index,
                                "stamp": stamp,
                                "failed": True,
                                "error": str(error),
                            },
                        )
                    else:
                        await asyncio.sleep(5 * attempt)
            if record is None:
                continue

            record["run_index"] = run_index
            record["stamp"] = stamp
            append_record(path, record)
            total_cost += record["cost_usd"] or 0.0

            by_tool: dict[str, int] = {}
            for call in record["tool_calls"]:
                by_tool[call["name"]] = by_tool.get(call["name"], 0) + 1
            blocked = len(record["boundary_violations"])
            print(
                f"   run {run_index}: {len(record['findings']):2d} findings  "
                f"tools={by_tool or '{}'}  turns={record['num_turns']}  "
                f"cache_read={record['usage']['cache_read_input_tokens']:>7}  "
                f"${record['cost_usd'] or 0:.4f}"
                + (f"  ⚠ {blocked} blocked" if blocked else "")
                + (f"  PARSE ERROR {record['parse_error']}" if record["parse_error"] else "")
            )

    print(f"total spend this invocation: ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
