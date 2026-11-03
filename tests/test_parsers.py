"""Unit tests for Markdown, DOCX, PDF and OpenAPI parsers."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.parsers.blocks import DocumentParseError
from app.parsers.loader import parse_documentation, parse_specification
from app.utils.file_validation import UploadValidationError, validate_upload


def test_parse_openapi_yaml_and_json() -> None:
    yaml_path = settings.sample_dir / "shopwave_openapi.yaml"
    json_path = settings.sample_dir / "shopwave_openapi.json"

    yaml_model = parse_specification(yaml_path.read_bytes(), yaml_path.name)
    json_model = parse_specification(json_path.read_bytes(), json_path.name)

    assert yaml_model.title == "ShopWave Commerce API"
    assert yaml_model.version == "2.3.0"
    assert yaml_model.base_path == "/v2"
    assert len(yaml_model.endpoints) == 10
    assert len(json_model.endpoints) == 10
    assert "bearer" in yaml_model.auth_methods

    create_order = next(ep for ep in yaml_model.endpoints if ep.method == "POST" and ep.path == "/orders")
    field_paths = {f.path for f in create_order.request_fields}
    assert "customer_id" in field_paths
    assert "currency" in field_paths
    assert "items[].product_id" in field_paths
    assert "shipping_address.postal_code" in field_paths


def test_parse_markdown_documentation() -> None:
    md_path = settings.sample_dir / "shopwave_api_docs.md"
    doc_model = parse_documentation(md_path.read_bytes(), md_path.name)

    assert len(doc_model.endpoints) == 10
    keys = {(ep.method, ep.path) for ep in doc_model.endpoints}
    assert ("GET", "/customers") in keys
    assert ("GET", "/customers/{customer_id}/rewards") in keys
    assert ("GET", "/v1/products/{product_id}") in keys
    assert "bearer" in doc_model.auth_methods


def test_parse_docx_documentation() -> None:
    docx_path = settings.sample_dir / "shopwave_api_docs.docx"
    doc_model = parse_documentation(docx_path.read_bytes(), docx_path.name)

    assert len(doc_model.endpoints) == 10
    keys = {(ep.method, ep.path) for ep in doc_model.endpoints}
    assert ("POST", "/customers") in keys
    assert ("GET", "/orders/{order_id}") in keys


def test_parse_pdf_documentation() -> None:
    pdf_path = settings.sample_dir / "shopwave_api_docs.pdf"
    doc_model = parse_documentation(pdf_path.read_bytes(), pdf_path.name)

    assert len(doc_model.endpoints) == 10
    keys = {(ep.method, ep.path) for ep in doc_model.endpoints}
    assert ("GET", "/customers") in keys
    assert ("POST", "/orders/{order_id}/cancel") in keys


def test_malformed_files_handled_gracefully() -> None:
    with pytest.raises(DocumentParseError):
        parse_documentation(b"   ", "empty.md")

    with pytest.raises(DocumentParseError):
        parse_documentation(b"not a zip archive", "broken.docx")

    with pytest.raises(DocumentParseError):
        parse_documentation(b"not a pdf header", "broken.pdf")

    with pytest.raises(DocumentParseError):
        parse_specification(b"{invalid json", "broken.json")

    with pytest.raises(DocumentParseError):
        parse_specification(b"key: value\nnot_openapi: true", "not_openapi.yaml")

    with pytest.raises(UploadValidationError):
        validate_upload(b"plain text", "malicious.exe", "documentation")

