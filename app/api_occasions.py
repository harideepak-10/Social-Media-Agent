"""JSON API: approve festivals / special days / AI suggestions, remembered rules, special days, event pause."""
from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, occasions

router = APIRouter(prefix="/api")
User = Depends(auth.require_user)


@router.get("/occasions")
def list_occasions(days: int = 60, start: str | None = None, _: str = User):
    s = date.fromisoformat(start) if start else date.today()
    items = occasions.occasions_between(s, s + timedelta(days=min(max(days, 1), 400)))
    return {"items": [occasions.as_dict(o) for o in items], "default_timing": occasions.default_timing()}


@router.get("/occasions/pending")
def pending(days: int = 7, _: str = User):
    return {"items": [occasions.as_dict(o) for o in occasions.pending_soon(days)]}


class DecideIn(BaseModel):
    key: str
    status: str                      # approved | skipped | clear
    timing: int | None = Field(None, ge=0, le=3)
    note: str | None = Field(None, max_length=500)


@router.post("/occasions/decide")
def decide(body: DecideIn, _: str = User):
    if body.status not in ("approved", "skipped", "clear") or "|" not in body.key:
        raise HTTPException(400, "status must be approved, skipped or clear")
    occasions.decide(body.key, body.status, body.timing, body.note)
    return {"ok": True}


class RuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    rule: str                        # always | never | ask
    timing: int | None = Field(None, ge=0, le=3)
    note: str | None = Field(None, max_length=500)


@router.put("/occasions/rule")
def set_rule(body: RuleIn, _: str = User):
    if body.rule not in ("always", "never", "ask"):
        raise HTTPException(400, "rule must be always, never or ask")
    occasions.set_rule(body.name, body.rule, body.timing, body.note)
    return {"ok": True}


@router.post("/occasions/suggest")
def suggest(_: str = User):
    try:
        return {"added": occasions.suggest_with_ai(90)}
    except Exception as e:
        raise HTTPException(502, f"AI suggestion failed: {e}")


class SuggestionIn(BaseModel):
    status: str                      # accepted | dismissed | pending


@router.post("/occasions/suggestions/{sid}")
def suggestion(sid: int, body: SuggestionIn, _: str = User):
    if body.status not in ("accepted", "dismissed", "pending"):
        raise HTTPException(400, "status must be accepted, dismissed or pending")
    occasions.suggestion_status(sid, body.status)
    return {"ok": True}


class SpecialDayIn(BaseModel):
    date: str                        # MM-DD (every year)
    name: str = Field(min_length=2, max_length=120)


@router.post("/special-days")
def add_special(body: SpecialDayIn, _: str = User):
    if not re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", body.date):
        raise HTTPException(400, "date must be MM-DD")
    occasions.add_special_day(body.date, body.name.strip())
    return {"ok": True}


@router.delete("/special-days/{mmdd}")
def remove_special(mmdd: str, _: str = User):
    occasions.remove_special_day(mmdd)
    return {"ok": True}


class PauseIn(BaseModel):
    paused: bool


@router.post("/events/{event_id}/pause")
def pause_event(event_id: int, body: PauseIn, _: str = User):
    try:
        occasions.set_event_paused(event_id, body.paused)
    except KeyError:
        raise HTTPException(404, "Event not found")
    return {"ok": True}
