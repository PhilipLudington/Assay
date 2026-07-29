#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Turns pilot transcripts into the numbers that go into FINDINGS.md.

Makes no API calls. Run it as often as you like.

    uv run pilot/analyze.py
    uv run pilot/analyze.py --window 20 --bootstrap 20000

Scoring caveat, stated up front because it bounds everything below: the real
semantic judge is Phase 3 work and does not exist yet. Detection here is a
crude proximity match against the seeded defect's location. It will disagree
with a human on genuine-but-oddly-located findings. Write a `labels.json` next
to the transcripts to override it per run — see `--help` output — and the
report will say which source it used.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import OUT_DIR, parse_failed, read_records

# Ground truth, mirroring the ANSWER.md files. Deliberately lives here and not
# in common.py: the scripts that build reviewer prompts import common.py, and
# they must have no path to the answer key at all.
SEEDED_DEFECTS: dict[str, dict[str, Any]] = {
    # Locality is what the pilot measured, not what the author intended. M-1
    # and L-1 were both authored as cross_file and both turned out reachable
    # from the floor — see pilot/FINDINGS.md, Q2.
    "small": {"id": "S-1", "file": "src/bucket.ts", "lines": (34, 36), "locality": "local"},
    "medium": {"id": "M-1", "file": "src/worker/pool.ts", "lines": (78, 88), "locality": "touched_file"},
    "large": {"id": "L-1", "file": "src/routes/shipments.ts", "lines": (81, 81), "locality": "touched_file"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=15, help="proximity window in lines")
    parser.add_argument("--bootstrap", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument(
        "--emit-labels",
        action="store_true",
        help=(
            "write out/labels.template.json — every run keyed and pre-filled "
            "with the heuristic's guess plus a digest of that run's findings, "
            "so it can be labelled by hand without reopening the transcripts. "
            "Correct the booleans, save it as out/labels.json, re-run."
        ),
    )
    return parser.parse_args()


def emit_label_template(records: list[dict], window: int) -> Path:
    """Builds a hand-labelling worksheet from the transcripts.

    The heuristic's verdict is the starting value, not the answer — the point
    of labelling is to overrule it where it is wrong.
    """
    template: dict[str, Any] = {
        "_README": [
            "Set each run's value to true if that run found the seeded defect.",
            "'guess' is the proximity heuristic; 'findings' is what the run said.",
            "Correct the flat <key>: bool pairs below, save this file as",
            "out/labels.json, then re-run analyze.py. The _README and _runs",
            "keys are ignored on load, so there is no need to strip them.",
        ],
        "_runs": {},
    }
    for record in sorted(records, key=run_key):
        key = run_key(record)
        defect = SEEDED_DEFECTS.get(record["fixture"], {})
        template["_runs"][key] = {
            "seeded_defect": f"{defect.get('id')} at {defect.get('file')}:{defect.get('lines')}",
            "guess": detected(record, window),
            "findings": [
                f"{f.get('file')}:{f.get('start_line')}-{f.get('end_line')} "
                f"[{f.get('severity')}] {str(f.get('message', ''))[:160]}"
                for f in record.get("findings", [])
                if isinstance(f, dict)
            ],
        }
        template[key] = detected(record, window)

    path = OUT_DIR / "labels.template.json"
    path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def partition(all_records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Splits transcripts into `(billed, scored)`.

    `billed` drops runs that failed outright — they produced nothing at all.
    `scored` additionally drops runs whose structured output would not parse:
    those navigated the repo and cost money, so they stay in the cost, caching
    and navigation tables, but their finding list is unknown and must not be
    read as an empty one.

    Lives here as a named function, not inline in `main`, so the exclusion can
    be tested rather than asserted — see tests/test_pilot_scoring.py.
    """
    billed = [r for r in all_records if not r.get("failed")]
    scored = [r for r in billed if not parse_failed(r)]
    return billed, scored


def run_key(record: dict) -> str:
    return "|".join(
        str(record.get(field, ""))
        for field in ("fixture", "mode", "reviewer", "stamp", "run_index")
    )


def detected(record: dict, window: int) -> bool:
    """Proximity gate: same file, line ranges within `window` lines."""
    defect = SEEDED_DEFECTS.get(record["fixture"])
    if defect is None:
        return False
    low, high = defect["lines"]
    for finding in record.get("findings", []):
        if not isinstance(finding, dict):
            continue
        if str(finding.get("file", "")).lstrip("./") != defect["file"]:
            continue
        raw_start = finding.get("start_line", 0)
        raw_end = finding.get("end_line", raw_start)
        # Reviewers occasionally emit the range backwards; a swapped range is
        # a formatting slip, not a different observation.
        start, end = min(raw_start, raw_end), max(raw_start, raw_end)
        if end >= low - window and start <= high + window:
            return True
    return False


def load_labels() -> dict[str, bool]:
    path = OUT_DIR / "labels.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def bootstrap_ci(
    observations: list[int], k: int, iterations: int, rng: random.Random
) -> tuple[float, float]:
    if not observations:
        return (0.0, 0.0)
    means = []
    for _ in range(iterations):
        sample = [observations[rng.randrange(len(observations))] for _ in range(k)]
        means.append(sum(sample) / k)
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[min(len(means) - 1, int(0.975 * len(means)))]
    return (lo, hi)


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def finding_keys(record: dict) -> set[tuple[str, int]]:
    """Bucket findings to (file, 10-line band) so trivially different line
    numbers for the same observation do not count as disagreement."""
    keys = set()
    for finding in record.get("findings", []):
        if isinstance(finding, dict):
            keys.add((str(finding.get("file", "")), int(finding.get("start_line", 0)) // 10))
    return keys


def heading(text: str) -> None:
    print(f"\n{text}\n{'─' * len(text)}")


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    all_records = list(read_records())
    # Three tiers, not two.
    #
    # A run that failed outright produced nothing and is gone entirely. A run
    # whose structured output would not parse is different: it still navigated
    # the repo and it still cost money, so it belongs in the navigation,
    # caching and cost tables. But its finding list is *unknown*, not empty —
    # scoring it as "found nothing" would silently depress detection, and
    # scoring it as a hit would invent a result. It leaves Q1 and only Q1.
    #
    # This is the exclusion the pilot did not make: both runners recorded
    # `parse_error` and this analyzer never read the field, so a parse failure
    # and a clean empty review were the same number. Incidence was 0/34, so no
    # published figure moved — but the control was absent, not merely unneeded.
    billed, scored = partition(all_records)
    failed = len(all_records) - len(billed)
    unparsed = len(billed) - len(scored)

    if not billed:
        print(f"no transcripts in {OUT_DIR}. Run run_singleshot.py / run_agentic.py first.")
        return 1

    if args.emit_labels:
        path = emit_label_template(scored, args.window)
        print(f"wrote {path} — {len(scored)} runs to label")
        if unparsed:
            print(f"({unparsed} unparseable run(s) omitted — there is nothing to label)")
        return 0

    labels = load_labels()
    label_hits = 0
    for record in scored:
        key = run_key(record)
        if key in labels:
            record["_detected"] = bool(labels[key])
            label_hits += 1
        else:
            record["_detected"] = detected(record, args.window)

    heading("Run accounting")
    print(f"{len(all_records):>4} run(s) on disk")
    print(f"{failed:>4} failed outright — excluded from every table")
    print(f"{unparsed:>4} returned unparseable output — kept in Q2/Q3/Q4, excluded from Q1")
    print(f"{len(scored):>4} scored across {len({r['fixture'] for r in scored})} fixtures")
    print(
        f"\ndetection source: {label_hits} hand-labelled, "
        f"{len(scored) - label_hits} by proximity heuristic (±{args.window} lines)"
    )

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for record in scored:
        groups[(record["fixture"], record["mode"], record["reviewer"])].append(record)

    # Per-group parse failures, so a group whose effective n has shrunk below
    # the K it was run at cannot look fully powered in the Q1 table.
    unparsed_by_group: dict[tuple[str, str, str], int] = defaultdict(int)
    for record in billed:
        if parse_failed(record):
            unparsed_by_group[
                (record["fixture"], record["mode"], record["reviewer"])
            ] += 1

    if unparsed:
        print(
            "\n⚠ An unparseable run is not a run that found nothing. Excluding it\n"
            "  shrinks n below the K these groups were run at; counting it would\n"
            "  invent a measurement. Affected groups:"
        )
        for (fixture, mode, reviewer), count in sorted(unparsed_by_group.items()):
            kept = len(groups.get((fixture, mode, reviewer), []))
            print(f"    {fixture}/{mode}/{reviewer}: {count} dropped, n={kept} remaining")

    if not scored:
        print("\nno scoreable runs — every run either failed or would not parse.")
        print("Q1 is skipped; the cost and navigation tables below still apply.")

    # --- Q1: variance and the choice of K ---------------------------------
    heading("Q1  Run-to-run variance → K")
    print("'pe' is runs dropped for unparseable output; n is what remains.\n")
    print(
        f"{'fixture/mode/reviewer':38} {'n':>3} {'pe':>3} {'detect':>7} "
        f"{'findings':>16} {'Jaccard':>8}"
    )
    for (fixture, mode, reviewer), runs in sorted(groups.items()):
        dropped = unparsed_by_group.get((fixture, mode, reviewer), 0)
        hits = [1 if r["_detected"] else 0 for r in runs]
        counts = [len(r.get("findings", [])) for r in runs]
        keysets = [finding_keys(r) for r in runs]
        pairs = [
            jaccard(keysets[i], keysets[j])
            for i in range(len(keysets))
            for j in range(i + 1, len(keysets))
        ]
        spread = f"{statistics.mean(counts):.1f}±{statistics.pstdev(counts):.1f}"
        print(
            f"{fixture + '/' + mode + '/' + reviewer:38} {len(runs):>3} {dropped:>3} "
            f"{sum(hits) / len(hits):>7.2f} {spread:>16} "
            f"{(statistics.mean(pairs) if pairs else float('nan')):>8.2f}"
        )

    heading("Q1  Bootstrap 95% CI half-width on detection rate, by K")
    print("A K is defensible when the interval is tight enough to call a")
    print("regression. Pick the threshold before looking at the numbers.\n")
    print(f"{'fixture/mode/reviewer':38} " + "".join(f"{'K=' + str(k):>14}" for k in (3, 5, 7, 10)))
    for (fixture, mode, reviewer), runs in sorted(groups.items()):
        hits = [1 if r["_detected"] else 0 for r in runs]
        if len(hits) < 3:
            continue
        cells = ""
        for k in (3, 5, 7, 10):
            lo, hi = bootstrap_ci(hits, k, args.bootstrap, rng)
            cells += f"{'±' + format((hi - lo) / 2, '.2f'):>14}"
        print(f"{fixture + '/' + mode + '/' + reviewer:38} {cells}")

    # --- Q2: navigation ----------------------------------------------------
    heading("Q2  Navigation behaviour (agentic runs only)")
    # `billed`, not `scored`: tool calls are observed directly from the
    # transcript, so a run whose final payload would not parse still navigated
    # and still counts here.
    agentic = [r for r in billed if r["mode"] == "read_tools"]
    if not agentic:
        print("no agentic transcripts yet.")
    else:
        print(
            f"{'fixture':10} {'src':>4} {'calls':>6} {'Read':>5} {'Glob':>5} {'Grep':>5} "
            f"{'files read':>11} {'% of repo':>10} {'read all?':>10}"
        )
        by_fixture: dict[str, list[dict]] = defaultdict(list)
        for record in agentic:
            by_fixture[record["fixture"]].append(record)
        for fixture, runs in sorted(by_fixture.items()):
            source_count = runs[0]["source_file_count"]
            totals = defaultdict(list)
            read_everything = 0
            for record in runs:
                calls = record.get("tool_calls", [])
                counts = defaultdict(int)
                read_paths = set()
                for call in calls:
                    counts[call["name"]] += 1
                    if call["name"] == "Read":
                        read_paths.add(str(call["input"].get("file_path", "")))
                totals["calls"].append(len(calls))
                for tool in ("Read", "Glob", "Grep"):
                    totals[tool].append(counts[tool])
                totals["files"].append(len(read_paths))
                # Navigation is trivial when the agent simply retrieves the
                # whole repo. Listing filenames with Glob is not that — a
                # `**/*.ts` glob returns the full tree at any repo size, so
                # counting it would mark every size trivial and answer nothing.
                if len(read_paths) >= source_count:
                    read_everything += 1
            mean = lambda key: statistics.mean(totals[key]) if totals[key] else 0.0
            print(
                f"{fixture:10} {source_count:>4} {mean('calls'):>6.1f} {mean('Read'):>5.1f} "
                f"{mean('Glob'):>5.1f} {mean('Grep'):>5.1f} {mean('files'):>11.1f} "
                f"{100 * mean('files') / source_count:>9.0f}% "
                f"{f'{read_everything}/{len(runs)}':>10}"
            )
        print(
            "\n'read all?' counts runs that read every source file in the repo —\n"
            "navigation was a slow `cat` and the agentic ceiling bought nothing at\n"
            "that size. The column that matters is '% of repo': the lower it is,\n"
            "the more the agent had to decide *what* to look at, which is the\n"
            "capability the read_tools mode is supposed to be testing."
        )

    # --- Q3: caching -------------------------------------------------------
    heading("Q3  Prompt caching")
    # Tokens were read and written whatever the payload looked like coming back.
    billed_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for record in billed:
        billed_groups[(record["fixture"], record["mode"], record["reviewer"])].append(record)

    print(f"{'fixture/mode/reviewer':38} {'run':>4} {'cache_write':>12} {'cache_read':>11} {'input':>9}")
    for (fixture, mode, reviewer), runs in sorted(billed_groups.items()):
        for record in sorted(runs, key=lambda r: r.get("run_index", 0)):
            usage = record.get("usage", {})
            print(
                f"{fixture + '/' + mode + '/' + reviewer:38} {record.get('run_index', 0):>4} "
                f"{usage.get('cache_creation_input_tokens', 0):>12} "
                f"{usage.get('cache_read_input_tokens', 0):>11} "
                f"{usage.get('input_tokens', 0):>9}"
            )
    print(
        "\nRead this two ways. Within one reviewer, a non-zero cache_read on runs\n"
        "after the first means repeat runs are cheap. Across two reviewers on the\n"
        "same fixture, a non-zero cache_read on the *second* reviewer's first run\n"
        "means the fixture-first prefix is genuinely shared — which is the claim\n"
        "DESIGN's cost-controls table rests on."
    )

    # --- Q4: cost ----------------------------------------------------------
    heading("Q4  Cost per run, and what a full sweep would cost")
    print(f"{'fixture':10} {'mode':12} {'src files':>10} {'mean $/run':>12} {'mean turns':>11}")
    cost_by: dict[tuple[str, str], list[float]] = defaultdict(list)
    turns_by: dict[tuple[str, str], list[int]] = defaultdict(list)
    # An unparseable run was still paid for. Dropping it here would understate
    # what a sweep actually costs, which is the opposite of the Q1 correction.
    for record in billed:
        key = (record["fixture"], record["mode"])
        if record.get("cost_usd") is not None:
            cost_by[key].append(record["cost_usd"])
        turns_by[key].append(record.get("num_turns", 1))
    for (fixture, mode), costs in sorted(cost_by.items()):
        source_count = next(r["source_file_count"] for r in billed if r["fixture"] == fixture)
        print(
            f"{fixture:10} {mode:12} {source_count:>10} {statistics.mean(costs):>12.4f} "
            f"{statistics.mean(turns_by[(fixture, mode)]):>11.1f}"
        )

    heading("Q4  Projected v1 sweep — DESIGN's actual reviewer mix")
    print("DESIGN's three v1 reviewers are SingleShotReviewer, AgentReviewer and")
    print("SarifReviewer. They do not cost the same thing, so a sweep is priced as")
    print("15 fixtures x K runs x (single-shot + agentic + SARIF), not as three")
    print("copies of the dearest one. SARIF shells out to an external tool and")
    print("makes no model calls, so it contributes $0 here.\n")

    per_size: dict[str, dict[str, float]] = defaultdict(dict)
    for (fixture, mode), costs in cost_by.items():
        per_size[fixture][mode] = statistics.mean(costs)

    print(
        f"{'repo size':26} {'1 sweep run':>12} " + "".join(f"{'K=' + str(k):>11}" for k in (3, 5, 7, 10))
    )
    for fixture, modes in sorted(per_size.items(), key=lambda kv: -len(kv[1])):
        if "single_shot" not in modes or "read_tools" not in modes:
            print(f"{fixture + ' (incomplete)':26} " + "  both modes not measured — cannot price")
            continue
        unit = modes["single_shot"] + modes["read_tools"]
        source_count = next(r["source_file_count"] for r in billed if r["fixture"] == fixture)
        cells = "".join(f"{0.5 * 15 * k * unit:>11.2f}" for k in (3, 5, 7, 10))
        print(f"{f'{fixture} ({source_count} files, batch)':26} {unit:>12.4f} {cells}")
        cells = "".join(f"{15 * k * unit:>11.2f}" for k in (3, 5, 7, 10))
        print(f"{f'{fixture} ({source_count} files, list)':26} {unit:>12.4f} {cells}")

    print("\nThe $50 DESIGN budget covers the sweep *plus* judge adjudication, which")
    print("is Phase 3 and unmeasured — so treat the batch row as a floor, not the")
    print("final bill. If the chosen repo size does not clear it, corpus size or K")
    print("moves, not the budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
