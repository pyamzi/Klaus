"""The two legal pages; the text lives in templates.py, the operator's details in Settings."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from . import templates

router = APIRouter()


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request) -> str:
    s = request.app.state.settings
    return templates.terms(s.operator_name or "Klaus", s.operator_email, s.operator_country or "the operator's country of residence")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request) -> str:
    s = request.app.state.settings
    return templates.privacy(s.operator_name or "Klaus", s.operator_email)
