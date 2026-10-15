"""Bayesian updating primitives (pure functions, no state).

Beliefs update in odds space: posterior odds = prior odds x Bayes factor. The
Bayes factor B = P(E|H) / P(E|not H) summarizes how strongly a piece of evidence
E favors a hypothesis H over its negation. Working in odds keeps multi-experiment
updating associative — applying two Bayes factors in sequence equals applying
their product — and avoids the pitfalls of nudging a probability directly.
"""

from __future__ import annotations

# Keep probabilities strictly inside (0, 1): a credence of exactly 0 or 1 can
# never be moved by any finite amount of evidence, which is rarely intended.
EPS = 1e-9


def clamp_prob(p: float) -> float:
    return min(1.0 - EPS, max(EPS, float(p)))


def prob_to_odds(p: float) -> float:
    p = clamp_prob(p)
    return p / (1.0 - p)


def odds_to_prob(odds: float) -> float:
    if odds < 0:
        raise ValueError("odds must be non-negative")
    return odds / (1.0 + odds)


def bayes_factor_from_likelihoods(p_e_given_h: float, p_e_given_not_h: float) -> float:
    """B = P(E|H) / P(E|not H). Both likelihoods must be in [0, 1]."""
    for name, val in (("p_e_given_h", p_e_given_h), ("p_e_given_not_h", p_e_given_not_h)):
        if not 0.0 <= val <= 1.0:
            raise ValueError(f"{name} must be in [0, 1], got {val}")
    if p_e_given_not_h <= 0.0:
        raise ValueError("p_e_given_not_h must be > 0 (evidence otherwise decisive)")
    return p_e_given_h / p_e_given_not_h


def update_probability(prior: float, bayes_factor: float) -> float:
    """Return the posterior credence after applying a Bayes factor to a prior.

    ``bayes_factor`` > 1 raises the credence, < 1 lowers it, == 1 leaves it
    unchanged (evidence uninformative).
    """
    if bayes_factor <= 0:
        raise ValueError("bayes_factor must be > 0")
    posterior_odds = prob_to_odds(prior) * bayes_factor
    return odds_to_prob(posterior_odds)
