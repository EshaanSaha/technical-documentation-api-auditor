"""Validation Results Dashboard & Report Export View (Modules G & H)."""

from __future__ import annotations

from html import escape
from typing import Any, Optional

import pandas as pd
import streamlit as st

from app.frontend.components.api_client import (
    BackendClientError,
    download_report,
    fetch_session_detail,
    fetch_sessions,
)
from app.frontend.components.styles import (
    build_category_chart,
    build_score_breakdown_chart,
    build_severity_chart,
    render_kpi_card,
    render_page_header,
    severity_badge_html,
)


def _ensure_active_result() -> Optional[dict[str, Any]]:
    result = st.session_state.get("current_result")
    if result is not None:
        return result
    try:
        sessions = fetch_sessions(limit=1)
        if sessions:
            loaded = fetch_session_detail(sessions[0]["session_id"])
            st.session_state["current_result"] = loaded
            return loaded
    except BackendClientError:
        return None
    return None


def render_results_page() -> None:
    result = _ensure_active_result()
    if result is None:
        render_page_header(
            "Validation Results",
            "No validation session is currently loaded.",
        )
        st.info("Run a validation from **New Validation** or select a previous run in **Analysis History**.")
        if st.button("Go to New Validation", type="primary"):
            st.session_state["active_nav"] = "New Validation"
            st.rerun()
        return

    session_id = result.get("session_id", "")
    summary = result.get("summary") or {}
    issues: list[dict[str, Any]] = result.get("issues") or []
    matches: list[dict[str, Any]] = result.get("matches") or []
    comparisons: list[dict[str, Any]] = result.get("comparisons") or []
    descriptions: list[dict[str, Any]] = result.get("descriptions") or []
    entities: list[dict[str, Any]] = result.get("entities") or []
    score_breakdown: list[dict[str, Any]] = result.get("score_breakdown") or []

    render_page_header(
        f"Validation Results — {result.get('session_name') or 'Audit Session'}",
        (
            f"Session ID: {session_id}  |  Created: {result.get('created_at')}  |  "
            f"Documentation: {result.get('documentation_file')}  |  "
            f"Specification: {result.get('specification_file')}"
        ),
    )

    for warn in result.get("warnings") or []:
        st.warning(warn)

    # ------------------------------------------------------------------ #
    # Downloadable Reports Bar (Module H: CSV, Excel, PDF)
    # ------------------------------------------------------------------ #
    exp_col1, exp_col2, exp_col3, exp_col4 = st.columns([1.6, 1.0, 1.0, 1.0])
    with exp_col1:
        st.markdown(
            "**Export Audit Report**  \n"
            "<span style='font-size:0.8rem;color:#64748B;'>Includes summary, findings, evidence &amp; recommended corrections.</span>",
            unsafe_allow_html=True,
        )
    if session_id:
        for idx, (col, fmt, label, mime) in enumerate(
            [
                (exp_col2, "csv", "Download CSV", "text/csv"),
                (
                    exp_col3,
                    "xlsx",
                    "Download Excel (.xlsx)",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
                (exp_col4, "pdf", "Download PDF", "application/pdf"),
            ]
        ):
            with col:
                cache_key = f"report_bytes_{session_id}_{fmt}"
                if cache_key not in st.session_state:
                    try:
                        data, fname = download_report(session_id, fmt)
                        st.session_state[cache_key] = (data, fname)
                    except BackendClientError as exc:
                        st.error(str(exc))
                        continue
                data, fname = st.session_state[cache_key]
                st.download_button(
                    label=label,
                    data=data,
                    file_name=fname,
                    mime=mime,
                    key=f"dl_{session_id}_{fmt}_{idx}",
                    use_container_width=True,
                )

    st.write("")

    # ------------------------------------------------------------------ #
    # 8 Required KPI Metrics (Module G) — 2 rows of 4 cards
    # ------------------------------------------------------------------ #
    score = float(result.get("completeness_score", 0.0))
    score_color = "#15803D" if score >= 85 else ("#B45309" if score >= 65 else "#B91C1C")

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    with r1c1:
        render_kpi_card(
            "Completeness Score",
            f"{score:.1f}%",
            f"{summary.get('total_issues', len(issues))} total findings",
            accent_color=score_color,
        )
    with r1c2:
        render_kpi_card(
            "Spec Endpoints",
            str(summary.get("total_spec_endpoints", 0)),
            f"OpenAPI: {result.get('specification_file')}",
            accent_color="#2B5B84",
        )
    with r1c3:
        render_kpi_card(
            "Documented Endpoints",
            str(summary.get("total_doc_endpoints", 0)),
            f"{summary.get('unexpected_endpoints', 0)} unexpected in docs",
            accent_color="#0284C7",
        )
    with r1c4:
        render_kpi_card(
            "Matched Endpoints",
            str(summary.get("matched_endpoints", 0)),
            f"{summary.get('exact_matched_endpoints', 0)} exact, {summary.get('likely_matched_endpoints', 0)} likely",
            accent_color="#0F766E",
        )

    st.write("")
    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    with r2c1:
        miss_ep = int(summary.get("missing_endpoints", 0))
        render_kpi_card(
            "Missing Endpoints",
            str(miss_ep),
            "In spec, absent from docs",
            accent_color="#B91C1C" if miss_ep > 0 else "#315B8A",
        )
    with r2c2:
        p_mis = int(summary.get("parameter_mismatches", 0))
        render_kpi_card(
            "Parameter Mismatches",
            str(p_mis),
            "Names, types, requiredness, location",
            accent_color="#C2410C" if p_mis > 0 else "#315B8A",
        )
    with r2c3:
        s_mis = int(summary.get("schema_inconsistencies", 0))
        render_kpi_card(
            "Schema & Status Issues",
            str(s_mis),
            f"Req: {summary.get('request_schema_issues', 0)} | Resp: {summary.get('response_schema_issues', 0)} | Status: {summary.get('status_code_issues', 0)}",
            accent_color="#C2410C" if s_mis > 0 else "#315B8A",
        )
    with r2c4:
        d_mis = int(summary.get("description_inconsistencies", 0))
        render_kpi_card(
            "Description Inconsistencies",
            str(d_mis),
            "Semantic similarity & missing prose",
            accent_color="#B45309" if d_mis > 0 else "#315B8A",
        )

    st.write("")

    # ------------------------------------------------------------------ #
    # Plotly Charts
    # ------------------------------------------------------------------ #
    ch1, ch2, ch3 = st.columns(3)
    with ch1:
        st.plotly_chart(
            build_severity_chart(summary.get("severity_counts") or {}),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with ch2:
        st.plotly_chart(
            build_category_chart(summary.get("category_counts") or {}),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with ch3:
        st.plotly_chart(
            build_score_breakdown_chart(score_breakdown),
            use_container_width=True,
            config={"displayModeBar": False},
        )

    # ------------------------------------------------------------------ #
    # Interactive Filters (HTTP method, Validation category, Severity, Endpoint)
    # ------------------------------------------------------------------ #
    st.markdown("#### Filter Validation Findings")
    all_methods = sorted({i["method"] for i in issues} | {m.get("spec_method") or m.get("doc_method") or "" for m in matches} - {""})
    all_categories = sorted({i["category"] for i in issues})
    all_severities = [s for s in ["Critical", "High", "Medium", "Low", "Informational"] if any(i["severity"] == s for i in issues)]
    all_endpoints = sorted({i["endpoint"] for i in issues})

    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        sel_methods = st.multiselect("HTTP Method", options=all_methods, default=[])
    with fc2:
        sel_categories = st.multiselect("Validation Category", options=all_categories, default=[])
    with fc3:
        sel_severities = st.multiselect("Severity", options=all_severities, default=[])
    with fc4:
        sel_endpoints = st.multiselect("Endpoint", options=all_endpoints, default=[])

    filtered_issues = [
        i
        for i in issues
        if (not sel_methods or i["method"] in sel_methods)
        and (not sel_categories or i["category"] in sel_categories)
        and (not sel_severities or i["severity"] in sel_severities)
        and (not sel_endpoints or i["endpoint"] in sel_endpoints)
    ]

    # ------------------------------------------------------------------ #
    # Detailed Analysis Tabs
    # ------------------------------------------------------------------ #
    tab_issues, tab_endpoints, tab_schemas, tab_desc, tab_nlp = st.tabs([
        f"Findings & Corrections ({len(filtered_issues)})",
        f"Endpoint Matching ({len(matches)})",
        f"Parameters & Schemas ({len(comparisons)})",
        f"Description Consistency ({len(descriptions)})",
        f"NLP Entities ({len(entities)})",
    ])

    # Tab 1: Findings & Corrections
    with tab_issues:
        if not filtered_issues:
            st.success("No validation issues match the current filter criteria.")
        else:
            df_issues = pd.DataFrame([
                {
                    "ID": i["issue_id"],
                    "Severity": i["severity"],
                    "Category": i["category"],
                    "Method": i["method"],
                    "Endpoint": i["endpoint"],
                    "Issue Type": i["issue_type"],
                    "Expected (Spec)": i["expected"],
                    "Actual (Documented)": i["actual"],
                    "Recommended Correction": i["suggestion"],
                }
                for i in filtered_issues
            ])
            st.dataframe(df_issues, use_container_width=True, hide_index=True)

            st.markdown("##### Detailed Evidence & Recommended Corrections")
            for idx_iss, issue in enumerate(filtered_issues):
                header_text = (
                    f"[{issue['issue_id']}] {issue['severity']} | {issue['category']} — "
                    f"{issue['method']} {issue['endpoint']} — {issue['issue_type']}"
                )
                with st.expander(header_text, expanded=(idx_iss < 2)):
                    st.markdown(
                        f"{severity_badge_html(issue['severity'])} "
                        f"<span class='method-badge'>{escape(issue['method'])}</span> "
                        f"<code>{escape(issue['endpoint'])}</code>",
                        unsafe_allow_html=True,
                    )
                    c_exp, c_act = st.columns(2)
                    with c_exp:
                        st.markdown(
                            f"<div class='diff-box-expected'><div class='diff-label'>Expected (OpenAPI Specification)</div>"
                            f"{escape(issue['expected'])}</div>",
                            unsafe_allow_html=True,
                        )
                    with c_act:
                        st.markdown(
                            f"<div class='diff-box-actual'><div class='diff-label'>Actual (Documentation)</div>"
                            f"{escape(issue['actual'])}</div>",
                            unsafe_allow_html=True,
                        )
                    st.markdown(f"**Explanation:** {issue['explanation']}")
                    st.markdown(f"**Evidence:** `{issue['evidence']}`")
                    st.markdown(f"**Recommended Correction:** {issue['suggestion']}")

    # Tab 2: Endpoint Matching
    with tab_endpoints:
        filtered_matches = [
            m
            for m in matches
            if (not sel_methods or (m.get("spec_method") in sel_methods or m.get("doc_method") in sel_methods))
            and (not sel_endpoints or (m.get("spec_path") in sel_endpoints or m.get("doc_path") in sel_endpoints))
        ]
        df_matches = pd.DataFrame([
            {
                "Classification": m["status"],
                "Spec Method": m.get("spec_method") or "—",
                "Spec Path": m.get("spec_path") or "—",
                "Doc Method": m.get("doc_method") or "—",
                "Doc Path": m.get("doc_path") or "—",
                "Confidence": round(float(m.get("confidence", 0.0)), 2),
                "Doc Location": m.get("doc_location") or "—",
                "Explanation": m.get("explanation") or "",
            }
            for m in filtered_matches
        ])
        st.dataframe(df_matches, use_container_width=True, hide_index=True)

    # Tab 3: Parameter & Schema Comparison
    with tab_schemas:
        status_filter = st.radio(
            "Comparison Status Filter",
            options=["All Elements", "Discrepancies Only", "Matching Only"],
            horizontal=True,
        )
        filtered_cmp = [
            row
            for row in comparisons
            if (not sel_methods or row["method"] in sel_methods)
            and (not sel_endpoints or row["endpoint"] in sel_endpoints)
            and (
                status_filter == "All Elements"
                or (status_filter == "Discrepancies Only" and row["status"] != "OK")
                or (status_filter == "Matching Only" and row["status"] == "OK")
            )
        ]
        if not filtered_cmp:
            st.info("No parameter or schema comparison rows match the current filter.")
        else:
            df_cmp = pd.DataFrame([
                {
                    "Method": r["method"],
                    "Endpoint": r["endpoint"],
                    "Scope": r["scope"],
                    "Spec Name": r["name"],
                    "Documented Name": r["documented_name"] or "—",
                    "Expected Type": r["expected_type"] or "—",
                    "Documented Type": r["documented_type"] or "—",
                    "Expected Req.": r["expected_required"] or "—",
                    "Documented Req.": r["documented_required"] or "—",
                    "Expected In": r["expected_location"] or "—",
                    "Documented In": r["documented_location"] or "—",
                    "Validation Status": r["status"],
                }
                for r in filtered_cmp
            ])
            st.dataframe(df_cmp, use_container_width=True, hide_index=True)

    # Tab 4: Description Consistency (Side-by-Side)
    with tab_desc:
        st.caption(
            "Semantic similarity computed locally using sentence-transformers/all-MiniLM-L6-v2. "
            "Heuristic bands: >= 0.85 High similarity | 0.65–0.84 Moderate similarity | < 0.65 Potential inconsistency."
        )
        filtered_desc = [
            d
            for d in descriptions
            if (not sel_methods or d["method"] in sel_methods)
            and (not sel_endpoints or d["endpoint"] in sel_endpoints)
        ]
        if not filtered_desc:
            st.info("No description comparisons match the current filter.")
        else:
            for d in filtered_desc:
                sim_val = d.get("similarity")
                sim_str = f"{sim_val:.2f}" if isinstance(sim_val, (int, float)) else "N/A"
                band = d.get("band", "")
                flagged = band in ("Potential inconsistency", "Unrelated", "Missing")
                title = (
                    f"{'[FLAGGED] ' if flagged else ''}{d['method']} {d['endpoint']} — {d['element']}  |  "
                    f"Similarity: {sim_str} ({band})"
                )
                with st.expander(title, expanded=flagged):
                    col_s, col_d = st.columns(2)
                    with col_s:
                        st.markdown(
                            f"<div class='diff-box-expected'><div class='diff-label'>OpenAPI Specification Text</div>"
                            f"{escape(d.get('spec_text') or '(None)')}</div>",
                            unsafe_allow_html=True,
                        )
                    with col_d:
                        box_cls = "diff-box-actual" if flagged else "diff-box"
                        st.markdown(
                            f"<div class='{box_cls}'><div class='diff-label'>Documentation Text</div>"
                            f"{escape(d.get('doc_text') or '(Missing in documentation)')}</div>",
                            unsafe_allow_html=True,
                        )

    # Tab 5: Extracted NLP Entities
    with tab_nlp:
        st.caption(
            "Technical entities extracted from documentation via spaCy linguistic parsing and custom patterns, "
            "showing both original surface text and canonical normalized representations."
        )
        if not entities:
            st.info("No technical entities recorded.")
        else:
            label_options = sorted({e["label"] for e in entities})
            sel_labels = st.multiselect("Entity Type", options=label_options, default=[])
            shown_entities = [e for e in entities if not sel_labels or e["label"] in sel_labels]
            df_ent = pd.DataFrame([
                {
                    "Entity Type": e["label"],
                    "Original Value": e["text"],
                    "Normalized Value": e["normalized"],
                    "Source Location": e["source"],
                    "Sentence Context": e["context"],
                }
                for e in shown_entities
            ])
            st.dataframe(df_ent, use_container_width=True, hide_index=True)

