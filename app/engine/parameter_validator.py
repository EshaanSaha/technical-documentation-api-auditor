"""Parameter validation module (Module D).

Compares documented path, query, header and cookie parameters against the
OpenAPI specification for a paired endpoint.

Detects:
1. Parameters present in the specification but missing in documentation.
2. Parameters documented but absent from the specification.
3. Incorrect parameter names (caught via fuzzy/normalized alignment).
4. Incorrect data types.
5. Required versus optional mismatches.
6. Incorrect parameter locations (query vs path vs header).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.config import ValidationThresholds
from app.core.models import (
    ComparisonRow,
    EndpointSpec,
    Issue,
    IssueCategory,
    Parameter,
    Severity,
)
from app.engine.alignment import (
    ElementStats,
    align_named,
    fmt_required,
    types_compatible,
)


@dataclass
class ParameterValidationOutput:
    issues: list[Issue] = field(default_factory=list)
    comparisons: list[ComparisonRow] = field(default_factory=list)
    stats: ElementStats = field(default_factory=ElementStats)


def validate_endpoint_parameters(
    spec_ep: EndpointSpec,
    doc_ep: EndpointSpec,
    thresholds: Optional[ValidationThresholds] = None,
) -> ParameterValidationOutput:
    thresholds = thresholds or ValidationThresholds()
    out = ParameterValidationOutput()
    out.stats.total = len(spec_ep.parameters)

    # First align without restricting location so we can detect location mismatches
    alignment = align_named(
        spec_ep.parameters,
        doc_ep.parameters,
        original=lambda p: p.name,
        normalized=lambda p: p.normalized_name,
        scope=lambda _: None,
        fuzzy_threshold=thresholds.name_fuzzy_match,
    )

    for pair in alignment.pairs:
        sp: Parameter = pair.spec
        dp: Parameter = pair.doc
        has_discrepancy = False

        # 3. Parameter naming mismatch (exact normalized match with different surface form vs fuzzy match)
        if pair.kind == "fuzzy" or (pair.kind == "normalized" and sp.name != dp.name):
            has_discrepancy = True
            sev = Severity.HIGH if pair.kind == "fuzzy" else Severity.LOW
            out.issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=IssueCategory.PARAMETER,
                    issue_type="Incorrect parameter name",
                    severity=sev,
                    expected=sp.name,
                    actual=dp.name,
                    evidence=dp.evidence or f"Documented parameter '{dp.name}'",
                    explanation=(
                        f"Parameter '{sp.name}' in the specification is documented as '{dp.name}' "
                        f"({'normalized identifier match' if pair.kind == 'normalized' else f'fuzzy similarity {pair.score:.0f}%'})."
                    ),
                    suggestion=f"Rename documented parameter '{dp.name}' to '{sp.name}' to match the specification.",
                    confidence=round(pair.score / 100.0, 2),
                )
            )

        # 4. Data type mismatch
        if sp.type and dp.type and not types_compatible(sp.type, dp.type, False):
            has_discrepancy = True
            out.issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=IssueCategory.PARAMETER,
                    issue_type="Incorrect parameter type",
                    severity=Severity.HIGH,
                    expected=f"{sp.type}" + (f" [{sp.raw_type}]" if sp.raw_type and sp.raw_type != sp.type else ""),
                    actual=f"{dp.type}" + (f" [{dp.raw_type}]" if dp.raw_type and dp.raw_type != dp.type else ""),
                    evidence=dp.evidence or f"Parameter '{dp.name}'",
                    explanation=(
                        f"Parameter '{sp.name}' has type '{sp.type}' in the OpenAPI specification, "
                        f"but the documentation states '{dp.raw_type or dp.type}'."
                    ),
                    suggestion=f"Update the documented type of '{sp.name}' to '{sp.raw_type or sp.type}'.",
                )
            )

        # 5. Required vs optional mismatch
        if sp.required is not None and dp.required is not None and sp.required != dp.required:
            has_discrepancy = True
            out.issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=IssueCategory.PARAMETER,
                    issue_type="Required/optional mismatch",
                    severity=Severity.MEDIUM,
                    expected=fmt_required(sp.required),
                    actual=fmt_required(dp.required),
                    evidence=dp.evidence or f"Parameter '{dp.name}'",
                    explanation=(
                        f"Parameter '{sp.name}' is {fmt_required(sp.required)} in the OpenAPI specification, "
                        f"but documented as {fmt_required(dp.required)}."
                    ),
                    suggestion=f"Mark parameter '{sp.name}' as {fmt_required(sp.required)} in the documentation.",
                )
            )

        # 6. Parameter location mismatch (query vs path vs header)
        if sp.location and dp.location and sp.location != dp.location:
            has_discrepancy = True
            out.issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=IssueCategory.PARAMETER,
                    issue_type="Incorrect parameter location",
                    severity=Severity.HIGH,
                    expected=sp.location,
                    actual=dp.location,
                    evidence=dp.evidence or f"Parameter '{dp.name}'",
                    explanation=(
                        f"Parameter '{sp.name}' is passed in '{sp.location}' according to the specification, "
                        f"but the documentation places it in '{dp.location}'."
                    ),
                    suggestion=f"Update the documentation for '{sp.name}' to specify location '{sp.location}'.",
                )
            )

        if has_discrepancy:
            out.stats.partial += 1
        else:
            out.stats.correct += 1

        out.comparisons.append(
            ComparisonRow(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                scope="parameter",
                name=sp.name,
                documented_name=dp.name,
                expected_type=sp.type or "",
                documented_type=dp.type or "",
                expected_required=fmt_required(sp.required),
                documented_required=fmt_required(dp.required),
                expected_location=sp.location or "",
                documented_location=dp.location or "",
                status="Mismatch" if has_discrepancy else "OK",
            )
        )

    # 1. Missing parameters (in spec, absent from documentation)
    for sp in alignment.missing:
        out.stats.missing += 1
        sev = Severity.HIGH if sp.required else Severity.MEDIUM
        out.issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=IssueCategory.PARAMETER,
                issue_type="Missing parameter in documentation",
                severity=sev,
                expected=f"{sp.name} ({sp.location or 'param'}, {sp.type or 'any'}, {fmt_required(sp.required)})",
                actual="Not documented",
                evidence=sp.evidence,
                explanation=(
                    f"The {fmt_required(sp.required)} {sp.location or ''} parameter '{sp.name}' is defined in the "
                    f"specification for '{spec_ep.method} {spec_ep.path}' but is missing from the documentation."
                ),
                suggestion=f"Document parameter '{sp.name}' (in: {sp.location}, type: {sp.type}, {fmt_required(sp.required)}).",
            )
        )
        out.comparisons.append(
            ComparisonRow(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                scope="parameter",
                name=sp.name,
                expected_type=sp.type or "",
                expected_required=fmt_required(sp.required),
                expected_location=sp.location or "",
                status="Missing in documentation",
            )
        )

    # 2. Extra parameters (in documentation, absent from spec)
    for dp in alignment.extra:
        out.stats.extra += 1
        out.issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=IssueCategory.PARAMETER,
                issue_type="Undocumented parameter in specification",
                severity=Severity.MEDIUM,
                expected="Not present in specification",
                actual=f"{dp.name} ({dp.location or 'param'}, {dp.type or 'unspecified'})",
                evidence=dp.evidence,
                explanation=(
                    f"The documentation lists parameter '{dp.name}' on '{spec_ep.method} {spec_ep.path}', "
                    "which does not exist in the OpenAPI specification."
                ),
                suggestion=f"Remove '{dp.name}' from the documentation or add it to the OpenAPI specification.",
            )
        )
        out.comparisons.append(
            ComparisonRow(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                scope="parameter",
                name=dp.name,
                documented_name=dp.name,
                documented_type=dp.type or "",
                documented_required=fmt_required(dp.required),
                documented_location=dp.location or "",
                status="Not in specification",
            )
        )

    return out

