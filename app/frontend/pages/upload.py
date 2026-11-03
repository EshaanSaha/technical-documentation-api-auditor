"""New Validation upload & sample runner page (Module A)."""

from __future__ import annotations

import streamlit as st

from app.frontend.components.api_client import (
    BackendClientError,
    preview_parse,
    run_sample_validation,
    run_validation_upload,
)
from app.frontend.components.styles import render_page_header

SAMPLE_SUITE_CATALOG: dict[str, dict] = {
    "FinLedger Enterprise Banking & Payments API v3.4 (18 Endpoints)": {
        "description": (
            "Large enterprise treasury, multi-currency accounts, ACH/SEPA/Wire transfers, commercial card "
            "issuing, real-time FX quotes, KYC compliance screening and webhook management suite."
        ),
        "docs": [
            ("finledger_api_docs.md", "finledger_api_docs.md (Markdown — 15 KB)"),
            ("finledger_api_docs.docx", "finledger_api_docs.docx (Word DOCX — 42 KB)"),
            ("finledger_api_docs.pdf", "finledger_api_docs.pdf (Multi-page PDF — 19 KB)"),
        ],
        "specs": [
            ("finledger_openapi.yaml", "finledger_openapi.yaml (OpenAPI 3.0.3 YAML — 24 KB)"),
            ("finledger_openapi.json", "finledger_openapi.json (OpenAPI 3.0.3 JSON — 40 KB)"),
        ],
        "highlights": [
            "Missing endpoints: POST /accounts/{account_id}/freeze and PATCH /cards/{card_id}/limits",
            "Legacy undocumented endpoint: GET /transfers/ach-batches",
            "Outdated path versions: POST /v2/webhooks/endpoints and GET /v1/compliance/kyc/{check_id}",
            "Parameter & schema drift: Idempotency-Key in query vs header, min_amount_cents float vs integer, amount vs amount_cents, beneficiary.routing_number vs beneficiary.bank_routing_number, masked_pan vs card_number_last4",
            "Semantic contradiction: DELETE /webhooks/endpoints/{webhook_id} (pausing & queuing for 7 days vs immediate secret revocation)",
        ],
    },
    "MedCore Clinical EHR & Patient Portal API v4.1 (15 Endpoints)": {
        "description": (
            "HL7/FHIR-aligned clinical healthcare suite covering master patient index (MPI) charts, "
            "outpatient scheduling, e-prescriptions (eRx), LOINC diagnostic lab panels and ICD-10 insurance claims."
        ),
        "docs": [
            ("medcore_api_docs.md", "medcore_api_docs.md (Markdown — 13 KB)"),
            ("medcore_api_docs.docx", "medcore_api_docs.docx (Word DOCX — 41 KB)"),
            ("medcore_api_docs.pdf", "medcore_api_docs.pdf (Multi-page PDF — 16 KB)"),
        ],
        "specs": [
            ("medcore_openapi.yaml", "medcore_openapi.yaml (OpenAPI 3.0.3 YAML — 20 KB)"),
            ("medcore_openapi.json", "medcore_openapi.json (OpenAPI 3.0.3 JSON — 35 KB)"),
        ],
        "highlights": [
            "Missing endpoints: DELETE /appointments/{appointment_id} and POST /prescriptions/{prescription_id}/refill",
            "Unexpected endpoint: GET /patients/{patient_id}/billing-summary",
            "Outdated path & auth mismatch: GET /v3/labs/orders/{lab_order_id} documented as public",
            "Parameter & schema drift: mrn vs patient_mrn, X-Facility-ID in query vs required header, missing required dosage_mg and insurance_policy.group_number, copay_cents vs patient_copay_cents, status 200 vs 202",
            "Description contradiction on PATCH /appointments/{appointment_id}/reschedule and missing description on GET /claims/{claim_id}",
        ],
    },
    "ShopWave Commerce API v2.3 (10 Endpoints — With Clean Reference)": {
        "description": (
            "E-commerce REST API for customers, orders and product catalogue, including both an intentionally "
            "drifted documentation set (MD, DOCX, PDF) and a 100% consistent clean reference document."
        ),
        "docs": [
            ("shopwave_api_docs.md", "shopwave_api_docs.md (Markdown — Intentional Discrepancies)"),
            ("shopwave_api_docs.docx", "shopwave_api_docs.docx (Word DOCX — Intentional Discrepancies)"),
            ("shopwave_api_docs.pdf", "shopwave_api_docs.pdf (PDF — Intentional Discrepancies)"),
            ("shopwave_api_docs_clean.md", "shopwave_api_docs_clean.md (Markdown — 100% Clean Reference)"),
        ],
        "specs": [
            ("shopwave_openapi.yaml", "shopwave_openapi.yaml (OpenAPI 3.0.3 YAML)"),
            ("shopwave_openapi.json", "shopwave_openapi.json (OpenAPI 3.0.3 JSON)"),
        ],
        "highlights": [
            "Missing endpoint: PATCH /customers/{customer_id}",
            "Unexpected endpoint: GET /customers/{customer_id}/rewards",
            "Outdated version & auth mismatch: GET /v1/products/{product_id}",
            "Parameter & schema drift: customer vs customer_id, include in header vs query, missing required currency, total vs total_amount, status 200 vs 201",
            "Description contradiction on POST /orders/{order_id}/cancel and missing description on DELETE /customers/{customer_id}",
        ],
    },
}


def _render_parse_preview(label: str, parsed: dict) -> None:
    endpoints = parsed.get("endpoints") or []
    warnings = parsed.get("warnings") or []
    st.markdown(
        f"**{label}** — Title: `{parsed.get('title') or 'Untitled'}` | "
        f"Version: `{parsed.get('version') or 'N/A'}` | "
        f"Extracted Operations: **{len(endpoints)}** | "
        f"Auth Schemes: `{', '.join(parsed.get('auth_methods') or ['none detected'])}`"
    )
    if warnings:
        for w in warnings:
            st.warning(w)
    if endpoints:
        rows = [
            {
                "Method": ep["method"],
                "Path": ep["path"],
                "Summary": ep.get("summary", ""),
                "Parameters": len(ep.get("parameters") or []),
                "Request Fields": len(ep.get("request_fields") or []),
                "Responses": ", ".join(r["status_code"] for r in (ep.get("responses") or [])),
            }
            for ep in endpoints
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)


def render_upload_page() -> None:
    render_page_header(
        "New Validation Audit",
        "Upload API documentation (PDF, DOCX, or Markdown) and its target OpenAPI specification (JSON or YAML), or select from the built-in enterprise sample suites.",
    )

    tab_upload, tab_sample = st.tabs(["Upload Files", "Enterprise Sample Suites (3 Domains, 16 Files)"])

    with tab_upload:
        st.caption(
            "Tip: You can also browse and upload any of the 16 generated files directly from the "
            "`data/sample_data/` folder on your computer (`finledger_*`, `medcore_*`, `shopwave_*`)."
        )
        session_name = st.text_input(
            "Audit Session Name (optional)",
            placeholder="e.g. FinLedger Treasury API v3.4 Pre-Release Audit",
        )

        col_doc, col_spec = st.columns(2, gap="medium")
        with col_doc:
            st.markdown("##### 1. API Reference Documentation")
            st.caption("Supported formats: PDF (`.pdf`), Microsoft Word (`.docx`), Markdown (`.md`)")
            doc_file = st.file_uploader(
                "Select Documentation File",
                type=["pdf", "docx", "md", "markdown"],
                key="doc_uploader",
            )
        with col_spec:
            st.markdown("##### 2. OpenAPI Specification")
            st.caption("Supported formats: OpenAPI 3.x / Swagger 2.0 in YAML (`.yaml`, `.yml`) or JSON (`.json`)")
            spec_file = st.file_uploader(
                "Select OpenAPI Specification",
                type=["yaml", "yml", "json"],
                key="spec_uploader",
            )

        btn_col1, btn_col2, _ = st.columns([1.2, 1.2, 2.0])
        with btn_col1:
            run_clicked = st.button(
                "Run Consistency Audit",
                type="primary",
                use_container_width=True,
                disabled=(doc_file is None or spec_file is None),
            )
        with btn_col2:
            preview_clicked = st.button(
                "Preview Extracted Structure",
                type="secondary",
                use_container_width=True,
                disabled=(doc_file is None and spec_file is None),
            )

        if preview_clicked:
            if doc_file is not None:
                with st.spinner(f"Parsing {doc_file.name}..."):
                    try:
                        parsed_doc = preview_parse(doc_file.getvalue(), doc_file.name, "documentation")
                        _render_parse_preview(f"Documentation ({doc_file.name})", parsed_doc)
                    except BackendClientError as exc:
                        st.error(f"Documentation parse error: {exc}")
            if spec_file is not None:
                with st.spinner(f"Parsing {spec_file.name}..."):
                    try:
                        parsed_spec = preview_parse(spec_file.getvalue(), spec_file.name, "specification")
                        _render_parse_preview(f"OpenAPI Specification ({spec_file.name})", parsed_spec)
                    except BackendClientError as exc:
                        st.error(f"Specification parse error: {exc}")

        if run_clicked and doc_file is not None and spec_file is not None:
            with st.spinner("Running NLP entity extraction, schema comparison and semantic similarity analysis..."):
                try:
                    result = run_validation_upload(
                        doc_bytes=doc_file.getvalue(),
                        doc_filename=doc_file.name,
                        spec_bytes=spec_file.getvalue(),
                        spec_filename=spec_file.name,
                        session_name=session_name,
                    )
                    st.session_state["current_result"] = result
                    st.session_state["active_nav"] = "Validation Results"
                    st.rerun()
                except BackendClientError as exc:
                    st.error(f"Validation failed: {exc}")

    with tab_sample:
        suite_name = st.selectbox(
            "Select Enterprise API Sample Suite",
            options=list(SAMPLE_SUITE_CATALOG.keys()),
        )
        suite = SAMPLE_SUITE_CATALOG[suite_name]

        bullets_html = "".join(f"<li>{item}</li>" for item in suite["highlights"])
        st.markdown(
            f"""
            <div class="auditor-panel">
                <p class="auditor-panel-title">{suite_name}</p>
                <p style="font-size:0.86rem;color:#1E293B;margin-bottom:8px;">{suite['description']}</p>
                <ul style="font-size:0.84rem;color:#1E293B;margin-bottom:4px;">{bullets_html}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

        doc_map = dict(suite["docs"])
        spec_map = dict(suite["specs"])

        sc1, sc2 = st.columns(2)
        with sc1:
            doc_choice = st.selectbox(
                "Sample Documentation File",
                options=list(doc_map.keys()),
                format_func=lambda k: doc_map[k],
            )
        with sc2:
            spec_choice = st.selectbox(
                "Sample OpenAPI Specification File",
                options=list(spec_map.keys()),
                format_func=lambda k: spec_map[k],
            )

        sample_session_name = st.text_input(
            "Sample Session Label (optional)",
            value=f"{suite_name.split(' (')[0]} ({doc_choice} vs {spec_choice})",
        )

        if st.button("Execute Sample Audit", type="primary"):
            with st.spinner(f"Auditing {doc_choice} against {spec_choice}..."):
                try:
                    result = run_sample_validation(
                        doc_variant=doc_choice,
                        spec_variant=spec_choice,
                        session_name=sample_session_name,
                    )
                    st.session_state["current_result"] = result
                    st.session_state["active_nav"] = "Validation Results"
                    st.rerun()
                except BackendClientError as exc:
                    st.error(f"Sample audit failed: {exc}")
