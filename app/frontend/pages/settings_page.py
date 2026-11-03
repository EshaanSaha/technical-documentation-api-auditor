"""Settings & Threshold Configuration Page."""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from app.frontend.components.api_client import (
    BackendClientError,
    fetch_thresholds,
    reset_thresholds,
    update_thresholds,
)
from app.frontend.components.styles import render_page_header


def render_settings_page(health: Optional[dict[str, Any]]) -> None:
    render_page_header(
        "Validation & NLP Engine Settings",
        "Configure heuristic similarity thresholds and inspect local NLP model parameters.",
    )

    try:
        current = fetch_thresholds()
    except BackendClientError as exc:
        st.error(f"Could not fetch settings from backend: {exc}")
        return

    col_form, col_info = st.columns([1.4, 1.0], gap="medium")

    with col_form:
        st.markdown("#### Heuristic Threshold Configuration")
        st.caption(
            "These thresholds govern description semantic similarity bands and fuzzy candidate alignment. "
            "Changes persist in SQLite and apply to subsequent validation runs."
        )
        with st.form("thresholds_form"):
            desc_high = st.slider(
                "High Description Similarity Threshold (Cosine)",
                min_value=0.70,
                max_value=0.98,
                value=float(current.get("description_high", 0.85)),
                step=0.01,
                help="Descriptions at or above this score are classified as 'High similarity'.",
            )
            desc_mod = st.slider(
                "Moderate Description Similarity Threshold (Cosine)",
                min_value=0.45,
                max_value=0.84,
                value=float(current.get("description_moderate", 0.65)),
                step=0.01,
                help="Descriptions below this score are flagged as 'Potential inconsistency'.",
            )
            desc_unrel = st.slider(
                "Unrelated Description Threshold (Cosine)",
                min_value=0.10,
                max_value=0.55,
                value=float(current.get("description_unrelated", 0.30)),
                step=0.01,
                help="Descriptions below this score are flagged as 'Unrelated' (High severity).",
            )
            ep_likely = st.slider(
                "Candidate Endpoint Match Threshold",
                min_value=0.45,
                max_value=0.90,
                value=float(current.get("endpoint_likely_match", 0.62)),
                step=0.01,
                help="Minimum combined path + method + semantic score to classify a non-exact pair as 'Likely match'.",
            )
            fuzzy_name = st.slider(
                "Identifier Fuzzy Alignment Threshold (RapidFuzz %)",
                min_value=65.0,
                max_value=95.0,
                value=float(current.get("name_fuzzy_match", 80.0)),
                step=1.0,
                help="Minimum RapidFuzz similarity to align a renamed parameter or schema attribute.",
            )

            sc1, sc2 = st.columns(2)
            with sc1:
                save_btn = st.form_submit_button("Save Thresholds", type="primary", use_container_width=True)
            with sc2:
                reset_btn = st.form_submit_button("Restore Defaults", use_container_width=True)

        if save_btn:
            if desc_mod >= desc_high or desc_unrel >= desc_mod:
                st.error("Ensure: Unrelated threshold < Moderate threshold < High threshold.")
            else:
                try:
                    update_thresholds({
                        "description_high": desc_high,
                        "description_moderate": desc_mod,
                        "description_unrelated": desc_unrel,
                        "endpoint_likely_match": ep_likely,
                        "name_fuzzy_match": fuzzy_name,
                    })
                    st.success("Saved updated thresholds to SQLite.")
                    st.rerun()
                except BackendClientError as exc:
                    st.error(str(exc))

        if reset_btn:
            try:
                reset_thresholds()
                st.success("Restored default thresholds.")
                st.rerun()
            except BackendClientError as exc:
                st.error(str(exc))

    with col_info:
        st.markdown(
            """
            <div class="auditor-panel">
                <p class="auditor-panel-title">Scoring &amp; Methodology Notes</p>
                <p style="font-size:0.84rem;color:#202B3C;line-height:1.5;">
                    <strong>Semantic similarity is not proof of correctness.</strong>
                    Two sentences can share high lexical/embedding overlap while differing in a critical negation or constraint.
                    Accordingly, structural checks (endpoints, parameters, types, requiredness, schemas, status codes)
                    are always evaluated deterministically alongside semantic description checks.
                </p>
                <p style="font-size:0.84rem;color:#202B3C;line-height:1.5;margin-bottom:4px;">
                    <strong>Completeness Score Weights:</strong>
                </p>
                <ul style="font-size:0.83rem;color:#202B3C;margin-top:0;">
                    <li>Endpoint Coverage &amp; Accuracy: <strong>30%</strong></li>
                    <li>Parameter Accuracy: <strong>25%</strong></li>
                    <li>Request &amp; Response Schemas: <strong>25%</strong></li>
                    <li>Status Codes &amp; Authentication: <strong>10%</strong></li>
                    <li>Description Consistency: <strong>10%</strong></li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if health:
            st.markdown(
                f"""
                <div class="auditor-panel">
                    <p class="auditor-panel-title">Local Model Paths</p>
                    <p style="font-size:0.82rem;color:#64748B;margin:0;">
                        <strong>spaCy Model:</strong> <code>{health.get('spacy_model_name')}</code><br/>
                        <strong>Embedding Model:</strong> <code>data/models/all-MiniLM-L6-v2</code><br/>
                        <strong>Offline Mode:</strong> <code>HF_HUB_OFFLINE=1</code>, <code>TRANSFORMERS_OFFLINE=1</code>
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

