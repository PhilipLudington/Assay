"""What a run costs, in dollars.

One table, because two numbers have to agree: the spend printed after a
measurement run, and the spend a sweep projection multiplies out. The Phase 0
pilot kept both in one file and they agreed by construction; what this module
removes is the risk that they stop agreeing once `pilot/` is deleted and each
caller starts estimating for itself.

An unknown model raises rather than defaulting. A missing price that quietly
became zero would make a budget look met.
"""

from __future__ import annotations

#: USD per million tokens, `(input, output)`. Cache writes bill at 1.25x input
#: and cache reads at 0.1x, so both are derived rather than listed.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

#: The Batch API's discount. Not applied by `cost_usd` — a recorded run is
#: billed at whatever rate it actually ran at, and a projection that wants the
#: batch price applies this itself and says so.
BATCH_DISCOUNT = 0.5


class UnknownModelError(KeyError):
    """No price on file. Raised rather than guessed."""


def price_for(model: str) -> tuple[float, float]:
    """Per-million-token `(input, output)` price for `model`.

    Prefix match, so a dated snapshot of a known model prices correctly, but an
    unrecognised family raises instead of falling back to a neighbour's rate.
    """
    for known, prices in PRICING.items():
        if model.startswith(known):
            return prices
    raise UnknownModelError(
        f"no price on file for {model!r}; add it to PRICING rather than guessing, "
        "or every cost figure that quotes it is fiction"
    )


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Dollar cost of one call at list price."""
    per_in, per_out = price_for(model)
    return (
        input_tokens * per_in
        + cache_creation_tokens * per_in * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * per_in * CACHE_READ_MULTIPLIER
        + output_tokens * per_out
    ) / 1_000_000
