"""Tests the pilot's parse-failure handling.

**This file dies with `pilot/`** at the end of Phase 1, together with the code
it covers. It lives in `tests/` rather than beside the pilot scripts for one
reason: `pyproject.toml` sets `testpaths = ["tests"]`, so a test anywhere else
would not run in the suite, and a test that does not run is not a gate. The
Phase 1 gate forbids measurement runs until this blocker is closed, and the
locality-verification and K runs both execute on this harness — so the
exclusion has to be proven before those runs, not after.

What is covered is the rule, not the plumbing: *an empty finding list means
one of two completely different things, and the analyzer must tell them
apart.* The rule outlives the pilot — Phase 4's scorer inherits it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The pilot scripts import each other flat (`from common import ...`), so the
# pilot directory itself has to be importable.
PILOT_DIR = Path(__file__).resolve().parent.parent / "pilot"
sys.path.insert(0, str(PILOT_DIR))

pytest.importorskip("common", reason="pilot/ has been deleted; this test goes with it")

import run_singleshot  # noqa: E402
from analyze import partition  # noqa: E402
from common import extract_findings, parse_failed  # noqa: E402
from run_singleshot import run_with_retries  # noqa: E402

# --- extract_findings: the empty list must be earned -------------------------


def test_well_formed_payload_yields_findings_and_no_error():
    payload = {"findings": [{"file": "src/a.ts", "start_line": 1, "end_line": 2}]}
    findings, error = extract_findings(payload)
    assert error is None
    assert len(findings) == 1


def test_genuinely_empty_review_is_not_a_parse_error():
    """The case the whole exclusion hinges on. A reviewer that looked and found
    nothing returns `[]` with no error, and that is a real, scoreable result —
    the fix must not turn every empty review into a dropped run."""
    findings, error = extract_findings({"findings": []})
    assert findings == []
    assert error is None
    assert not parse_failed({"findings": findings, "parse_error": error})


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        (None, "no structured output"),
        ([], "not an object"),
        ("findings: none", "not an object"),
        ({}, "no 'findings' key"),
        ({"result": []}, "no 'findings' key"),
        ({"findings": None}, "not a list"),
        ({"findings": {"file": "a.ts"}}, "not a list"),
        ({"findings": ["a string, not a finding"]}, "not objects"),
        ({"findings": [{"file": "a.ts"}, 42]}, "not objects"),
    ],
)
def test_malformed_payloads_report_an_error_and_never_a_silent_empty_list(
    payload, expected_fragment
):
    findings, error = extract_findings(payload)
    assert findings == []
    assert error is not None, f"{payload!r} produced [] with no parse_error"
    assert expected_fragment in error
    assert parse_failed({"findings": findings, "parse_error": error})


def test_missing_findings_key_is_not_treated_as_an_empty_review():
    """`structured.get("findings", [])` — the shape both runners used — made a
    schema violation indistinguishable from a clean empty review."""
    _, error = extract_findings({"unexpected": "shape"})
    assert error is not None


# --- partition: which table each tier lands in -------------------------------


def _record(**overrides) -> dict:
    base = {
        "fixture": "small",
        "mode": "single_shot",
        "reviewer": "correctness",
        "findings": [],
        "parse_error": None,
        "cost_usd": 0.10,
    }
    return {**base, **overrides}


def test_clean_runs_are_both_billed_and_scored():
    billed, scored = partition([_record(), _record()])
    assert len(billed) == 2
    assert len(scored) == 2


def test_outright_failure_is_dropped_from_everything():
    billed, scored = partition([_record(), {"failed": True, "error": "boom"}])
    assert len(billed) == 1
    assert len(scored) == 1


def test_unparseable_run_is_billed_but_not_scored():
    """The blocker in one assertion: it still cost money, so it stays in the
    cost table; its finding list is unknown, so it leaves the detection table."""
    records = [_record(), _record(parse_error="no 'findings' key")]
    billed, scored = partition(records)
    assert len(billed) == 2, "an unparseable run was still paid for"
    assert len(scored) == 1, "an unparseable run is not a run that found nothing"


def test_unparseable_run_does_not_depress_the_detection_rate():
    """Before the fix, the parse failure below arrived as `findings: []` and
    scored as a miss, halving a detection rate that should read 1.00."""
    records = [
        _record(findings=[{"file": "src/bucket.ts", "start_line": 34, "end_line": 36}]),
        _record(parse_error="JSONDecodeError: Expecting value"),
    ]
    _, scored = partition(records)
    detection = sum(1 for r in scored if r["findings"]) / len(scored)
    assert detection == 1.0

    naive = [r for r in records if not r.get("failed")]
    assert sum(1 for r in naive if r["findings"]) / len(naive) == 0.5


def test_cost_still_counts_the_unparseable_run():
    billed, _ = partition([_record(), _record(parse_error="boom")])
    assert sum(r["cost_usd"] for r in billed) == pytest.approx(0.20)


# --- run_with_retries: a failure costs one run, never the batch --------------


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    """The backoff is real seconds in production and pointless here."""
    monkeypatch.setattr(run_singleshot.time, "sleep", lambda _: None)


def test_success_on_the_first_attempt_does_not_retry():
    calls = []

    def run_fn():
        calls.append(1)
        return {"findings": []}

    record, error = run_with_retries(run_fn, retries=2, label="run 0")
    assert record == {"findings": []}
    assert error is None
    assert len(calls) == 1


def test_transient_failure_is_retried_and_the_run_survives():
    attempts = []

    def run_fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("overloaded")
        return {"findings": [], "recovered": True}

    record, error = run_with_retries(run_fn, retries=2, label="run 0")
    assert record is not None and record["recovered"]
    assert error is None
    assert len(attempts) == 3, "should retry twice before succeeding"


def test_exhausted_retries_return_an_error_instead_of_raising():
    """The batch-killing behaviour, inverted: the exception must stop here so
    the caller can record the dead run and move to the next one."""
    attempts = []

    def run_fn():
        attempts.append(1)
        raise ConnectionError("still overloaded")

    record, error = run_with_retries(run_fn, retries=2, label="run 0")
    assert record is None
    assert error is not None
    assert "ConnectionError" in error and "still overloaded" in error
    assert len(attempts) == 3, "1 initial attempt + 2 retries"


def test_zero_retries_still_attempts_once():
    attempts = []

    def run_fn():
        attempts.append(1)
        raise RuntimeError("nope")

    record, _ = run_with_retries(run_fn, retries=0, label="run 0")
    assert record is None
    assert len(attempts) == 1


def test_a_dead_run_does_not_abort_the_runs_after_it():
    """The regression this blocker names: one bad call used to discard every
    remaining run in the batch. Here run 1 dies and runs 2 and 3 still happen."""
    completed, recorded = [], []
    for index in range(4):

        def run_fn(i=index):
            if i == 1:
                raise ConnectionError("transient")
            return {"run_index": i}

        record, error = run_with_retries(run_fn, retries=1, label=f"run {index}")
        if record is None:
            recorded.append({"run_index": index, "failed": True, "error": error})
        else:
            completed.append(record)

    assert [r["run_index"] for r in completed] == [0, 2, 3]
    assert len(recorded) == 1

    # And the failure is visible to the analyzer rather than being a silent gap.
    billed, scored = partition(completed + recorded)
    assert len(billed) == 3
    assert len(scored) == 3
