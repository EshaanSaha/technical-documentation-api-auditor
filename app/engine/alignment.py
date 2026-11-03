"""Alignment of named elements (parameters, schema fields) between spec and docs.

Alignment is staged from strict to lenient so that every pairing can be
explained:

1. ``exact``      - identical original names.
2. ``normalized`` - identical after normalization (``customerId`` == ``customer_id``).
3. ``fuzzy``      - RapidFuzz similarity above a threshold, restricted to
                    elements in the same scope (e.g. same parent object).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, Hashable, Optional, TypeVar

from app.nlp.semantic_matching import name_similarity

T = TypeVar("T")


@dataclass
class AlignedPair(Generic[T]):
    spec: T
    doc: T
    kind: str  # exact | normalized | fuzzy
    score: float  # 0..100


@dataclass
class Alignment(Generic[T]):
    pairs: list[AlignedPair[T]] = field(default_factory=list)
    missing: list[T] = field(default_factory=list)  # in spec, not in docs
    extra: list[T] = field(default_factory=list)  # in docs, not in spec


def align_named(
    spec_items: list[T],
    doc_items: list[T],
    original: Callable[[T], str],
    normalized: Callable[[T], str],
    scope: Callable[[T], Hashable] = lambda _: None,
    leaf: Optional[Callable[[T], str]] = None,
    fuzzy_threshold: float = 80.0,
) -> Alignment[T]:
    leaf = leaf or original
    result: Alignment[T] = Alignment()
    remaining_spec = list(spec_items)
    remaining_doc = list(doc_items)

    for key_fn, kind in ((original, "exact"), (normalized, "normalized")):
        doc_index: dict[str, T] = {}
        for d in remaining_doc:
            doc_index.setdefault(key_fn(d), d)
        still_spec = []
        for s in remaining_spec:
            d = doc_index.pop(key_fn(s), None)
            if d is not None:
                result.pairs.append(AlignedPair(s, d, kind, 100.0))
                remaining_doc.remove(d)
            else:
                still_spec.append(s)
        remaining_spec = still_spec

    # Fuzzy stage: greedy assignment of the best-scoring candidates first.
    candidates = []
    for s in remaining_spec:
        for d in remaining_doc:
            if scope(s) != scope(d):
                continue
            score = name_similarity(leaf(s), leaf(d))
            if score >= fuzzy_threshold:
                candidates.append((score, id(s), id(d), s, d))
    candidates.sort(key=lambda c: -c[0])
    used_spec: set[int] = set()
    used_doc: set[int] = set()
    for score, sid, did, s, d in candidates:
        if sid in used_spec or did in used_doc:
            continue
        used_spec.add(sid)
        used_doc.add(did)
        result.pairs.append(AlignedPair(s, d, "fuzzy", round(score, 1)))

    result.missing = [s for s in remaining_spec if id(s) not in used_spec]
    result.extra = [d for d in remaining_doc if id(d) not in used_doc]
    return result


@dataclass
class ElementStats:
    """Counts used by the completeness score."""

    total: int = 0  # elements defined in the specification
    correct: int = 0
    partial: int = 0  # documented but with at least one discrepancy
    missing: int = 0
    extra: int = 0  # documented elements that do not exist in the specification

    def add(self, other: "ElementStats") -> None:
        self.total += other.total
        self.correct += other.correct
        self.partial += other.partial
        self.missing += other.missing
        self.extra += other.extra

    def accuracy(self) -> Optional[float]:
        denominator = self.total + self.extra
        if denominator == 0:
            return None
        return (self.correct + 0.5 * self.partial) / denominator


def fmt_required(value: Optional[bool]) -> str:
    return "" if value is None else ("required" if value else "optional")


def types_compatible(expected: Optional[str], documented: Optional[str], documented_from_example: bool) -> bool:
    """Whether two canonical types agree. Example values of 5 are valid for ``number`` fields."""
    if not expected or not documented or expected == documented:
        return True
    if documented_from_example and expected == "number" and documented == "integer":
        return True
    return False

