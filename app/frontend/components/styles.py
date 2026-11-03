"""Clean enterprise developer-tool styling and Plotly chart builders.

Uses a balanced slate-navy and steel-blue developer palette:
* App canvas: #EEF2F6 (soft cool slate-grey so cards stand out clearly)
* Sidebar: #1E293B (deep slate-navy with crisp light text)
* Card surface: #FFFFFF with subtle #CBD5E1 borders and colored top/left accents
* Primary accent: #2B5B84 / #0F766E (muted steel blue & teal)
* Restrained semantic tints for Expected (soft sage) vs Actual (soft amber/rose)
"""

from __future__ import annotations

from html import escape
from typing import Any

import plotly.graph_objects as go
import streamlit as st

SEVERITY_COLORS: dict[str, tuple[str, str, str]] = {
    # severity -> (text_color, bg_color, border_color)
    "Critical": ("#991B1B", "#FEF2F2", "#FCA5A5"),
    "High": ("#9A3412", "#FFF7ED", "#FDBA74"),
    "Medium": ("#854D0E", "#FEFCE8", "#FDE047"),
    "Low": ("#1E40AF", "#EFF6FF", "#93C5FD"),
    "Informational": ("#334155", "#F1F5F9", "#CBD5E1"),
}

SEVERITY_BAR_COLORS: dict[str, str] = {
    "Critical": "#DC2626",
    "High": "#EA580C",
    "Medium": "#D97706",
    "Low": "#2563EB",
    "Informational": "#64748B",
}

CATEGORY_PALETTE: list[str] = [
    "#2B5B84",
    "#0F766E",
    "#3B82F6",
    "#0284C7",
    "#475569",
    "#0D9488",
    "#1D4ED8",
]


def apply_enterprise_styles() -> None:
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {
            color: #1E293B;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
        }
        .stApp {
            background-color: #EEF2F6;
        }
        /* Deep slate-navy developer sidebar */
        section[data-testid="stSidebar"] {
            background-color: #1E293B;
            border-right: 1px solid #0F172A;
        }
        section[data-testid="stSidebar"] * {
            color: #E2E8F0 !important;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label {
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 5px;
            padding: 8px 12px;
            margin-bottom: 6px;
            transition: background-color 0.15s ease;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
            background-color: rgba(56, 189, 248, 0.14);
            border-color: rgba(56, 189, 248, 0.35);
        }
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2.5rem;
            max-width: 1380px;
        }
        /* Top page banner with steel-blue accent bar */
        .auditor-header {
            background-color: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-left: 5px solid #2B5B84;
            border-radius: 6px;
            padding: 16px 22px;
            margin-bottom: 18px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        .auditor-title {
            font-size: 1.25rem;
            font-weight: 600;
            color: #0F172A;
            margin: 0;
            letter-spacing: -0.01em;
        }
        .auditor-subtitle {
            font-size: 0.875rem;
            color: #475569;
            margin-top: 4px;
            margin-bottom: 0;
        }
        /* Content panels */
        .auditor-panel {
            background-color: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-top: 3px solid #3B6E9C;
            border-radius: 6px;
            padding: 16px 20px;
            margin-bottom: 14px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        .auditor-panel-title {
            font-size: 0.95rem;
            font-weight: 600;
            color: #1E3A5F;
            margin: 0 0 10px 0;
            padding-bottom: 6px;
            border-bottom: 1px solid #E2E8F0;
        }
        /* KPI metric cards */
        .kpi-card {
            background-color: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-top: 4px solid #2B5B84;
            border-radius: 6px;
            padding: 13px 16px;
            height: 100%;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        .kpi-label {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #475569;
            margin-bottom: 4px;
        }
        .kpi-value {
            font-size: 1.5rem;
            font-weight: 700;
            color: #0F172A;
            line-height: 1.2;
        }
        .kpi-sub {
            font-size: 0.76rem;
            color: #64748B;
            margin-top: 5px;
        }
        .sev-badge {
            display: inline-block;
            padding: 2px 8px;
            font-size: 0.74rem;
            font-weight: 600;
            border-radius: 4px;
            border: 1px solid #CBD5E1;
        }
        .method-badge {
            display: inline-block;
            padding: 2px 7px;
            font-family: Consolas, "Courier New", monospace;
            font-size: 0.75rem;
            font-weight: 600;
            background-color: #E0F2FE;
            color: #0369A1;
            border: 1px solid #BAE6FD;
            border-radius: 4px;
        }
        /* Side-by-side comparison boxes with subtle semantic color tints */
        .diff-box {
            background-color: #F8FAFC;
            border: 1px solid #CBD5E1;
            border-radius: 5px;
            padding: 10px 12px;
            font-size: 0.85rem;
            color: #1E293B;
        }
        .diff-box-expected {
            background-color: #F0FDF4;
            border: 1px solid #BBF7D0;
            border-left: 4px solid #16A34A;
            border-radius: 5px;
            padding: 10px 12px;
            font-size: 0.85rem;
            color: #14532D;
        }
        .diff-box-actual {
            background-color: #FFFBEB;
            border: 1px solid #FDE68A;
            border-left: 4px solid #D97706;
            border-radius: 5px;
            padding: 10px 12px;
            font-size: 0.85rem;
            color: #78350F;
        }
        .diff-label {
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            color: #475569;
            margin-bottom: 4px;
        }
        /* Tabs styling */
        button[data-baseweb="tab"] {
            font-weight: 600 !important;
            color: #475569 !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: #1E3A5F !important;
        }
        div.stButton > button[kind="primary"] {
            background-color: #2B5B84;
            border-color: #2B5B84;
            color: #FFFFFF;
            border-radius: 5px;
            font-weight: 500;
        }
        div.stButton > button[kind="primary"]:hover {
            background-color: #1E4263;
            border-color: #1E4263;
        }
        div.stButton > button[kind="secondary"] {
            background-color: #FFFFFF;
            border-color: #94A3B8;
            color: #1E293B;
            border-radius: 5px;
            font-weight: 500;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="auditor-header">
            <p class="auditor-title">{escape(title)}</p>
            <p class="auditor-subtitle">{escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_card(label: str, value: str, subtext: str = "", accent_color: str = "#2B5B84") -> None:
    st.markdown(
        f"""
        <div class="kpi-card" style="border-top-color: {accent_color};">
            <div class="kpi-label">{escape(label)}</div>
            <div class="kpi-value">{escape(value)}</div>
            <div class="kpi-sub">{escape(subtext)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def severity_badge_html(severity: str) -> str:
    fg, bg, border = SEVERITY_COLORS.get(severity, ("#334155", "#F1F5F9", "#CBD5E1"))
    return (
        f'<span class="sev-badge" style="color:{fg};background:{bg};border-color:{border};">'
        f"{escape(severity)}</span>"
    )


def build_severity_chart(severity_counts: dict[str, int]) -> go.Figure:
    order = ["Critical", "High", "Medium", "Low", "Informational"]
    labels = [s for s in order if s in severity_counts]
    values = [int(severity_counts.get(s, 0)) for s in labels]
    bar_colors = [SEVERITY_BAR_COLORS.get(s, "#2B5B84") for s in labels]

    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker_color=bar_colors,
                text=values,
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="Findings by Severity", font=dict(size=13, color="#0F172A")),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFC",
        font=dict(color="#1E293B", size=11),
        margin=dict(l=24, r=16, t=40, b=28),
        height=260,
        yaxis=dict(gridcolor="#E2E8F0", zerolinecolor="#CBD5E1", dtick=1 if max(values or [1]) <= 6 else None),
        xaxis=dict(linecolor="#CBD5E1"),
    )
    return fig


def build_category_chart(category_counts: dict[str, int]) -> go.Figure:
    items = [(k, int(v)) for k, v in category_counts.items() if int(v) > 0]
    if not items:
        items = [("No issues", 0)]
    items.sort(key=lambda pair: pair[1])
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    colors = [CATEGORY_PALETTE[idx % len(CATEGORY_PALETTE)] for idx in range(len(labels))]

    fig = go.Figure(
        data=[
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                marker_color=colors,
                text=values,
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="Findings by Validation Category", font=dict(size=13, color="#0F172A")),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFC",
        font=dict(color="#1E293B", size=11),
        margin=dict(l=120, r=28, t=40, b=28),
        height=260,
        xaxis=dict(gridcolor="#E2E8F0", zerolinecolor="#CBD5E1"),
        yaxis=dict(linecolor="#CBD5E1"),
    )
    return fig


def build_score_breakdown_chart(score_breakdown: list[dict[str, Any]]) -> go.Figure:
    names = [c["name"] for c in score_breakdown if c.get("weight", 0) > 0]
    scores = [round(float(c["score"]) * 100, 1) for c in score_breakdown if c.get("weight", 0) > 0]
    bar_colors = [
        "#0F766E" if s >= 85 else ("#2B5B84" if s >= 70 else "#D97706")
        for s in scores
    ]

    fig = go.Figure(
        data=[
            go.Bar(
                x=scores,
                y=names,
                orientation="h",
                marker_color=bar_colors,
                text=[f"{s:.1f}%" for s in scores],
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="Completeness Score by Dimension (%)", font=dict(size=13, color="#0F172A")),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFC",
        font=dict(color="#1E293B", size=11),
        margin=dict(l=175, r=42, t=40, b=28),
        height=250,
        xaxis=dict(range=[0, 112], gridcolor="#E2E8F0", zerolinecolor="#CBD5E1"),
        yaxis=dict(linecolor="#CBD5E1"),
    )
    return fig
