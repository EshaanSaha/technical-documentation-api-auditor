"""HTTP client used by the Streamlit frontend to communicate with FastAPI."""

from __future__ import annotations

import json
from typing import Any, Optional

import requests

from app.core.config import settings


class BackendClientError(RuntimeError):
    """User-facing error returned by or while contacting the FastAPI backend."""


def _base_url() -> str:
    return settings.api_url.rstrip("/")


def _handle_response(resp: requests.Response) -> Any:
    if resp.status_code >= 400:
        try:
            payload = resp.json()
            detail = payload.get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise BackendClientError(str(detail))
    return resp.json()


def get_health() -> Optional[dict[str, Any]]:
    try:
        resp = requests.get(f"{_base_url()}/api/health", timeout=4)
        return _handle_response(resp)
    except requests.RequestException:
        return None


def preview_parse(file_bytes: bytes, filename: str, role: str) -> dict[str, Any]:
    try:
        resp = requests.post(
            f"{_base_url()}/api/parse-preview",
            files={"file": (filename, file_bytes)},
            data={"role": role},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def run_validation_upload(
    doc_bytes: bytes,
    doc_filename: str,
    spec_bytes: bytes,
    spec_filename: str,
    session_name: str = "",
    thresholds: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    data: dict[str, str] = {}
    if session_name:
        data["session_name"] = session_name
    if thresholds:
        data["thresholds_json"] = json.dumps(thresholds)
    try:
        resp = requests.post(
            f"{_base_url()}/api/validate",
            files={
                "documentation": (doc_filename, doc_bytes),
                "specification": (spec_filename, spec_bytes),
            },
            data=data,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def run_sample_validation(
    doc_variant: str = "shopwave_api_docs.md",
    spec_variant: str = "shopwave_openapi.yaml",
    session_name: Optional[str] = None,
    thresholds: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "doc_variant": doc_variant,
        "spec_variant": spec_variant,
    }
    if session_name:
        payload["session_name"] = session_name
    if thresholds:
        payload["thresholds"] = thresholds
    try:
        resp = requests.post(f"{_base_url()}/api/validate/sample", json=payload, timeout=90)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def fetch_sessions(limit: int = 100) -> list[dict[str, Any]]:
    try:
        resp = requests.get(f"{_base_url()}/api/sessions", params={"limit": limit}, timeout=10)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def fetch_session_detail(session_id: str) -> dict[str, Any]:
    try:
        resp = requests.get(f"{_base_url()}/api/sessions/{session_id}", timeout=15)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def remove_session(session_id: str) -> dict[str, Any]:
    try:
        resp = requests.delete(f"{_base_url()}/api/sessions/{session_id}", timeout=10)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def download_report(session_id: str, fmt: str) -> tuple[bytes, str]:
    try:
        resp = requests.get(f"{_base_url()}/api/reports/{session_id}/{fmt}", timeout=30)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    if resp.status_code >= 400:
        _handle_response(resp)
    disposition = resp.headers.get("Content-Disposition", "")
    filename = f"audit_report_{session_id}.{fmt}"
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].strip('"')
    return resp.content, filename


def fetch_reports(session_id: Optional[str] = None) -> list[dict[str, Any]]:
    params = {"session_id": session_id} if session_id else {}
    try:
        resp = requests.get(f"{_base_url()}/api/reports", params=params, timeout=10)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def fetch_thresholds() -> dict[str, float]:
    try:
        resp = requests.get(f"{_base_url()}/api/settings/thresholds", timeout=8)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def update_thresholds(thresholds: dict[str, float]) -> dict[str, float]:
    try:
        resp = requests.put(f"{_base_url()}/api/settings/thresholds", json=thresholds, timeout=8)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)


def reset_thresholds() -> dict[str, float]:
    try:
        resp = requests.post(f"{_base_url()}/api/settings/thresholds/reset", timeout=8)
    except requests.RequestException as exc:
        raise BackendClientError(f"Could not reach FastAPI backend at {_base_url()}: {exc}") from exc
    return _handle_response(resp)

