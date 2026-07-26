"""The closed defect-class taxonomy for the TypeScript corpus.

Closed, deliberately. An open vocabulary would make per-class recall
uncomputable — every fixture would land in its own class of one, and the
published table would be a list of anecdotes. A closed set also lets a
reviewer's `claimed_class` be checked against something.

Seven classes, chosen so that 15 v1 fixtures give roughly two per class. That
is thin, and the README says so next to any per-class number; it is the
smallest set that still spans the three reviewer specializations DESIGN
assumes (correctness, error handling, security) rather than quietly measuring
one of them three times.

Each entry records *why it is in the set*. A class earns its place by being
(a) genuinely reachable in idiomatic TypeScript that the compiler accepts,
and (b) distinguishable from every other class by a reviewer's description
alone — if two classes cannot be told apart from a finding's text, they are
one class and the judge would be adjudicating a distinction that does not
exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DefectClass(StrEnum):
    NULL_DEREFERENCE = "null-dereference"
    BOUNDARY_ERROR = "boundary-error"
    ASYNC_RACE = "async-race"
    MISSING_GUARD = "missing-guard"
    ERROR_MISHANDLING = "error-mishandling"
    BROKEN_INVARIANT = "broken-invariant"
    ACCESS_CONTROL = "access-control"


class Locality(StrEnum):
    """How far from the diff the evidence for a defect lives.

    Assigned by measurement, never by the fixture author — see
    `assay.corpus.locality`. The Phase 0 pilot had two of three
    author-assigned tags wrong, in both cases because the touched file itself
    leaked the evidence.
    """

    #: Visible in the diff hunks alone.
    LOCAL = "local"
    #: Needs the full contents of a file the diff touches, but nothing more.
    TOUCHED_FILE = "touched_file"
    #: Needs a file the diff does not touch.
    CROSS_FILE = "cross_file"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ClassDefinition:
    name: DefectClass
    summary: str
    rationale: str
    distinguished_from: str


TAXONOMY: dict[DefectClass, ClassDefinition] = {
    DefectClass.NULL_DEREFERENCE: ClassDefinition(
        name=DefectClass.NULL_DEREFERENCE,
        summary="A value that can be null or undefined is used as though it cannot be.",
        rationale=(
            "TypeScript's strictNullChecks eliminates the easy cases, which is "
            "exactly what makes the survivors worth measuring: they arrive through "
            "non-null assertions, `any` at an I/O boundary, index access without "
            "noUncheckedIndexedAccess, or a cast that outlived the shape it "
            "described. A reviewer that only pattern-matches on `!` will miss them."
        ),
        distinguished_from=(
            "MISSING_GUARD — that is an absent check on a value that is present; "
            "this is a present value that may be absent."
        ),
    ),
    DefectClass.BOUNDARY_ERROR: ClassDefinition(
        name=DefectClass.BOUNDARY_ERROR,
        summary="Off-by-one, wrong comparison operator, or an incorrect range or limit.",
        rationale=(
            "The classic, and it survives every type system, so it is a fair test "
            "of reading rather than of tooling. Includes pagination cursors, slice "
            "bounds, retry counts and clamped arithmetic — the pilot's own S-1 "
            "(a floored refill that discarded its remainder) sat here."
        ),
        distinguished_from=(
            "BROKEN_INVARIANT — a boundary error computes the wrong number; a "
            "broken invariant computes the right number and records it wrongly."
        ),
    ),
    DefectClass.ASYNC_RACE: ClassDefinition(
        name=DefectClass.ASYNC_RACE,
        summary="Incorrect behaviour arising from interleaving across an await point.",
        rationale=(
            "Single-threaded JavaScript makes developers assume atomicity that "
            "`await` does not provide, and the resulting window is invisible in "
            "the diff — you have to know what else can run. Includes missing "
            "await, check-then-act across a yield, and unsynchronised "
            "read-modify-write. The pilot's M-1 was this shape."
        ),
        distinguished_from=(
            "ERROR_MISHANDLING — a missing `await` that loses a rejection is "
            "error mishandling; a missing `await` that lets two operations "
            "interleave is a race. Classify by the consequence, not the syntax."
        ),
    ),
    DefectClass.MISSING_GUARD: ClassDefinition(
        name=DefectClass.MISSING_GUARD,
        summary="A required precondition, validation or bounds check is absent or wrong.",
        rationale=(
            "The failure mode DESIGN's review-context contract is built around: "
            "removing a guard shows up in a diff as a deletion and nothing else, "
            "so it is the sharpest available test of whether a reviewer reasons "
            "about what *should* be there rather than reviewing what is."
        ),
        distinguished_from=(
            "ACCESS_CONTROL — a missing authorization check is access control "
            "even though it is also a missing guard; prefer the more specific class."
        ),
    ),
    DefectClass.ERROR_MISHANDLING: ClassDefinition(
        name=DefectClass.ERROR_MISHANDLING,
        summary="An error is swallowed, mis-typed, mis-propagated, or left unhandled.",
        rationale=(
            "Warrants its own class because one of the three v1 reviewers "
            "specializes in it, and because it is where TypeScript is weakest: "
            "`catch` binds `unknown`, rejections are untyped, and nothing in the "
            "compiler notices a promise nobody awaited. Includes empty catch "
            "blocks, catching too broadly, and losing the original cause."
        ),
        distinguished_from=(
            "MISSING_GUARD — a guard prevents the bad state; error handling "
            "responds to it once it happens."
        ),
    ),
    DefectClass.BROKEN_INVARIANT: ClassDefinition(
        name=DefectClass.BROKEN_INVARIANT,
        summary=(
            "A write path bypasses bookkeeping the rest of the system depends on, "
            "or drives an object into a state its own rules forbid."
        ),
        rationale=(
            "The most valuable class for the cross-file question, because the "
            "invariant is stated somewhere other than the code that breaks it, "
            "and nothing at the call site looks wrong. Includes invalid state "
            "transitions and writes that skip an audit or event log. The pilot's "
            "L-1 was this."
        ),
        distinguished_from=(
            "ASYNC_RACE — a race breaks an invariant only under interleaving; "
            "this breaks it on every single-threaded execution."
        ),
    ),
    DefectClass.ACCESS_CONTROL: ClassDefinition(
        name=DefectClass.ACCESS_CONTROL,
        summary="A missing, weaker-than-required, or wrongly-scoped authorization check.",
        rationale=(
            "The one security class in v1. Chosen over injection and secret "
            "handling because it is reachable in ordinary application code without "
            "contriving an I/O-heavy fixture, and because it is the security defect "
            "most likely to need cross-file reasoning — the scope hierarchy is "
            "rarely in the file that gets it wrong."
        ),
        distinguished_from=(
            "MISSING_GUARD — use this class whenever the absent check is an "
            "authorization decision."
        ),
    ),
}

#: Excluded from v1, recorded so the omission is a decision rather than an oversight.
EXCLUDED_CLASSES: dict[str, str] = {
    "injection": (
        "Needs a fixture built around a query or command boundary. Realistic ones "
        "are large and the defect tends to be conspicuous. Revisit post-v1."
    ),
    "secret-exposure": (
        "Usually a one-line, highly conspicuous defect — near-100% recall for any "
        "reviewer, so it would inflate scores without discriminating between them. "
        "The pilot's saturation finding makes this concrete."
    ),
    "performance": (
        "Rarely has a crisp right answer, so the judge would be adjudicating "
        "opinion. DESIGN reports precision and recall, not taste."
    ),
    "style-and-naming": (
        "Not a defect. These are what distractors are made of."
    ),
    "type-coercion": (
        "Folded into BOUNDARY_ERROR or NULL_DEREFERENCE by consequence. As its own "
        "class it was not distinguishable from those two by a finding's text alone."
    ),
}


def describe(defect_class: DefectClass) -> ClassDefinition:
    return TAXONOMY[defect_class]


def all_classes() -> list[DefectClass]:
    return list(TAXONOMY)
