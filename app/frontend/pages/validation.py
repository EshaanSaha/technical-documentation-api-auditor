"""Overview landing page.

Explains the application's architecture and purpose, shows live local runtime
readiness (FastAPI backend, SQLite database, spaCy pipeline, local MiniLM
embedding model), summarizes recent audit sessions from the database, and
provides prominent actions to start a new validation or run the built-in
sample dataset.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import streamlit as st

from app.frontend.components.api_client import (
    BackendClientError,
    fetch_session_detail,
    fetch_sessions,
    run_sample_validation,
)
from app.frontend.components.styles import render_kpi_card, render_page_header


def render_overview_page(health: Optional[dict[str, Any]]) -> None:
    render_page_header(
        "Technical Documentation & API Consistency Auditor",
        "Automated local NLP verification comparing API reference documentation (PDF, DOCX, Markdown) against OpenAPI 3.x / Swagger 2.0 specifications.",
    )

    col_left, col_right = st.columns([1.65, 1.0], gap="medium")

    with col_left:
        st.markdown(
            """
            <div class="auditor-panel">
                <p class="auditor-panel-title">Audit Pipeline Overview</p>
                <p style="font-size:0.88rem;color:#202B3C;line-height:1.55;margin-bottom:10px;">
                    Engineering teams often maintain customer-facing API guides in Markdown, Word (DOCX),
                    or PDF alongside machine-readable OpenAPI specifications. Over release cycles, endpoint
                    paths, parameters, request/response schemas, status codes and behavioral descriptions drift apart.
                </p>
                <table style="width:100%;font-size:0.84rem;border-collapse:collapse;">
                    <tr style="border-bottom:1px solid #E2E8F0;">
                        <td style="padding:6px 8px;font-weight:600;width:32%;color:#315B8A;">1. Document Parsing</td>
                        <td style="padding:6px 8px;color:#202B3C;">Extracts headings, parameter tables, JSON examples and prose from PDF, DOCX, Markdown and OpenAPI YAML/JSON.</td>
                    </tr>
                    <tr style="border-bottom:1px solid #E2E8F0;">
                        <td style="padding:6px 8px;font-weight:600;color:#315B8A;">2. NLP Entity Normalization</td>
                        <td style="padding:6px 8px;color:#202B3C;">Uses spaCy linguistic parsing and identifier canonicalization (<code>customer_id</code>, <code>customerId</code>, <code>Customer-ID</code>).</td>
                    </tr>
                    <tr style="border-bottom:1px solid #E2E8F0;">
                        <td style="padding:6px 8px;font-weight:600;color:#315B8A;">3. Endpoint &amp; Schema Alignment</td>
                        <td style="padding:6px 8px;color:#202B3C;">Deterministic template matching plus RapidFuzz candidate scoring for renamed parameters, nested fields and status codes.</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 8px;font-weight:600;color:#315B8A;">4. Semantic Consistency</td>
                        <td style="padding:6px 8px;color:#202B3C;">Compares endpoint and parameter descriptions locally using <code>sentence-transformers/all-MiniLM-L6-v2</code> embeddings.</td>
                    </tr>
                </table>
            </div>
            """,
            unsafe_allow_html=True,
        )

        act1, act2 = st.columns(2)
        with act1:
            if st.button("Start New Validation", type="primary", use_container_width=True):
                st.session_state["active_nav"] = "New Validation"
                st.rerun()
        with act2:
            if st.button("Run Built-in Sample Audit (ShopWave API)", type="secondary", use_container_width=True):
                with st.spinner("Running validation pipeline on ShopWave sample dataset..."):
                    try:
                        res = run_sample_validation(
                            doc_variant="shopwave_api_docs.md",
                            spec_variant="shopwave_openapi.yaml",
                        )
                        st.session_state["current_result"] = res
                        st.session_state["active_nav"] = "Validation Results"
                        st.rerun()
                    except BackendClientError as exc:
                        st.error(f"Sample validation failed: {exc}")

    with col_right:
        if health:
            spacy_status = f"Ready ({health.get('spacy_model_name')})" if health.get("spacy_model_loaded") else "Fallback (blank_en)"
            emb_status = "Ready (local offline)" if health.get("embedding_model_downloaded") else "Not downloaded"
            db_status = "Connected (SQLite)" if health.get("database_ready") else "Initializing"
            st.markdown(
                f"""
                <div class="auditor-panel">
                    <p class="auditor-panel-title">Local Environment Status</p>
                    <table style="width:100%;font-size:0.84rem;border-collapse:collapse;">
                        <tr style="border-bottom:1px solid #E2E8F0;">
                            <td style="padding:6px 4px;color:#64748B;">FastAPI Backend</td>
                            <td style="padding:6px 4px;font-weight:600;color:#15803D;">Online (v{health.get('version', '1.0.0')})</td>
                        </tr>
                        <tr style="border-bottom:1px solid #E2E8F0;">
                            <td style="padding:6px 4px;color:#64748B;">spaCy Pipeline</td>
                            <td style="padding:6px 4px;font-weight:600;color:#202B3C;">{spacy_status}</td>
                        </tr>
                        <tr style="border-bottom:1px solid #E2E8F0;">
                            <td style="padding:6px 4px;color:#64748B;">Embedding Model</td>
                            <td style="padding:6px 4px;font-weight:600;color:#202B3C;">all-MiniLM-L6-v2 ({emb_status})</td>
                        </tr>
                        <tr style="border-bottom:1px solid #E2E8F0;">
                            <td style="padding:6px 4px;color:#64748B;">Persistence</td>
                            <td style="padding:6px 4px;font-weight:600;color:#202B3C;">{db_status}</td>
                        </tr>
                        <tr>
                            <td style="padding:6px 4px;color:#64748B;">External API Calls</td>
                            <td style="padding:6px 4px;font-weight:600;color:#202B3C;">Disabled (100% Local)</td>
                        </tr>
                    </table>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.error("FastAPI backend is not reachable. Start the application with `python run.py`.")
            return

    # Recent sessions summary from actual database records
    try:
        sessions = fetch_sessions(limit=10)
    except BackendClientError:
        sessions = []

    st.markdown("#### Recent Audit Sessions")
    if not sessions:
        st.info(
            "No validation sessions have been recorded yet. Click **Start New Validation** to upload files "
            "or **Run Built-in Sample Audit (ShopWave API)** above to inspect a full validation report."
        )
        return

    latest = sessions[0]
    avg_score = sum(float(s["completeness_score"]) for s in sessions) / len(sessions)
    total_findings = sum(int(s["total_issues"]) for s in sessions)

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        render_kpi_card("Recorded Sessions", str(len(sessions)), f"Latest: {latest['created_at']}", accent_color="#2B5B84")
    with k2:
        render_kpi_card("Latest Completeness", f"{latest['completeness_score']:.1f}%", latest["session_name"], accent_color="#0F766E")
    with k3:
        render_kpi_card("Average Completeness", f"{avg_score:.1f}%", "Across recorded sessions", accent_color="#0284C7")
    with k4:
        render_kpi_card("Total Findings Logged", str(total_findings), f"Latest session: {latest['total_issues']} findings", accent_color="#D97706")

    st.write("")
    df = pd.DataFrame([
        {
            "Session ID": s["session_id"],
            "Session Name": s["session_name"],
            "Timestamp": s["created_at"],
            "Documentation": s["documentation_file"],
            "Specification": s["specification_file"],
            "Completeness (%)": s["completeness_score"],
            "Spec Endpoints": s["total_spec_endpoints"],
            "Matched": s["matched_endpoints"],
            "Missing": s["missing_endpoints"],
            "Total Findings": s["total_issues"],
        }
        for s in sessions[:5]
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    open_col, _ = st.columns([1, 3])
    with open_col:
        if st.button(f"Open Latest Session ({latest['session_id']})", use_container_width=True):
            try:
                st.session_state["current_result"] = fetch_session_detail(latest["session_id"])
                st.session_state["active_nav"] = "Validation Results"
                st.rerun()
            except BackendClientError as exc:
                st.error(str(exc))

