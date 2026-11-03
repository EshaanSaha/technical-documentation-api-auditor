"""Description consistency analysis (Module F).

Compares endpoint and parameter descriptions between the OpenAPI specification
and the documentation using the local ``sentence-transformers/all-MiniLM-L6-v2``
model.

Important design principles:
* Comparisons are strictly contextual (only between a paired endpoint or an
  aligned parameter on that endpoint — never across unrelated document sections).
* Similarity scores are treated as heuristic signals, not proof of correctness.
* Every comparison records the exact specification text and documentation text
  side by side so engineers can inspect the evidence directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.config import ValidationThresholds
from app.core.models import (
    DescriptionComparison,
    EndpointSpec,
    Issue,
    IssueCategory,
    Severity,
)
from app.engine.alignment import ElementStats, align_named
from app.engine.endpoint_matcher import PairedEndpoint
from app.nlp.semantic_matching import (
    SemanticModelUnavailable,
    get_semantic_matcher,
)


@dataclass
class DescriptionValidationOutput:
    comparisons: list[DescriptionComparison] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    stats: ElementStats = field(default_factory=ElementStats)
    model_available: bool = True
    warning: Optional[str] = None


@dataclass
class _PendingPair:
    endpoint: str
    method: str
    element: str
    spec_text: str
    doc_text: str
    doc_location: str


def _classify_band(score: float, thresholds: ValidationThresholds) -> str:
    if score >= thresholds.description_high:
        return "High similarity"
    if score >= thresholds.description_moderate:
        return "Moderate similarity"
    if score >= thresholds.description_unrelated:
        return "Potential inconsistency"
    return "Unrelated"


def validate_descriptions(
    paired_endpoints: list[PairedEndpoint],
    thresholds: Optional[ValidationThresholds] = None,
) -> DescriptionValidationOutput:
    thresholds = thresholds or ValidationThresholds()
    out = DescriptionValidationOutput()
    pending: list[_PendingPair] = []

    for pair in paired_endpoints:
        spec_ep: EndpointSpec = pair.spec
        doc_ep: EndpointSpec = pair.doc

        spec_desc = (spec_ep.description or spec_ep.summary).strip()
        doc_desc = doc_ep.description.strip()

        if spec_desc:
            out.stats.total += 1
            if not doc_desc:
                out.stats.missing += 1
                out.comparisons.append(
                    DescriptionComparison(
                        endpoint=spec_ep.path,
                        method=spec_ep.method,
                        element="endpoint",
                        spec_text=spec_desc,
                        doc_text="",
                        similarity=None,
                        band="Missing",
                    )
                )
                out.issues.append(
                    Issue(
                        endpoint=spec_ep.path,
                        method=spec_ep.method,
                        category=IssueCategory.DESCRIPTION,
                        issue_type="Missing endpoint description",
                        severity=Severity.MEDIUM,
                        expected=spec_desc,
                        actual="No descriptive text in documentation section",
                        evidence=doc_ep.source_location or "documentation section",
                        explanation=(
                            f"The OpenAPI specification provides a description for '{spec_ep.method} {spec_ep.path}', "
                            "but the documentation section contains no prose description."
                        ),
                        suggestion=f"Add a description for '{spec_ep.method} {spec_ep.path}': \"{spec_desc}\"",
                    )
                )
            else:
                pending.append(
                    _PendingPair(
                        endpoint=spec_ep.path,
                        method=spec_ep.method,
                        element="endpoint",
                        spec_text=spec_desc,
                        doc_text=doc_desc,
                        doc_location=doc_ep.source_location,
                    )
                )

        # Contextual parameter description comparisons
        param_align = align_named(
            spec_ep.parameters,
            doc_ep.parameters,
            original=lambda p: p.name,
            normalized=lambda p: p.normalized_name,
            fuzzy_threshold=thresholds.name_fuzzy_match,
        )
        for p_pair in param_align.pairs:
            sp_desc = p_pair.spec.description.strip()
            dp_desc = p_pair.doc.description.strip()
            if not sp_desc or not dp_desc:
                continue
            out.stats.total += 1
            pending.append(
                _PendingPair(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    element=f"parameter '{p_pair.spec.name}'",
                    spec_text=sp_desc,
                    doc_text=dp_desc,
                    doc_location=p_pair.doc.evidence or doc_ep.source_location,
                )
            )

    if not pending:
        return out

    matcher = get_semantic_matcher()
    try:
        scores = matcher.similarity_pairs([(p.spec_text, p.doc_text) for p in pending])
    except SemanticModelUnavailable as exc:
        out.model_available = False
        out.warning = str(exc)
        for item in pending:
            out.comparisons.append(
                DescriptionComparison(
                    endpoint=item.endpoint,
                    method=item.method,
                    element=item.element,
                    spec_text=item.spec_text,
                    doc_text=item.doc_text,
                    similarity=None,
                    band="Model unavailable",
                )
            )
        return out

    for item, raw_score in zip(pending, scores):
        score = round(float(raw_score), 3)
        band = _classify_band(score, thresholds)
        out.comparisons.append(
            DescriptionComparison(
                endpoint=item.endpoint,
                method=item.method,
                element=item.element,
                spec_text=item.spec_text,
                doc_text=item.doc_text,
                similarity=score,
                band=band,
            )
        )
        if band == "High similarity":
            out.stats.correct += 1
        elif band == "Moderate similarity":
            out.stats.correct += 1
        else:
            out.stats.partial += 1
            sev = Severity.HIGH if (band == "Unrelated" or item.element == "endpoint") else Severity.MEDIUM
            out.issues.append(
                Issue(
                    endpoint=item.endpoint,
                    method=item.method,
                    category=IssueCategory.DESCRIPTION,
                    issue_type=f"Description inconsistency ({item.element})",
                    severity=sev,
                    expected=item.spec_text,
                    actual=item.doc_text,
                    evidence=(
                        f"{item.doc_location or 'documentation'} | Cosine similarity: {score:.2f} "
                        f"(threshold: {thresholds.description_moderate:.2f})"
                    ),
                    explanation=(
                        f"The documented description for {item.element} on '{item.method} {item.endpoint}' has low "
                        f"semantic similarity ({score:.2f}, classified as '{band}') compared with the OpenAPI "
                        "specification, indicating potentially contradictory or outdated behaviour documentation."
                    ),
                    suggestion=(
                        f"Review and align the documented description with the specification: \"{item.spec_text}\""
                    ),
                    confidence=score,
                )
            )

    return out

