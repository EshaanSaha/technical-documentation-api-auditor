"""Request and response schema & status-code validator (Module E).

Compares:
1. Request body root structure and fields (nested paths supported via dotted
   notation such as ``shipping_address.postal_code`` and ``items[].quantity``).
2. Response status codes (missing documented success/error codes, unexpected
   status codes, or mismatched success code such as 200 vs 201).
3. Response body structures and fields for matched or corresponding success
   responses.
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
    ResponseSpec,
    SchemaField,
    Severity,
)
from app.engine.alignment import (
    ElementStats,
    align_named,
    fmt_required,
    types_compatible,
)


@dataclass
class SchemaValidationOutput:
    issues: list[Issue] = field(default_factory=list)
    comparisons: list[ComparisonRow] = field(default_factory=list)
    request_stats: ElementStats = field(default_factory=ElementStats)
    response_stats: ElementStats = field(default_factory=ElementStats)
    status_stats: ElementStats = field(default_factory=ElementStats)


def _parent_scope(field_obj: SchemaField) -> str:
    """Return normalized parent path so nested fields only fuzzy-match siblings."""
    if "." not in field_obj.normalized_path:
        return ""
    return field_obj.normalized_path.rsplit(".", 1)[0]


def _is_from_example(field_obj: SchemaField) -> bool:
    return (field_obj.raw_type or "").startswith("example:")


def _all_from_example(fields: list[SchemaField]) -> bool:
    return bool(fields) and all(_is_from_example(f) for f in fields)


def _compare_field_lists(
    spec_ep: EndpointSpec,
    spec_fields: list[SchemaField],
    doc_fields: list[SchemaField],
    category: IssueCategory,
    scope_label: str,
    thresholds: ValidationThresholds,
) -> tuple[list[Issue], list[ComparisonRow], ElementStats]:
    issues: list[Issue] = []
    rows: list[ComparisonRow] = []
    stats = ElementStats(total=len(spec_fields))

    if not spec_fields and not doc_fields:
        return issues, rows, stats

    doc_only_examples = _all_from_example(doc_fields)
    is_request = category == IssueCategory.REQUEST_SCHEMA
    noun = "request field" if is_request else "response attribute"

    alignment = align_named(
        spec_fields,
        doc_fields,
        original=lambda f: f.path,
        normalized=lambda f: f.normalized_path,
        scope=_parent_scope,
        leaf=lambda f: f.name,
        fuzzy_threshold=thresholds.name_fuzzy_match,
    )

    for pair in alignment.pairs:
        sf: SchemaField = pair.spec
        df: SchemaField = pair.doc
        from_example = _is_from_example(df)
        has_discrepancy = False

        # Field naming mismatch (fuzzy match, or camelCase vs snake_case in explicit table)
        if pair.kind == "fuzzy" or (pair.kind == "normalized" and sf.path != df.path):
            has_discrepancy = True
            sev = Severity.HIGH if pair.kind == "fuzzy" else Severity.LOW
            issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=category,
                    issue_type=f"Incorrect {noun} name",
                    severity=sev,
                    expected=sf.path,
                    actual=df.path,
                    evidence=df.evidence or f"Documented field '{df.path}'",
                    explanation=(
                        f"The {scope_label} defines '{sf.path}', whereas the documentation uses '{df.path}' "
                        f"({'naming convention difference' if pair.kind == 'normalized' else f'fuzzy similarity {pair.score:.0f}%'})."
                    ),
                    suggestion=f"Update the documented field name from '{df.path}' to '{sf.path}'.",
                    confidence=round(pair.score / 100.0, 2),
                )
            )

        # Data type mismatch
        if sf.type and df.type and not types_compatible(sf.type, df.type, from_example):
            has_discrepancy = True
            issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=category,
                    issue_type=f"Incorrect {noun} data type",
                    severity=Severity.HIGH,
                    expected=f"{sf.type}" + (f" [{sf.raw_type}]" if sf.raw_type and sf.raw_type != sf.type else ""),
                    actual=f"{df.type}" + (f" [{df.raw_type}]" if df.raw_type and df.raw_type != df.type else ""),
                    evidence=df.evidence or f"Field '{df.path}'",
                    explanation=(
                        f"Field '{sf.path}' in {scope_label} has type '{sf.type}' in the specification, "
                        f"but is documented as '{df.raw_type or df.type}'."
                    ),
                    suggestion=f"Change the documented type of '{sf.path}' to '{sf.raw_type or sf.type}'.",
                )
            )

        # Required vs optional mismatch (only when documentation explicitly states requiredness)
        if sf.required is not None and df.required is not None and sf.required != df.required:
            has_discrepancy = True
            issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=category,
                    issue_type="Required field mismatch",
                    severity=Severity.MEDIUM,
                    expected=fmt_required(sf.required),
                    actual=fmt_required(df.required),
                    evidence=df.evidence or f"Field '{df.path}'",
                    explanation=(
                        f"Field '{sf.path}' in {scope_label} is {fmt_required(sf.required)} in the specification, "
                        f"but documented as {fmt_required(df.required)}."
                    ),
                    suggestion=f"Mark '{sf.path}' as {fmt_required(sf.required)} in the documentation.",
                )
            )

        if has_discrepancy:
            stats.partial += 1
        else:
            stats.correct += 1

        rows.append(
            ComparisonRow(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                scope=scope_label,
                name=sf.path,
                documented_name=df.path,
                expected_type=sf.type or "",
                documented_type=df.type or "",
                expected_required=fmt_required(sf.required),
                documented_required=fmt_required(df.required),
                status="Mismatch" if has_discrepancy else "OK",
            )
        )

    # Missing fields (present in spec, absent in documentation)
    matched_spec_paths = {p.spec.normalized_path for p in alignment.pairs}
    for sf in alignment.missing:
        # If a parent object/array is already missing and has no children in docs, avoid cascading duplicate noise
        parent = _parent_scope(sf)
        parent_base = parent[:-2] if parent.endswith("[]") else parent
        if parent_base and parent_base not in matched_spec_paths and not any(
            d.normalized_path.startswith(parent + ".") for d in doc_fields
        ):
            stats.missing += 1
            continue

        # When the documentation only provides a JSON example, optional fields omitted from the sample
        # are not treated as documentation errors.
        if doc_only_examples and not sf.required:
            stats.correct += 1
            continue

        stats.missing += 1
        sev = Severity.HIGH if (is_request and sf.required) else Severity.MEDIUM
        issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=category,
                issue_type=f"Missing {noun}",
                severity=sev,
                expected=f"{sf.path} ({sf.type or 'any'}, {fmt_required(sf.required)})",
                actual="Not documented",
                evidence=sf.evidence,
                explanation=(
                    f"The {fmt_required(sf.required)} {noun} '{sf.path}' (type '{sf.type}') is defined in the "
                    f"OpenAPI {scope_label} for '{spec_ep.method} {spec_ep.path}' but is missing from the documentation."
                ),
                suggestion=f"Add '{sf.path}' (type: {sf.type}, {fmt_required(sf.required)}) to the documented {scope_label}.",
            )
        )
        rows.append(
            ComparisonRow(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                scope=scope_label,
                name=sf.path,
                expected_type=sf.type or "",
                expected_required=fmt_required(sf.required),
                status="Missing in documentation",
            )
        )

    # Extra fields (documented, absent from spec)
    for df in alignment.extra:
        stats.extra += 1
        issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=category,
                issue_type=f"Unexpected {noun}",
                severity=Severity.MEDIUM,
                expected="Not present in specification schema",
                actual=f"{df.path} ({df.type or 'unspecified'})",
                evidence=df.evidence,
                explanation=(
                    f"The documentation includes '{df.path}' in the {scope_label} of "
                    f"'{spec_ep.method} {spec_ep.path}', which is not defined in the OpenAPI schema."
                ),
                suggestion=f"Remove '{df.path}' from the documented {scope_label} or add it to the OpenAPI schema.",
            )
        )
        rows.append(
            ComparisonRow(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                scope=scope_label,
                name=df.path,
                documented_name=df.path,
                documented_type=df.type or "",
                documented_required=fmt_required(df.required),
                status="Not in specification",
            )
        )

    return issues, rows, stats


def _is_success_code(code: str) -> bool:
    return code.startswith("2")


def validate_endpoint_schemas(
    spec_ep: EndpointSpec,
    doc_ep: EndpointSpec,
    thresholds: Optional[ValidationThresholds] = None,
) -> SchemaValidationOutput:
    thresholds = thresholds or ValidationThresholds()
    out = SchemaValidationOutput()

    # ------------------------------------------------------------------ #
    # 1. Request body comparison
    # ------------------------------------------------------------------ #
    if spec_ep.request_root_type and doc_ep.request_root_type and spec_ep.request_root_type != doc_ep.request_root_type:
        out.issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=IssueCategory.REQUEST_SCHEMA,
                issue_type="Incorrect request body structure",
                severity=Severity.HIGH,
                expected=spec_ep.request_root_type,
                actual=doc_ep.request_root_type,
                evidence=f"Documented at {doc_ep.source_location}",
                explanation=(
                    f"Request body root type is '{spec_ep.request_root_type}' in the specification "
                    f"but '{doc_ep.request_root_type}' in the documentation."
                ),
                suggestion=f"Update the request body structure in documentation to '{spec_ep.request_root_type}'.",
            )
        )

    if spec_ep.request_fields and not doc_ep.request_fields:
        req_count = sum(1 for f in spec_ep.request_fields if f.required)
        out.request_stats.total = len(spec_ep.request_fields)
        out.request_stats.missing = len(spec_ep.request_fields)
        sev = Severity.HIGH if req_count > 0 else Severity.MEDIUM
        out.issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=IssueCategory.REQUEST_SCHEMA,
                issue_type="Missing request body documentation",
                severity=sev,
                expected=f"Request body with {len(spec_ep.request_fields)} field(s)",
                actual="No request body documented",
                evidence=spec_ep.source_location,
                explanation=(
                    f"'{spec_ep.method} {spec_ep.path}' accepts a request body in the OpenAPI specification, "
                    "but no request fields or payload examples were found in the documentation."
                ),
                suggestion="Document the request body fields and provide an example JSON payload.",
            )
        )
    else:
        req_issues, req_rows, req_stats = _compare_field_lists(
            spec_ep,
            spec_ep.request_fields,
            doc_ep.request_fields,
            IssueCategory.REQUEST_SCHEMA,
            "request body",
            thresholds,
        )
        out.issues.extend(req_issues)
        out.comparisons.extend(req_rows)
        out.request_stats.add(req_stats)

    # ------------------------------------------------------------------ #
    # 2. Status codes & response schema comparison
    # ------------------------------------------------------------------ #
    spec_resps = {r.status_code: r for r in spec_ep.responses}
    doc_resps = {r.status_code: r for r in doc_ep.responses if r.status_code != "2XX"}
    generic_doc_2xx = next((r for r in doc_ep.responses if r.status_code == "2XX"), None)

    spec_success = [r for r in spec_ep.responses if _is_success_code(r.status_code)]
    doc_success = [r for r in doc_ep.responses if _is_success_code(r.status_code) and r.status_code != "2XX"]

    out.status_stats.total = len(spec_resps)

    # Check if primary 2xx success status code differs (e.g. spec=201, doc=200)
    paired_responses: list[tuple[ResponseSpec, ResponseSpec]] = []
    handled_spec_codes: set[str] = set()
    handled_doc_codes: set[str] = set()

    for code, sr in spec_resps.items():
        if code in doc_resps:
            out.status_stats.correct += 1
            handled_spec_codes.add(code)
            handled_doc_codes.add(code)
            paired_responses.append((sr, doc_resps[code]))

    # If the spec's 2xx code wasn't matched directly, check if the doc used a different 2xx code or generic 2XX
    unmatched_spec_success = [r for r in spec_success if r.status_code not in handled_spec_codes]
    unmatched_doc_success = [r for r in doc_success if r.status_code not in handled_doc_codes]

    if unmatched_spec_success and unmatched_doc_success:
        sr = unmatched_spec_success[0]
        dr = unmatched_doc_success[0]
        handled_spec_codes.add(sr.status_code)
        handled_doc_codes.add(dr.status_code)
        out.status_stats.partial += 1
        out.issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=IssueCategory.STATUS_CODE,
                issue_type="Inconsistent success status code",
                severity=Severity.HIGH,
                expected=sr.status_code,
                actual=dr.status_code,
                evidence=dr.evidence or f"Documented response {dr.status_code}",
                explanation=(
                    f"The OpenAPI specification defines success status code '{sr.status_code}' for "
                    f"'{spec_ep.method} {spec_ep.path}', whereas the documentation states '{dr.status_code}'."
                ),
                suggestion=f"Update the documented response status code from '{dr.status_code}' to '{sr.status_code}'.",
            )
        )
        paired_responses.append((sr, dr))
    elif unmatched_spec_success and generic_doc_2xx is not None:
        sr = unmatched_spec_success[0]
        handled_spec_codes.add(sr.status_code)
        out.status_stats.partial += 1
        paired_responses.append((sr, generic_doc_2xx))

    # Remaining unmatched spec status codes
    for code, sr in spec_resps.items():
        if code in handled_spec_codes:
            continue
        out.status_stats.missing += 1
        sev = Severity.MEDIUM if _is_success_code(code) else Severity.LOW
        out.issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=IssueCategory.STATUS_CODE,
                issue_type="Undocumented response status code",
                severity=sev,
                expected=f"{code} ({sr.description or 'response'})",
                actual="Not documented",
                evidence=sr.evidence,
                explanation=(
                    f"Status code '{code}' ({sr.description or 'defined in specification'}) for "
                    f"'{spec_ep.method} {spec_ep.path}' is not mentioned in the documentation."
                ),
                suggestion=f"Document the '{code}' response status code and when it is returned.",
            )
        )

    # Remaining unmatched documented status codes
    for code, dr in doc_resps.items():
        if code in handled_doc_codes:
            continue
        out.status_stats.extra += 1
        out.issues.append(
            Issue(
                endpoint=spec_ep.path,
                method=spec_ep.method,
                category=IssueCategory.STATUS_CODE,
                issue_type="Unexpected documented status code",
                severity=Severity.MEDIUM,
                expected="Not in specification responses",
                actual=code,
                evidence=dr.evidence,
                explanation=(
                    f"The documentation lists HTTP status '{code}' for '{spec_ep.method} {spec_ep.path}', "
                    "which is not declared in the OpenAPI specification."
                ),
                suggestion=f"Add status code '{code}' to the OpenAPI specification or remove it from the documentation.",
            )
        )

    # Compare response schemas for paired responses (focusing on 2xx responses or responses where doc provides fields)
    for sr, dr in paired_responses:
        if not _is_success_code(sr.status_code) and not dr.fields:
            continue
        if sr.root_type and dr.root_type and sr.root_type != dr.root_type:
            out.issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=IssueCategory.RESPONSE_SCHEMA,
                    issue_type="Incorrect response structure",
                    severity=Severity.HIGH,
                    expected=sr.root_type,
                    actual=dr.root_type,
                    evidence=dr.evidence,
                    explanation=(
                        f"Response {sr.status_code} root type is '{sr.root_type}' in the specification "
                        f"but '{dr.root_type}' in the documentation."
                    ),
                    suggestion=f"Update the documented response {sr.status_code} payload structure to '{sr.root_type}'.",
                )
            )
        if sr.fields and not dr.fields:
            # Doc mentioned the status code in prose ("Response 201 Created: returns the order") without a schema table/example
            out.response_stats.total += len(sr.fields)
            out.response_stats.missing += len(sr.fields)
            out.issues.append(
                Issue(
                    endpoint=spec_ep.path,
                    method=spec_ep.method,
                    category=IssueCategory.RESPONSE_SCHEMA,
                    issue_type="Missing response schema details",
                    severity=Severity.LOW,
                    expected=f"Response {sr.status_code} schema ({len(sr.fields)} fields)",
                    actual="Summary text only (no field table or JSON example)",
                    evidence=dr.evidence or doc_ep.source_location,
                    explanation=(
                        f"Response '{sr.status_code}' on '{spec_ep.method} {spec_ep.path}' defines {len(sr.fields)} "
                        "schema attributes in OpenAPI, but the documentation does not list the response fields or an example payload."
                    ),
                    suggestion=f"Include a response field table or JSON example for status '{sr.status_code}'.",
                )
            )
            continue

        resp_issues, resp_rows, resp_stats = _compare_field_lists(
            spec_ep,
            sr.fields,
            dr.fields,
            IssueCategory.RESPONSE_SCHEMA,
            f"response {sr.status_code}",
            thresholds,
        )
        out.issues.extend(resp_issues)
        out.comparisons.extend(resp_rows)
        out.response_stats.add(resp_stats)

    return out

