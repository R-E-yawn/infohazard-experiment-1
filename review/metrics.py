"""Statistics, standard library only.

Everything here is closed-form or a seeded bootstrap.  No numpy, no scipy, no
statsmodels -- the app has to run on a laptop with nothing installed, and a
reviewer who cannot reproduce a number by hand should not be asked to sign off
on it.

Verified against known values in _selftest.py:
  * Wilson 0/20 -> [0.0%, 16.1%]            (the figure quoted in SPEC 7.3)
  * Cohen's kappa [[20,5],[10,15]] -> 0.400 (textbook)
  * Fisher 2x2 [[1,9],[11,3]] -> p = 0.0028 (textbook)
  * kappa falls with prevalence at fixed raw agreement; AC1 does not
    (the reason SPEC 8.6 demands all three be printed)
"""

from __future__ import annotations

import math
import random
from fractions import Fraction

Z95 = 1.959963984540054
Z90 = 1.6448536269514722


# ---------------------------------------------------------------------------
# Proportions
# ---------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval.  Valid at the 2% base rates this study lives at,
    where a Wald interval returns negative lower bounds (SPEC 7.3)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_prop(k: int, n: int, z: float = Z95) -> str:
    """`4/20 = 20.0%, 95% CI [8.1%, 41.6%]`.  Never prints a bare 0%."""
    if n <= 0:
        return f"{k}/0 = n/a"
    lo, hi = wilson(k, n, z)
    return f"{k}/{n} = {100.0 * k / n:.1f}%, 95% CI [{100 * lo:.1f}%, {100 * hi:.1f}%]"


def risk_difference(k1: int, n1: int, k2: int, n2: int,
                    z: float = Z95) -> tuple[float, float, float]:
    """(difference, lo, hi) using the Newcombe hybrid-score interval: the
    Wilson bounds of each arm combined.  Behaves at zero counts, where a
    normal-approximation difference interval does not."""
    if n1 <= 0 or n2 <= 0:
        return (0.0, -1.0, 1.0)
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    delta = p1 - p2
    lo = delta - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = delta + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (delta, max(-1.0, lo), min(1.0, hi))


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]].

    Exact rational arithmetic, so the sum-of-smaller-probabilities comparison
    has no floating-point tie-breaking problem.  The chi-square
    approximation is not safe at these expected counts (SPEC 7.3)."""
    n = a + b + c + d
    if n == 0:
        return 1.0
    row1, col1, col2 = a + b, a + c, b + d
    denom = math.comb(n, row1)
    if denom == 0:
        return 1.0

    def prob(k: int) -> Fraction:
        return Fraction(math.comb(col1, k) * math.comb(col2, row1 - k), denom)

    lo = max(0, row1 - col2)
    hi = min(row1, col1)
    observed = prob(a)
    total = sum((prob(k) for k in range(lo, hi + 1) if prob(k) <= observed),
                Fraction(0))
    return min(1.0, float(total))


def holm_bonferroni(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-adjusted p-values, monotone-enforced.  Applied across the
    pre-registered P1-P3 only (SPEC 7.3); P4 is descriptive."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (key, p) in enumerate(items):
        val = min(1.0, (m - i) * p)
        running = max(running, val)
        adjusted[key] = running
    return adjusted


def tost_equivalence(k1: int, n1: int, k2: int, n2: int,
                     margin: float = 0.10) -> dict:
    """Two one-sided tests on the risk difference.

    Equivalence is declared only when the 90% CI lies entirely inside +/-margin
    (SPEC 7.3).  Anything else is reported as INCONCLUSIVE (UNDERPOWERED), never
    as a null -- the distinction between 'we showed it does not matter' and
    'we could not tell' is the whole point."""
    delta, lo, hi = risk_difference(k1, n1, k2, n2, z=Z90)
    if n1 <= 0 or n2 <= 0:
        verdict = "NO DATA"
    elif lo > -margin and hi < margin:
        verdict = "EQUIVALENT"
    else:
        p = fisher_exact_2x2(k1, n1 - k1, k2, n2 - k2)
        verdict = "DIFFERENT" if p < 0.05 else "INCONCLUSIVE (UNDERPOWERED)"
    return {"delta": delta, "lo90": lo, "hi90": hi, "margin": margin,
            "verdict": verdict}


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------


def confusion(pairs: list[tuple[str, str]], categories: list[str]) -> list[list[int]]:
    """rows = first rater (auto), cols = second rater (human)."""
    idx = {c: i for i, c in enumerate(categories)}
    m = [[0] * len(categories) for _ in categories]
    for a, h in pairs:
        if a in idx and h in idx:
            m[idx[a]][idx[h]] += 1
    return m


def raw_agreement(pairs: list[tuple[str, str]]) -> tuple[int, int]:
    n = len(pairs)
    return sum(1 for a, h in pairs if a == h), n


def cohen_kappa(pairs: list[tuple[str, str]], categories: list[str]) -> dict:
    """Cohen's kappa with the Fleiss-Cohen-Everitt (1969) asymptotic SE.

    Returned alongside a seeded bootstrap interval; if the two disagree
    materially, distrust both and say so rather than printing one."""
    n = len(pairs)
    if n == 0:
        return {"kappa": None, "n": 0, "po": None, "pe": None,
                "se": None, "lo": None, "hi": None}
    m = confusion(pairs, categories)
    q = len(categories)
    p = [[m[i][j] / n for j in range(q)] for i in range(q)]
    row = [sum(p[i]) for i in range(q)]
    col = [sum(p[i][j] for i in range(q)) for j in range(q)]
    po = sum(p[i][i] for i in range(q))
    pe = sum(row[i] * col[i] for i in range(q))
    if abs(1.0 - pe) < 1e-12:
        # Both raters used one category for everything: kappa is undefined.
        return {"kappa": None, "n": n, "po": po, "pe": pe, "se": None,
                "lo": None, "hi": None,
                "note": "kappa undefined: expected agreement is 1.0 "
                        "(both raters used a single category)"}
    kappa = (po - pe) / (1.0 - pe)

    term_a = sum(p[i][i] * (1.0 - (row[i] + col[i]) * (1.0 - po)) ** 2
                 for i in range(q))
    term_b = (1.0 - po) ** 2 * sum(
        p[i][j] * (col[i] + row[j]) ** 2
        for i in range(q) for j in range(q) if i != j)
    term_c = (po * pe - 2.0 * pe + po) ** 2
    var = (term_a + term_b - term_c) / (n * (1.0 - pe) ** 2)
    se = math.sqrt(var) if var > 0 else 0.0
    # Kappa is bounded by 1; the asymptotic interval is not, and at these n it
    # routinely runs past it.  Clamp rather than print an impossible number,
    # and let the caller say the bound was clamped.
    hi_raw = kappa + Z95 * se
    return {"kappa": kappa, "n": n, "po": po, "pe": pe, "se": se,
            "lo": max(-1.0, kappa - Z95 * se), "hi": min(1.0, hi_raw),
            "hi_clamped": hi_raw > 1.0}


def gwet_ac1(pairs: list[tuple[str, str]], categories: list[str]) -> dict:
    """Gwet's AC1.

    Chance agreement is  (1/(q-1)) * sum_k pi_k (1 - pi_k)  with
    pi_k the mean marginal for category k.  Unlike kappa it does not collapse
    toward zero as prevalence becomes lopsided, which is exactly the regime
    this study sits in -- hence SPEC 8.6 requiring it next to kappa."""
    n = len(pairs)
    q = len(categories)
    if n == 0 or q < 2:
        return {"ac1": None, "n": n, "pa": None, "pe": None}
    m = confusion(pairs, categories)
    p = [[m[i][j] / n for j in range(q)] for i in range(q)]
    row = [sum(p[i]) for i in range(q)]
    col = [sum(p[i][j] for i in range(q)) for j in range(q)]
    pa = sum(p[i][i] for i in range(q))
    pi = [(row[k] + col[k]) / 2.0 for k in range(q)]
    pe = sum(pk * (1.0 - pk) for pk in pi) / (q - 1)
    if abs(1.0 - pe) < 1e-12:
        return {"ac1": None, "n": n, "pa": pa, "pe": pe,
                "note": "AC1 undefined: chance agreement is 1.0"}
    return {"ac1": (pa - pe) / (1.0 - pe), "n": n, "pa": pa, "pe": pe}


def bootstrap_ci(pairs: list[tuple[str, str]], categories: list[str],
                 statistic: str = "kappa", iters: int = 4000,
                 seed: int = 20260101, alpha: float = 0.05) -> dict:
    """Seeded nonparametric percentile bootstrap over episodes.

    Reported next to the analytic interval as a cross-check: the analytic
    kappa SE is a long formula and a transcription error in it would be
    invisible, whereas the bootstrap only uses the point estimate."""
    n = len(pairs)
    if n < 3:
        return {"lo": None, "hi": None, "iters": 0, "seed": seed,
                "note": "too few episodes to bootstrap"}
    rng = random.Random(seed)
    fn = cohen_kappa if statistic == "kappa" else gwet_ac1
    key = "kappa" if statistic == "kappa" else "ac1"
    vals: list[float] = []
    undefined = 0
    for _ in range(iters):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        val = fn(sample, categories).get(key)
        if val is None:
            undefined += 1
        else:
            vals.append(val)
    if not vals:
        return {"lo": None, "hi": None, "iters": iters, "seed": seed,
                "note": "statistic undefined in every resample"}
    vals.sort()

    def pct(fr: float) -> float:
        pos = fr * (len(vals) - 1)
        lo_i = int(math.floor(pos))
        hi_i = min(len(vals) - 1, lo_i + 1)
        frac = pos - lo_i
        return vals[lo_i] * (1 - frac) + vals[hi_i] * frac

    return {"lo": pct(alpha / 2), "hi": pct(1 - alpha / 2),
            "iters": iters, "seed": seed, "undefined_resamples": undefined}


def sens_spec(pairs: list[tuple[bool, bool]]) -> dict:
    """Grader sensitivity and specificity, human verdict as truth.

    `pairs` are (auto_positive, human_positive)."""
    tp = sum(1 for a, h in pairs if a and h)
    fp = sum(1 for a, h in pairs if a and not h)
    fn = sum(1 for a, h in pairs if not a and h)
    tn = sum(1 for a, h in pairs if not a and not h)
    out = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": len(pairs)}
    pos, neg = tp + fn, tn + fp
    out["sensitivity"] = (tp / pos) if pos else None
    out["sensitivity_ci"] = wilson(tp, pos) if pos else None
    out["specificity"] = (tn / neg) if neg else None
    out["specificity_ci"] = wilson(tn, neg) if neg else None
    out["ppv"] = (tp / (tp + fp)) if (tp + fp) else None
    out["ppv_ci"] = wilson(tp, tp + fp) if (tp + fp) else None
    out["npv"] = (tn / (tn + fn)) if (tn + fn) else None
    return out


def equivalence_operating_characteristics(p: float, n1: int, n2: int,
                                          margin: float = 0.10) -> dict:
    """Exact operating characteristics of the TOST equivalence test when the
    two conditions are TRULY IDENTICAL at rate `p`.

    Enumerated over every (k1, k2) with its binomial weight -- no simulation,
    so the number is reproducible to the last digit.  This is what lets
    results.md say "the equivalence test is inconclusive X% of the time even
    when there is no difference" with X computed for the actual design rather
    than quoted."""
    def binom(n, k, pp):
        return math.comb(n, k) * (pp ** k) * ((1 - pp) ** (n - k))

    out = {"EQUIVALENT": 0.0, "DIFFERENT": 0.0,
           "INCONCLUSIVE (UNDERPOWERED)": 0.0, "NO DATA": 0.0}
    for k1 in range(n1 + 1):
        w1 = binom(n1, k1, p)
        if w1 == 0.0:
            continue
        for k2 in range(n2 + 1):
            w2 = binom(n2, k2, p)
            if w2 == 0.0:
                continue
            verdict = tost_equivalence(k1, n1, k2, n2, margin)["verdict"]
            out[verdict] = out.get(verdict, 0.0) + w1 * w2
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()} | {
        "p": p, "n1": n1, "n2": n2, "margin": margin}


def prevalence(pairs: list[tuple[str, str]], positive: set[str]) -> float | None:
    """Mean marginal prevalence of `positive` across the two raters -- printed
    next to kappa because kappa is only interpretable alongside it."""
    if not pairs:
        return None
    hits = sum(1 for a, h in pairs if a in positive) + \
        sum(1 for a, h in pairs if h in positive)
    return hits / (2 * len(pairs))
