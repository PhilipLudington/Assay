"""Scoring: intervals, matching, and the judge.

Phase 4 owns this package. `interval` and `precision` land early because
Phase 1's K decision needs them, in the same way `review_floor` landed in
`assay.corpus.locality` — the alternative is two implementations of one
definition, and the whole project is a series of lessons about what that costs.

Nothing here is re-exported. `assay.eval.precision` reads a stored transcript
and imports `assay.corpus.locality` for the reviewer contract, which pulls in
the Anthropic SDK; code that only wants an interval should not pay for that.
"""
