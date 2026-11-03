"""Unit tests for endpoint matching, parameter validation, schema comparison and descriptions."""

from __future__ import annotations

from app.core.models import (
    EndpointSpec,
    MatchStatus,
    Parameter,
    ResponseSpec,
    SchemaField,
)
from app.engine.description_validator import validate_descriptions
from app.engine.endpoint_matcher import match_endpoints
from app.engine.parameter_validator import validate_endpoint_parameters
from app.engine.schema_validator import validate_endpoint_schemas


def test_endpoint_matcher_classifications() -> None:
    spec_eps = [
        EndpointSpec(method="GET", path="/customers", normalized_path="/customers", summary="List customers"),
        EndpointSpec(method="PATCH", path="/customers/{customer_id}", normalized_path="/customers/{}", summary="Update customer"),
        EndpointSpec(method="GET", path="/products/{product_id}", normalized_path="/products/{}", summary="Get product"),
    ]
    doc_eps = [
        EndpointSpec(method="GET", path="/customers", normalized_path="/customers", summary="List customers"),
        EndpointSpec(method="GET", path="/v1/products/{product_id}", normalized_path="/v1/products/{}", summary="Get product"),
        EndpointSpec(method="GET", path="/customers/{customer_id}/rewards", normalized_path="/customers/{}/rewards", summary="Rewards"),
    ]

    out = match_endpoints(spec_eps, doc_eps, spec_base_path="/v2")
    by_status = {m.status: m for m in out.matches}

    assert MatchStatus.EXACT in by_status
    assert by_status[MatchStatus.EXACT].spec_path == "/customers"

    assert MatchStatus.LIKELY in by_status
    assert by_status[MatchStatus.LIKELY].spec_path == "/products/{product_id}"
    assert by_status[MatchStatus.LIKELY].doc_path == "/v1/products/{product_id}"

    assert MatchStatus.MISSING in by_status
    assert by_status[MatchStatus.MISSING].spec_path == "/customers/{customer_id}"

    assert MatchStatus.UNEXPECTED in by_status
    assert by_status[MatchStatus.UNEXPECTED].doc_path == "/customers/{customer_id}/rewards"


def test_parameter_validator_discrepancies() -> None:
    spec_ep = EndpointSpec(
        method="GET",
        path="/orders",
        normalized_path="/orders",
        parameters=[
            Parameter(name="limit", normalized_name="limit", location="query", type="integer", required=False),
            Parameter(name="customer_id", normalized_name="customer_id", location="query", type="string", required=False),
            Parameter(name="include", normalized_name="include", location="query", type="string", required=True),
            Parameter(name="created_after", normalized_name="created_after", location="query", type="string", required=False),
        ],
    )
    doc_ep = EndpointSpec(
        method="GET",
        path="/orders",
        normalized_path="/orders",
        parameters=[
            Parameter(name="limit", normalized_name="limit", location="query", type="string", required=False),
            Parameter(name="customer", normalized_name="customer", location="query", type="string", required=False),
            Parameter(name="include", normalized_name="include", location="header", type="string", required=False),
            Parameter(name="legacy_flag", normalized_name="legacy_flag", location="query", type="boolean", required=False),
        ],
    )

    out = validate_endpoint_parameters(spec_ep, doc_ep)
    issue_types = {i.issue_type for i in out.issues}

    assert "Incorrect parameter type" in issue_types
    assert "Incorrect parameter name" in issue_types
    assert "Incorrect parameter location" in issue_types
    assert "Required/optional mismatch" in issue_types
    assert "Missing parameter in documentation" in issue_types
    assert "Undocumented parameter in specification" in issue_types


def test_schema_and_status_validator() -> None:
    spec_ep = EndpointSpec(
        method="POST",
        path="/orders",
        normalized_path="/orders",
        request_root_type="object",
        request_fields=[
            SchemaField(path="customer_id", normalized_path="customer_id", name="customer_id", type="string", required=True),
            SchemaField(path="currency", normalized_path="currency", name="currency", type="string", required=True),
        ],
        responses=[
            ResponseSpec(
                status_code="201",
                root_type="object",
                fields=[
                    SchemaField(path="id", normalized_path="id", name="id", type="string", required=True),
                    SchemaField(path="total_amount", normalized_path="total_amount", name="total_amount", type="number", required=True),
                ],
            )
        ],
    )
    doc_ep = EndpointSpec(
        method="POST",
        path="/orders",
        normalized_path="/orders",
        request_root_type="object",
        request_fields=[
            SchemaField(path="customer_id", normalized_path="customer_id", name="customer_id", type="string", required=True),
        ],
        responses=[
            ResponseSpec(
                status_code="200",
                root_type="object",
                fields=[
                    SchemaField(path="id", normalized_name="id", normalized_path="id", name="id", type="string", required=True),
                    SchemaField(path="total", normalized_path="total", name="total", type="number", required=True),
                ],
            )
        ],
    )

    out = validate_endpoint_schemas(spec_ep, doc_ep)
    issue_types = {i.issue_type for i in out.issues}

    assert "Missing request field" in issue_types
    assert "Inconsistent success status code" in issue_types
    assert "Incorrect response attribute name" in issue_types


def test_description_validator_bands_and_missing() -> None:
    spec_ok = EndpointSpec(
        method="GET",
        path="/customers",
        normalized_path="/customers",
        description="Returns a paginated list of customers ordered by creation date.",
    )
    doc_ok = EndpointSpec(
        method="GET",
        path="/customers",
        normalized_path="/customers",
        description="Returns a paginated list of customers sorted by creation date.",
    )
    spec_bad = EndpointSpec(
        method="POST",
        path="/orders/{order_id}/cancel",
        normalized_path="/orders/{}/cancel",
        description="Cancels an order that has not shipped yet and issues a full refund.",
    )
    doc_bad = EndpointSpec(
        method="POST",
        path="/orders/{order_id}/cancel",
        normalized_path="/orders/{}/cancel",
        description="Archives the order so that it is hidden from the default merchant list.",
    )
    spec_missing = EndpointSpec(
        method="DELETE",
        path="/customers/{customer_id}",
        normalized_path="/customers/{}",
        description="Permanently deletes a customer and all saved payment methods.",
    )
    doc_missing = EndpointSpec(
        method="DELETE",
        path="/customers/{customer_id}",
        normalized_path="/customers/{}",
        description="",
    )

    matched = match_endpoints([spec_ok, spec_bad, spec_missing], [doc_ok, doc_bad, doc_missing])
    desc_out = validate_descriptions(matched.paired)

    bands = {c.endpoint: c.band for c in desc_out.comparisons}
    assert bands["/customers"] == "High similarity"
    assert bands["/orders/{order_id}/cancel"] in ("Potential inconsistency", "Unrelated")
    assert bands["/customers/{customer_id}"] == "Missing"
    assert len(desc_out.issues) == 2

