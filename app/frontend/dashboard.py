"""Main Streamlit dashboard entrypoint for Technical Documentation & API Consistency Auditor."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.frontend.components.api_client import get_health  # noqa: E402
from app.frontend.components.styles import apply_enterprise_styles  # noqa: E402
from app.frontend.pages.history import render_history_page  # noqa: E402
from app.frontend.pages.results import render_results_page  # noqa: E402
from app.frontend.pages.settings_page import render_settings_page  # noqa: E402
from app.frontend.pages.upload import render_upload_page  # noqa: E402
from app.frontend.pages.validation import render_overview_page  # noqa: E402

NAV_ITEMS = [
    "Overview",
    "New Validation",
    "Validation Results",
    "Analysis History",
    "Settings",
]


def main() -> None:
    st.set_page_config(
        page_title="Technical Documentation & API Consistency Auditor",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_enterprise_styles()

    if "active_nav" not in st.session_state or st.session_state["active_nav"] not in NAV_ITEMS:
        qp_page = st.query_params.get("page", "Overview")
        st.session_state["active_nav"] = qp_page if qp_page in NAV_ITEMS else "Overview"

    health = get_health()

    with st.sidebar:
        st.markdown(
            """
            <div style="padding:4px 0 14px 0;border-bottom:1px solid #334155;margin-bottom:14px;">
                <div style="font-size:1.05rem;font-weight:700;color:#F8FAFC !important;letter-spacing:-0.01em;">
                    API Consistency Auditor
                </div>
                <div style="font-size:0.76rem;color:#94A3B8 !important;margin-top:3px;">
                    Documentation &amp; OpenAPI Verification
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected = st.radio(
            "Navigation",
            options=NAV_ITEMS,
            index=NAV_ITEMS.index(st.session_state["active_nav"]),
            label_visibility="collapsed",
        )
        if selected != st.session_state["active_nav"]:
            st.session_state["active_nav"] = selected
            st.rerun()

        st.markdown("<hr style='border:none;border-top:1px solid #334155;margin:14px 0;'/>", unsafe_allow_html=True)

        current_res = st.session_state.get("current_result")
        if current_res:
            st.markdown(
                f"""
                <div style="font-size:0.78rem;background:#0F172A;border:1px solid #334155;border-left:3px solid #38BDF8;border-radius:5px;padding:10px 12px;">
                    <div style="font-weight:600;color:#F8FAFC !important;margin-bottom:4px;">Active Audit Session</div>
                    <div style="color:#CBD5E1 !important;">ID: <code>{current_res.get('session_id', 'N/A')}</code></div>
                    <div style="color:#CBD5E1 !important;">Score: <strong>{float(current_res.get('completeness_score', 0.0)):.1f}%</strong></div>
                    <div style="color:#CBD5E1 !important;">Issues: <strong>{len(current_res.get('issues') or [])}</strong></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        status_dot = "#22C55E" if health else "#EF4444"
        status_label = "Backend Online (Local)" if health else "Backend Offline"
        st.markdown(
            f"""
            <div style="margin-top:14px;font-size:0.76rem;color:#94A3B8 !important;">
                <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{status_dot};margin-right:6px;"></span>
                {status_label}
            </div>
            """,
            unsafe_allow_html=True,
        )

    active = st.session_state["active_nav"]
    if active == "Overview":
        render_overview_page(health)
    elif active == "New Validation":
        render_upload_page()
    elif active == "Validation Results":
        render_results_page()
    elif active == "Analysis History":
        render_history_page()
    elif active == "Settings":
        render_settings_page(health)


if __name__ == "__main__":
    main()

