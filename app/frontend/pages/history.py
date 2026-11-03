"""Analysis History view (Section 6)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.frontend.components.api_client import (
    BackendClientError,
    fetch_reports,
    fetch_session_detail,
    fetch_sessions,
    remove_session,
)
from app.frontend.components.styles import render_page_header


def render_history_page() -> None:
    render_page_header(
        "Analysis History",
        "Inspect, reload, export or delete previous validation sessions persisted in the local SQLite database.",
    )

    try:
        sessions = fetch_sessions(limit=200)
        reports = fetch_reports()
    except BackendClientError as exc:
        st.error(f"Could not load analysis history: {exc}")
        return

    if not sessions:
        st.info("No validation sessions have been saved yet.")
        if st.button("Start New Validation", type="primary"):
            st.session_state["active_nav"] = "New Validation"
            st.rerun()
        return

    df_sessions = pd.DataFrame([
        {
            "Session ID": s["session_id"],
            "Session Name": s["session_name"],
            "Created At": s["created_at"],
            "Documentation File": s["documentation_file"],
            "Specification File": s["specification_file"],
            "Completeness (%)": s["completeness_score"],
            "Spec Endpoints": s["total_spec_endpoints"],
            "Matched": s["matched_endpoints"],
            "Missing": s["missing_endpoints"],
            "Total Issues": s["total_issues"],
            "Critical": s["critical_issues"],
            "High": s["high_issues"],
            "Medium": s["medium_issues"],
            "Low": s["low_issues"],
        }
        for s in sessions
    ])
    st.dataframe(df_sessions, use_container_width=True, hide_index=True)

    st.markdown("#### Manage Session")
    session_options = {
        s["session_id"]: f"{s['session_id']} — {s['session_name']} ({s['created_at']}) | Score: {s['completeness_score']:.1f}%"
        for s in sessions
    }
    sel_id = st.selectbox(
        "Select Session",
        options=list(session_options.keys()),
        format_func=lambda k: session_options[k],
    )

    c1, c2, _ = st.columns([1.2, 1.2, 2.5])
    with c1:
        if st.button("Load Session into Results", type="primary", use_container_width=True):
            try:
                detail = fetch_session_detail(sel_id)
                st.session_state["current_result"] = detail
                st.session_state["active_nav"] = "Validation Results"
                st.rerun()
            except BackendClientError as exc:
                st.error(str(exc))
    with c2:
        if st.button("Delete Session", type="secondary", use_container_width=True):
            try:
                remove_session(sel_id)
                cur = st.session_state.get("current_result")
                if cur and cur.get("session_id") == sel_id:
                    st.session_state.pop("current_result", None)
                st.success(f"Deleted session {sel_id}.")
                st.rerun()
            except BackendClientError as exc:
                st.error(str(exc))

    if reports:
        st.markdown("#### Generated Report Log")
        df_rep = pd.DataFrame([
            {
                "Report ID": r["report_id"],
                "Session ID": r["session_id"],
                "Format": r["format"].upper(),
                "Filename": r["filename"],
                "Size (Bytes)": r["size_bytes"],
                "Generated At": r["generated_at"],
            }
            for r in reports
        ])
        st.dataframe(df_rep, use_container_width=True, hide_index=True)

