"""Shared OCR pilot metrics: token overlap, fuzzy title hit, bootstrap CI."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import numpy as np


def title_overlap_score(ocr_text: str, title: str) -> float:
    """Normalized token overlap of catalog title tokens found in OCR text."""

    def toks(s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 1}

    tt = toks(title)
    if not tt:
        return 0.0
    ot = toks(ocr_text)
    return round(len(tt & ot) / len(tt), 4)


def normalize_alnum(s: str) -> str:
    """Strip non-alphanumeric (handles Florence-style glued tokens / spacing)."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def title_fuzzy_score(ocr_text: str, title: str) -> float:
    """SequenceMatcher ratio on alnum-normalized title vs full OCR string."""
    a = normalize_alnum(title)
    b = normalize_alnum(ocr_text)
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 4)


def title_hit(ocr_text: str, title: str, fuzzy_threshold: float = 0.72) -> bool:
    """True if normalized title appears in OCR, or fuzzy score ≥ threshold."""
    a = normalize_alnum(title)
    b = normalize_alnum(ocr_text)
    if not a or not b:
        return False
    if a in b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= fuzzy_threshold


def bootstrap_mean_ci(
    values,
    n_resamples: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Return (mean, ci_low, ci_high) for the mean via percentile bootstrap."""
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    mean = float(arr.mean())
    if arr.size == 1:
        return (mean, mean, mean)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_resamples, arr.size))
    boots = arr[idx].mean(axis=1)
    lo = float(np.quantile(boots, alpha / 2))
    hi = float(np.quantile(boots, 1 - alpha / 2))
    return (mean, lo, hi)
