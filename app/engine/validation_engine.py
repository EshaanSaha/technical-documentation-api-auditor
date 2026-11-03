"""Main validation pipeline and completeness scoring engine (Section 5).

Combines:
* Deterministic & candidate endpoint matching
* Rule-based + fuzzy parameter validation
* Structural request/response schema & status-code comparison
* Semantic description similarity analysis (local MiniLM embeddings)
* Global and per-endpoint authentication consistency checks

Produces a complete, self-contained :class:`ValidationResult` with deterministic
issue IDs, side-by-side comparison rows, and a transparent weighted completeness
score breakdown.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from app.core.config import ValidationThresholds
from app.core.models import (
    CATEGORY_PREFIX,
    SEVERITY_ORDER,
    ApiModel,
    ComparisonRow,
    Issue,
    IssueCategory,
    MatchStatus,
    ScoreComponent,
    Severity,
    ValidationResult,
)
from app.engine.alignment import ElementStats
from app.engine.description_validator import validate_descriptions
from app.engine.endpoint_matcher import PairedEndpoint, match_endpoints
from app.engine.parameter_validator import validate_endpoint_parameters
from app.engine.schema_validator import validate_endpoint_schemas


def _validate_authentication(
    spec_model: ApiModel,
    doc_model: ApiModel,
    paired: list[PairedEndpoint],
) -> tuple[list[Issue], ElementStats]:
    """Compare global and endpoint-level authentication requirements."""
    issues: list[Issue] = []
    stats = ElementStats()

    spec_global = set(spec_model.global_security or spec_model.auth_methods)
    doc_global = set(doc_model.global_security or doc_model.auth_methods)

    if spec_global:
        stats.total += 1
        if not doc_global:
            stats.missing += 1
            issues.append(
                Issue(
                    endpoint="(global)",
                    method="ALL",
                    category=IssueCategory.AUTHENTICATION,
                    issue_type="Missing authentication documentation",
                    severity=Severity.HIGH,
                    expected=", ".join(sorted(spec_global)),
                    actual="No authentication mechanism documented",
                    evidence="OpenAPI components.securitySchemes / global security",
                    explanation=(
                        f"The OpenAPI specification requires {', '.join(sorted(spec_global))} authentication, "
                        "but no authentication section or scheme was detected in the documentation."
                    ),
                    suggestion=f"Add an Authentication section documenting the {', '.join(sorted(spec_global))} scheme.",
                )
            )
        elif not (spec_global & doc_global):
            stats.partial += 1
            issues.append(
                Issue(
                    endpoint="(global)",
                    method="ALL",
                    category=IssueCategory.AUTHENTICATION,
                    issue_type="Mismatched authentication scheme",
                    severity=Severity.HIGH,
                    expected=", ".join(sorted(spec_global)),
                    actual=", ".join(sorted(doc_global)),
                    evidence="Documentation Authentication section",
                    explanation=(
                        f"The specification defines {', '.join(sorted(spec_global))} authentication, "
                        f"whereas the documentation describes {', '.join(sorted(doc_global))}."
                    ),
                    suggestion=f"Update the documented authentication scheme to {', '.join(sorted(spec_global))}.",
                )
            )
        else:
            stats.correct += 1

    # Per-endpoint security overrides
    for pair in paired:
        s_ep = pair.spec
        d_ep = pair.doc
        effective_spec = s_ep.security if s_ep.security is not None else list(spec_global)
        effective_doc = d_ep.security  # None = inherits global doc auth, [] = explicitly documented as public

        if effective_doc is None:
            continue

        stats.total += 1
        if effective_spec and effective_doc == []:
            stats.partial += 1
            issues.append(
                Issue(
                    endpoint=s_ep.path,
                    method=s_ep.method,
                    category=IssueCategory.AUTHENTICATION,
                    issue_type="Endpoint authentication mismatch",
                    severity=Severity.HIGH,
                    expected=f"Requires {', '.join(effective_spec)} authentication",
                    actual="Documented as public (no authentication required)",
                    evidence=d_ep.source_location or "endpoint documentation section",
                    explanation=(
                        f"Operation '{s_ep.method} {s_ep.path}' requires {', '.join(effective_spec)} authentication "
                        "in the OpenAPI specification, but the documentation states that no authentication is required."
                    ),
                    suggestion=(
                        f"Either remove the 'public / no authentication' statement from '{s_ep.method} {s_ep.path}' "
                        "in the documentation, or add 'security: []' to the operation in the OpenAPI specification."
                    ),
                )
            )
        elif not effective_spec and effective_doc:
            stats.partial += 1
            issues.append(
                Issue(
                    endpoint=s_ep.path,
                    method=s_ep.method,
                    category=IssueCategory.AUTHENTICATION,
                    issue_type="Endpoint authentication mismatch",
                    severity=Severity.MEDIUM,
                    expected="Public endpoint (security: [])",
                    actual=f"Documented as requiring {', '.join(effective_doc)}",
                    evidence=d_ep.source_location or "endpoint documentation section",
                    explanation=(
                        f"Operation '{s_ep.method} {s_ep.path}' is marked public in the specification, "
                        f"but the documentation requires {', '.join(effective_doc)} authentication."
                    ),
                    suggestion="Align the endpoint security requirement between documentation and specification.",
                )
            )
        else:
            stats.correct += 1

    return issues, stats


def _assign_issue_ids(issues: list[Issue]) -> list[Issue]:
    """Sort issues by severity then category/endpoint and assign deterministic IDs."""
    sorted_issues = sorted(
        issues,
        key=lambda item: (
            SEVERITY_ORDER.get(item.severity.value, 99),
            item.category.value,
            item.endpoint,
            item.method,
            item.issue_type,
        ),
    )
    counters: Counter[IssueCategory] = Counter()
    for item in sorted_issues:
        counters[item.category] += 1
        prefix = CATEGORY_PREFIX.get(item.category, "ISS")
        item.issue_id = f"{prefix}-{counters[item.category]:03d}"
    return sorted_issues


def _compute_completeness_score(
    spec_total: int,
    exact_matches: int,
    likely_matches: int,
    unexpected_endpoints: int,
    param_stats: ElementStats,
    schema_stats: ElementStats,
    status_stats: ElementStats,
    desc_stats: ElementStats,
    auth_stats: ElementStats,
) -> tuple[float, list[ScoreComponent]]:
    """Transparent weighted completeness score on a 0..100 scale.

    Methodology:
    * Endpoint Coverage & Accuracy (weight 0.30):
      ``(exact + 0.5 * likely) / max(1, spec_total + unexpected)``
    * Parameter Accuracy (weight 0.25):
      ``(correct + 0.5 * partial) / (total + extra)``
    * Request & Response Schema Accuracy (weight 0.25):
      ``(correct + 0.5 * partial) / (total + extra)``
    * Status Code & Authentication Accuracy (weight 0.10):
      ``(correct + 0.5 * partial) / (total + extra)``
    * Description Consistency (weight 0.10):
      ``(correct + 0.5 * partial) / total``

    If a dimension has 0 applicable items in both spec and docs, its weight is
    redistributed proportionally across active dimensions.
    """
    ep_denom = max(1, spec_total + unexpected_endpoints)
    ep_score = (exact_matches + 0.5 * likely_matches) / ep_denom if spec_total or unexpected_endpoints else 1.0

    combined_status_auth = ElementStats()
    combined_status_auth.add(status_stats)
    combined_status_auth.add(auth_stats)

    raw_components: list[tuple[str, float, Optional[float], str]] = [
        (
            "Endpoint Coverage & Accuracy",
            0.30,
            ep_score,
            f"{exact_matches} exact, {likely_matches} likely of {spec_total} spec endpoints ({unexpected_endpoints} unexpected)",
        ),
        (
            "Parameter Accuracy",
            0.25,
            param_stats.accuracy(),
            f"{param_stats.correct} exact, {param_stats.partial} mismatched, {param_stats.missing} missing, {param_stats.extra} extra",
        ),
        (
            "Request & Response Schemas",
            0.25,
            schema_stats.accuracy(),
            f"{schema_stats.correct} exact, {schema_stats.partial} mismatched, {schema_stats.missing} missing, {schema_stats.extra} extra",
        ),
        (
            "Status Codes & Authentication",
            0.10,
            combined_status_auth.accuracy(),
            f"{combined_status_auth.correct} exact, {combined_status_auth.partial} mismatched, {combined_status_auth.missing} missing",
        ),
        (
            "Description Consistency",
            0.10,
            desc_stats.accuracy(),
            f"{desc_stats.correct} consistent, {desc_stats.partial} inconsistent, {desc_stats.missing} missing",
        ),
    ]

    active_weight = sum(w for _, w, s, _ in raw_components if s is not None) or 1.0
    breakdown: list[ScoreComponent] = []
    weighted_sum = 0.0

    for name, weight, score_val, detail in raw_components:
        if score_val is None:
            breakdown.append(ScoreComponent(name=name, weight=0.0, score=1.0, detail="Not applicable (0 items)"))
            continue
        norm_weight = round(weight / active_weight, 4)
        clamped = max(0.0, min(1.0, score_val))
        weighted_sum += norm_weight * clamped
        breakdown.append(ScoreComponent(name=name, weight=norm_weight, score=round(clamped, 4), detail=detail))

    return round(weighted_sum * 100.0, 1), breakdown


def run_validation(
    spec_model: ApiModel,
    doc_model: ApiModel,
    thresholds: Optional[ValidationThresholds] = None,
    session_name: str = "",
) -> ValidationResult:
    """Execute the full validation pipeline comparing ``doc_model`` against ``spec_model``."""
    thresholds = thresholds or ValidationThresholds()
    warnings: list[str] = list(spec_model.warnings) + list(doc_model.warnings)
    all_issues: list[Issue] = []
    all_comparisons: list[ComparisonRow] = []

    # 1. Endpoint matching
    ep_out = match_endpoints(
        spec_model.endpoints,
        doc_model.endpoints,
        spec_base_path=spec_model.base_path,
        thresholds=thresholds,
    )
    all_issues.extend(ep_out.issues)

    # 2. Parameter & 3. Schema validation on every paired endpoint (EXACT and LIKELY)
    total_param_stats = ElementStats()
    total_schema_stats = ElementStats()
    total_status_stats = ElementStats()

    for pair in ep_out.paired:
        p_out = validate_endpoint_parameters(pair.spec, pair.doc, thresholds=thresholds)
        all_issues.extend(p_out.issues)
        all_comparisons.extend(p_out.comparisons)
        total_param_stats.add(p_out.stats)

        s_out = validate_endpoint_schemas(pair.spec, pair.doc, thresholds=thresholds)
        all_issues.extend(s_out.issues)
        all_comparisons.extend(s_out.comparisons)
        total_schema_stats.add(s_out.request_stats)
        total_schema_stats.add(s_out.response_stats)
        total_status_stats.add(s_out.status_stats)

    # 4. Description consistency analysis
    desc_out = validate_descriptions(ep_out.paired, thresholds=thresholds)
    all_issues.extend(desc_out.issues)
    if desc_out.warning:
        warnings.append(desc_out.warning)

    # 5. Authentication consistency
    auth_issues, auth_stats = _validate_authentication(spec_model, doc_model, ep_out.paired)
    all_issues.extend(auth_issues)

    # 6. Assign deterministic issue IDs
    sorted_issues = _assign_issue_ids(all_issues)

    # 7. Calculate summary counts and completeness score from actual findings
    exact_count = sum(1 for m in ep_out.matches if m.status == MatchStatus.EXACT)
    likely_count = sum(1 for m in ep_out.matches if m.status == MatchStatus.LIKELY)
    missing_count = sum(1 for m in ep_out.matches if m.status == MatchStatus.MISSING)
    unexpected_count = sum(1 for m in ep_out.matches if m.status == MatchStatus.UNEXPECTED)

    cat_counts = Counter(i.category for i in sorted_issues)
    sev_counts = Counter(i.severity for i in sorted_issues)

    completeness_score, breakdown = _compute_completeness_score(
        spec_total=len(spec_model.endpoints),
        exact_matches=exact_count,
        likely_matches=likely_count,
        unexpected_endpoints=unexpected_count,
        param_stats=total_param_stats,
        schema_stats=total_schema_stats,
        status_stats=total_status_stats,
        desc_stats=desc_out.stats,
        auth_stats=auth_stats,
    )

    summary = {
        "total_spec_endpoints": len(spec_model.endpoints),
        "total_doc_endpoints": len(doc_model.endpoints),
        "matched_endpoints": exact_count + likely_count,
        "exact_matched_endpoints": exact_count,
        "likely_matched_endpoints": likely_count,
        "missing_endpoints": missing_count,
        "unexpected_endpoints": unexpected_count,
        "total_issues": len(sorted_issues),
        "parameter_mismatches": cat_counts.get(IssueCategory.PARAMETER, 0),
        "schema_inconsistencies": (
            cat_counts.get(IssueCategory.REQUEST_SCHEMA, 0)
            + cat_counts.get(IssueCategory.RESPONSE_SCHEMA, 0)
            + cat_counts.get(IssueCategory.STATUS_CODE, 0)
        ),
        "request_schema_issues": cat_counts.get(IssueCategory.REQUEST_SCHEMA, 0),
        "response_schema_issues": cat_counts.get(IssueCategory.RESPONSE_SCHEMA, 0),
        "status_code_issues": cat_counts.get(IssueCategory.STATUS_CODE, 0),
        "description_inconsistencies": cat_counts.get(IssueCategory.DESCRIPTION, 0),
        "authentication_issues": cat_counts.get(IssueCategory.AUTHENTICATION, 0),
        "endpoint_issues": cat_counts.get(IssueCategory.ENDPOINT, 0),
        "severity_counts": {s.value: sev_counts.get(s, 0) for s in Severity},
        "category_counts": {c.value: cat_counts.get(c, 0) for c in IssueCategory},
    }

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return ValidationResult(
        session_name=session_name or f"{spec_model.title or spec_model.source_name} Audit",
        created_at=created_at,
        documentation_file=doc_model.source_name,
        specification_file=spec_model.source_name,
        api_title=spec_model.title or doc_model.title,
        api_version=spec_model.version or doc_model.version,
        summary=summary,
        completeness_score=completeness_score,
        score_breakdown=breakdown,
        matches=ep_out.matches,
        issues=sorted_issues,
        comparisons=all_comparisons,
        descriptions=desc_out.comparisons,
        entities=doc_model.entities[:250],
        warnings=warnings,
        thresholds=thresholds.to_dict(),
        semantic_model_available=desc_out.model_available,
    )

