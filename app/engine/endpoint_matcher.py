"""Endpoint matching engine.

Compares endpoints extracted from documentation against OpenAPI specification
operations in two passes:

1. **Deterministic pass**: exact match on HTTP method + normalized path template
   (after stripping any server base path). If the static path segments match
   exactly (Confidence = 1.0), it is classified as ``EXACT``.
   Note: if path parameter names differ (e.g. ``{id}`` vs ``{customer_id}``),
   the endpoint still pairs structurally so downstream parameter validation can
   flag the parameter name mismatch explicitly.
2. **Candidate pass**: remaining unmatched endpoints are compared using a
   weighted combination of:
   - Normalized path template similarity (RapidFuzz + segment alignment)
   - Version-stripped path template similarity (catches outdated ``/v1/...`` prefixes)
   - HTTP method agreement
   - Semantic similarity of summaries/descriptions (local MiniLM embeddings)

   Candidates above ``thresholds.endpoint_likely_match`` are classified as
   ``LIKELY`` (never silently accepted as exact!) and generate a High/Medium
   issue explaining why they were paired and what differs.
3. Unmatched specification endpoints become ``MISSING`` (Critical issue).
   Unmatched documented endpoints become ``UNEXPECTED`` (Medium issue).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.config import ValidationThresholds
from app.core.models import (
    EndpointMatch,
    EndpointSpec,
    Issue,
    IssueCategory,
    MatchStatus,
    Severity,
)
from app.nlp.semantic_matching import (
    SemanticModelUnavailable,
    get_semantic_matcher,
    path_similarity,
)
from app.nlp.text_normalization import (
    canonical_path,
    path_template,
    split_version,
    strip_base_path,
)


@dataclass
class PairedEndpoint:
    spec: EndpointSpec
    doc: EndpointSpec
    match: EndpointMatch


@dataclass
class EndpointMatchingOutput:
    matches: list[EndpointMatch] = field(default_factory=list)
    paired: list[PairedEndpoint] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def _effective_doc_path(doc_path: str, spec_base_path: str) -> str:
    return strip_base_path(doc_path, spec_base_path)


def _describe_difference(spec: EndpointSpec, doc: EndpointSpec, spec_base_path: str) -> tuple[str, str]:
    """Return a clear explanation and issue type for a likely (approximate) match."""
    eff_doc = _effective_doc_path(doc.path, spec_base_path)
    spec_ver, spec_rest = split_version(spec.path)
    doc_ver, doc_rest = split_version(eff_doc)
    reasons: list[str] = []
    issue_type = "Endpoint path mismatch"

    if spec.method != doc.method:
        reasons.append(f"HTTP method differs (spec: {spec.method}, documented: {doc.method})")
        issue_type = "HTTP method mismatch"
    if (spec_ver != doc_ver) and path_template(spec_rest) == path_template(doc_rest):
        if doc_ver and not spec_ver:
            reasons.append(
                f"Documentation includes version prefix '/{doc_ver}' in '{doc.path}' "
                f"(possibly outdated reference; specification path is '{spec.path}')"
            )
        elif spec_ver and doc_ver:
            reasons.append(
                f"Version prefix differs: specification uses '/{spec_ver}' ('{spec.path}'), "
                f"documentation uses '/{doc_ver}' ('{doc.path}')"
            )
        else:
            reasons.append(
                f"Documentation omits version prefix '/{spec_ver}' present in specification '{spec.path}'"
            )
        issue_type = "Outdated or mismatched endpoint version"
    elif canonical_path(spec.path) != canonical_path(eff_doc):
        reasons.append(f"Path differs: specification defines '{spec.path}', documentation has '{doc.path}'")

    return ("; ".join(reasons) if reasons else "Approximate endpoint match."), issue_type


def match_endpoints(
    spec_endpoints: list[EndpointSpec],
    doc_endpoints: list[EndpointSpec],
    spec_base_path: str = "",
    thresholds: Optional[ValidationThresholds] = None,
) -> EndpointMatchingOutput:
    thresholds = thresholds or ValidationThresholds()
    output = EndpointMatchingOutput()

    remaining_spec: list[EndpointSpec] = list(spec_endpoints)
    remaining_doc: list[EndpointSpec] = list(doc_endpoints)

    # ------------------------------------------------------------------ #
    # Pass 1: Deterministic exact matching on (method, path_template)
    # ------------------------------------------------------------------ #
    doc_by_key: dict[tuple[str, str], list[EndpointSpec]] = {}
    for d in remaining_doc:
        eff_path = _effective_doc_path(d.path, spec_base_path)
        key = (d.method, path_template(eff_path))
        doc_by_key.setdefault(key, []).append(d)

    still_unmatched_spec: list[EndpointSpec] = []
    for s in remaining_spec:
        key = (s.method, s.normalized_path)
        bucket = doc_by_key.get(key)
        if bucket:
            d = bucket.pop(0)
            remaining_doc.remove(d)
            eff_doc = _effective_doc_path(d.path, spec_base_path)
            exact_text = canonical_path(s.path) == canonical_path(eff_doc)
            note = (
                "Exact HTTP method and canonical path match."
                if exact_text
                else (
                    f"Exact structural match on '{s.method} {s.normalized_path}' "
                    f"(documented as '{d.path}'; path parameter or casing differences are checked in parameter validation)."
                )
            )
            em = EndpointMatch(
                status=MatchStatus.EXACT,
                spec_method=s.method,
                spec_path=s.path,
                doc_method=d.method,
                doc_path=d.path,
                confidence=1.0,
                explanation=note,
                score_components={"path": 1.0, "method": 1.0},
                doc_location=d.source_location,
            )
            output.matches.append(em)
            output.paired.append(PairedEndpoint(spec=s, doc=d, match=em))
        else:
            still_unmatched_spec.append(s)

    remaining_spec = still_unmatched_spec

    # ------------------------------------------------------------------ #
    # Pass 2: Candidate matching (RapidFuzz + version stripping + semantic)
    # ------------------------------------------------------------------ #
    semantic_scores: dict[tuple[int, int], float] = {}
    if remaining_spec and remaining_doc:
        matcher = get_semantic_matcher()
        pair_indices: list[tuple[int, int]] = []
        pair_texts: list[tuple[str, str]] = []
        for si, s in enumerate(remaining_spec):
            s_text = s.full_description or f"{s.method} {s.path}"
            for di, d in enumerate(remaining_doc):
                d_text = d.full_description or f"{d.method} {d.path}"
                pair_indices.append((si, di))
                pair_texts.append((s_text, d_text))
        try:
            sims = matcher.similarity_pairs(pair_texts)
            for idx, sim in zip(pair_indices, sims):
                semantic_scores[idx] = sim
        except SemanticModelUnavailable:
            semantic_scores = {}

    candidates: list[tuple[float, int, int, dict[str, float]]] = []
    for si, s in enumerate(remaining_spec):
        s_tpl = path_template(s.path, strip_version=False)
        s_tpl_nover = path_template(s.path, strip_version=True)
        for di, d in enumerate(remaining_doc):
            eff_doc = _effective_doc_path(d.path, spec_base_path)
            d_tpl = path_template(eff_doc, strip_version=False)
            d_tpl_nover = path_template(eff_doc, strip_version=True)

            raw_path_sim = path_similarity(s_tpl, d_tpl)
            nover_path_sim = path_similarity(s_tpl_nover, d_tpl_nover)
            # If stripping a version prefix makes the path identical, treat path similarity as high (0.92)
            best_path_sim = max(raw_path_sim, 0.92 * nover_path_sim)
            method_sim = 1.0 if s.method == d.method else 0.0
            sem_sim = semantic_scores.get((si, di), 0.0)

            if (si, di) in semantic_scores:
                combined = 0.55 * best_path_sim + 0.25 * method_sim + 0.20 * sem_sim
            else:
                combined = 0.70 * best_path_sim + 0.30 * method_sim

            # Guard against pairing two unrelated endpoints just because they share GET + description words
            if best_path_sim < 0.50:
                continue

            if combined >= thresholds.endpoint_likely_match:
                comp = {
                    "path_similarity": round(best_path_sim, 3),
                    "method_match": round(method_sim, 3),
                    "semantic_similarity": round(sem_sim, 3),
                }
                candidates.append((round(combined, 3), si, di, comp))

    candidates.sort(key=lambda item: -item[0])
    used_spec: set[int] = set()
    used_doc: set[int] = set()

    for score, si, di, comp in candidates:
        if si in used_spec or di in used_doc:
            continue
        used_spec.add(si)
        used_doc.add(di)
        s = remaining_spec[si]
        d = remaining_doc[di]
        reason_text, issue_type = _describe_difference(s, d, spec_base_path)
        explanation = (
            f"{reason_text}. Candidate match score {score:.2f} "
            f"(path={comp['path_similarity']:.2f}, method={comp['method_match']:.0f}, "
            f"description={comp['semantic_similarity']:.2f})."
        )
        em = EndpointMatch(
            status=MatchStatus.LIKELY,
            spec_method=s.method,
            spec_path=s.path,
            doc_method=d.method,
            doc_path=d.path,
            confidence=score,
            explanation=explanation,
            score_components=comp,
            doc_location=d.source_location,
        )
        output.matches.append(em)
        output.paired.append(PairedEndpoint(spec=s, doc=d, match=em))
        output.issues.append(
            Issue(
                endpoint=s.path,
                method=s.method,
                category=IssueCategory.ENDPOINT,
                issue_type=issue_type,
                severity=Severity.HIGH,
                expected=f"{s.method} {s.path}",
                actual=f"{d.method} {d.path}",
                evidence=f"Documented at {d.source_location or 'documentation'}: '{d.method} {d.path}'",
                explanation=explanation,
                suggestion=f"Update the documentation endpoint reference from '{d.method} {d.path}' to '{s.method} {s.path}'.",
                confidence=score,
            )
        )

    # ------------------------------------------------------------------ #
    # Pass 3: Unmatched specification endpoints -> MISSING
    # ------------------------------------------------------------------ #
    for si, s in enumerate(remaining_spec):
        if si in used_spec:
            continue
        em = EndpointMatch(
            status=MatchStatus.MISSING,
            spec_method=s.method,
            spec_path=s.path,
            confidence=0.0,
            explanation=f"Operation '{s.method} {s.path}' is defined in the OpenAPI specification but missing from the documentation.",
        )
        output.matches.append(em)
        output.issues.append(
            Issue(
                endpoint=s.path,
                method=s.method,
                category=IssueCategory.ENDPOINT,
                issue_type="Undocumented endpoint",
                severity=Severity.CRITICAL,
                expected=f"{s.method} {s.path} ({s.summary or 'defined in specification'})",
                actual="Not documented",
                evidence=f"OpenAPI {s.source_location}",
                explanation=f"The endpoint '{s.method} {s.path}' exists in the OpenAPI specification but no matching section was found in the uploaded documentation.",
                suggestion=f"Add a documentation section for '{s.method} {s.path}' describing its purpose, parameters, request/response schemas and status codes.",
            )
        )

    # ------------------------------------------------------------------ #
    # Pass 4: Unmatched documented endpoints -> UNEXPECTED
    # ------------------------------------------------------------------ #
    for di, d in enumerate(remaining_doc):
        if di in used_doc:
            continue
        em = EndpointMatch(
            status=MatchStatus.UNEXPECTED,
            doc_method=d.method,
            doc_path=d.path,
            confidence=0.0,
            explanation=f"Documented endpoint '{d.method} {d.path}' does not correspond to any operation in the OpenAPI specification.",
            doc_location=d.source_location,
        )
        output.matches.append(em)
        output.issues.append(
            Issue(
                endpoint=d.path,
                method=d.method,
                category=IssueCategory.ENDPOINT,
                issue_type="Unexpected documented endpoint",
                severity=Severity.MEDIUM,
                expected="Not present in OpenAPI specification",
                actual=f"{d.method} {d.path}",
                evidence=f"Documented at {d.source_location or 'documentation'}: '{d.method} {d.path}'",
                explanation=f"The documentation describes '{d.method} {d.path}', which is absent from the OpenAPI specification (it may be deprecated, removed, or missing from the spec).",
                suggestion=f"Remove '{d.method} {d.path}' from the documentation if it has been retired, or add its definition to the OpenAPI specification.",
            )
        )

    return output

