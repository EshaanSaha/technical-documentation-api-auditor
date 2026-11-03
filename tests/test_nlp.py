"""Unit tests for text normalization, entity extraction and semantic matching."""

from __future__ import annotations

from app.nlp.entity_extraction import (
    extract_entities,
    extract_parameter_mentions,
)
from app.nlp.semantic_matching import (
    get_semantic_matcher,
    name_similarity,
    path_similarity,
)
from app.nlp.text_normalization import (
    canonical_path,
    detect_auth_methods,
    normalize_identifier,
    normalize_type,
    path_parameters,
    path_template,
    split_version,
    strip_base_path,
)


def test_identifier_normalization_variations() -> None:
    assert normalize_identifier("customer_id") == "customer_id"
    assert normalize_identifier("customerId") == "customer_id"
    assert normalize_identifier("Customer-ID") == "customer_id"
    assert normalize_identifier("  Customer   Identifier ") == "customer_id"
    assert normalize_identifier("marketingOptIn") == "marketing_opt_in"


def test_type_normalization() -> None:
    assert normalize_type("string (uuid)") == "string"
    assert normalize_type("int64") == "integer"
    assert normalize_type("float") == "number"
    assert normalize_type("boolean") == "boolean"
    assert normalize_type("Array<OrderItem>") == "array"
    assert normalize_type("object") == "object"


def test_path_normalization_and_templates() -> None:
    assert canonical_path("https://api.shopwave.io/v2/customers/:customerId/") == "/v2/customers/{customerId}"
    assert path_parameters("/orders/<uuid:order_id>/items/{item_id}") == ["order_id", "item_id"]
    assert path_template("/v2/Customer-Orders/{orderId}") == "/v2/customer_orders/{}"
    assert path_template("/v1/products/{product_id}", strip_version=True) == "/products/{}"
    assert split_version("/v1/products/{id}") == ("v1", "/products/{id}")
    assert strip_base_path("/v2/customers", "/v2") == "/customers"


def test_auth_method_detection() -> None:
    methods = detect_auth_methods("Authenticate with a Bearer JWT token or an X-API-Key header.")
    assert "bearer" in methods
    assert "api_key" in methods


def test_entity_extraction_and_compound_noun_filtering() -> None:
    text = (
        "Send GET /v2/customers/{customer_id} with the `include_orders` query parameter (boolean). "
        "The customer's phone number is returned on 200 OK or 404 Not Found."
    )
    entities = extract_entities(text, source="unit_test")
    by_label = {(e.label, e.normalized) for e in entities}

    assert ("ENDPOINT", "GET /v2/customers/{customer_id}") in by_label
    assert ("PARAMETER", "include_orders") in by_label
    assert ("DATA_TYPE", "boolean") in by_label
    assert ("STATUS_CODE", "200") in by_label
    assert ("STATUS_CODE", "404") in by_label
    # "phone number" is a compound noun, so "number" must not be misclassified as a DATA_TYPE
    assert ("DATA_TYPE", "number") not in by_label


def test_parameter_mentions_requiredness_and_negation() -> None:
    req_sentence = "The `customer_id` path parameter (string) is required."
    opt_sentence = "The `cursor` query parameter (string) is not required and may be omitted."

    req_mentions = extract_parameter_mentions(req_sentence)
    opt_mentions = extract_parameter_mentions(opt_sentence)

    assert len(req_mentions) == 1
    assert req_mentions[0].normalized_name == "customer_id"
    assert req_mentions[0].location == "path"
    assert req_mentions[0].type == "string"
    assert req_mentions[0].required is True

    assert len(opt_mentions) == 1
    assert opt_mentions[0].normalized_name == "cursor"
    assert opt_mentions[0].location == "query"
    assert opt_mentions[0].required is False


def test_lexical_and_semantic_similarity() -> None:
    assert name_similarity("customer_id", "customerId") == 100.0
    assert name_similarity("customer_id", "customer") >= 80.0
    assert path_similarity(
        path_template("/products/{id}", strip_version=True),
        path_template("/v1/products/{id}", strip_version=True),
    ) == 1.0

    matcher = get_semantic_matcher()
    assert matcher.available(), "Local MiniLM embedding model must be available in data/models/"
    scores = matcher.similarity_pairs([
        (
            "Returns a paginated list of customers ordered by creation date.",
            "Returns a paginated list of customers sorted by when they were created.",
        ),
        (
            "Cancels an order that has not shipped yet and issues a full refund.",
            "Archives the order so that it is hidden from the default merchant dashboard.",
        ),
    ])
    assert scores[0] >= 0.85
    assert scores[1] < 0.65

