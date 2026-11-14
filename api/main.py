"""PakkaKhata integration API (plan 12c). A thin wrapper: every endpoint only calls core/ (service layer).

Events in, cards out. It never moves money and never changes Paytm's own records; ledger changes happen only
after the shopkeeper taps. Every endpoint is scoped to one merchant (mid).

Run:  uvicorn api.main:app --port 8000      (no --reload for the demo)   ->  docs at http://localhost:8000/docs
Auth: X-Shop-Key per merchant (demo stand-in for Paytm's merchant login); X-Admin-Key for admin routes.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

import config  # noqa: E402
from core import cards, db, ledger, learning, service  # noqa: E402
from core.i18n import LANGS  # noqa: E402

MID_RE = r"^[A-Za-z0-9_\-]{2,32}$"
ID_RE = r"^[A-Za-z0-9_\-:.]{3,64}$"

app = FastAPI(title="PakkaKhata API", version="1.0.0",
              description="Plug-in service for the Business Khata tab: payment and khata events in, cards out. "
                          "Synthetic demo data; not connected to real Paytm systems.")
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["X-Shop-Key", "X-Admin-Key", "Content-Type"])


# ------------------------------------------------------------------ middleware: security headers + rate limit
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def guard(request: Request, call_next):
    key = request.headers.get("X-Shop-Key") or request.headers.get("X-Admin-Key") or (request.client.host if request.client else "?")
    if request.url.path.startswith("/v1/"):
        now = time.monotonic()
        q = _hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= config.RATE_LIMIT_PER_MIN:
            return JSONResponse({"detail": "rate limit: 30 requests per minute"}, status_code=429,
                                headers={"Retry-After": str(int(60 - (now - q[0])) + 1)})
        q.append(now)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# ------------------------------------------------------------------ auth
def merchant_auth(mid: str, key: str | None) -> None:
    if mid not in config.ENABLED_MERCHANTS:
        raise HTTPException(403, "PakkaKhata is not enabled for this merchant (pilot list only)")
    expected = config.SHOP_KEYS.get(mid)
    if not expected or key != expected:
        raise HTTPException(401, "missing or wrong X-Shop-Key for this merchant")


def admin_auth(x_admin_key: str | None = Header(default=None)) -> None:
    if x_admin_key != config.ADMIN_KEY:
        raise HTTPException(401, "admin key required")


def conn_dep():
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


# ------------------------------------------------------------------ request models (validated, size-limited)
class PaymentEvent(BaseModel):
    txn_id: str = Field(pattern=ID_RE)
    mid: str = Field(pattern=MID_RE)
    payer_vpa: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._\-]*@?[A-Za-z0-9]*$")
    payer_name: str = Field(default="", max_length=config.MAX_NAME_LEN)
    amount_paise: int = Field(gt=0, le=config.MAX_AMOUNT_PAISE)
    app: str = Field(default="UPI", max_length=30)
    status: Literal["SUCCESS", "FAILED", "PENDING", "REFUNDED"] = "SUCCESS"
    ts: datetime

    @field_validator("payer_name")
    @classmethod
    def _clean(cls, v: str) -> str:
        return "".join(ch for ch in v if ch.isprintable())


class KhataEvent(BaseModel):
    entry_id: str = Field(pattern=ID_RE)
    mid: str = Field(pattern=MID_RE)
    customer_ref: str = Field(pattern=r"^[A-Za-z0-9_\-]{1,40}$")
    khata_name: str = Field(min_length=1, max_length=config.MAX_NAME_LEN)
    type: Literal["udhaar", "repayment"]
    amount_paise: int = Field(gt=0, le=config.MAX_AMOUNT_PAISE)
    ts: datetime


class Decision(BaseModel):
    card_id: str = Field(pattern=r"^(pay|trust):[A-Za-z0-9_\-:.]{3,64}$")
    action: Literal["clear_full", "clear_part", "purchase", "not_him", "offer_yes", "offer_no"]
    amount_paise: int | None = Field(default=None, gt=0, le=config.MAX_AMOUNT_PAISE)
    customer_id: str | None = Field(default=None, pattern=ID_RE)
    extra: Literal["advance", "purchase"] | None = None


# ------------------------------------------------------------------ endpoints
@app.get("/health")
def health():
    return {"status": "ok", "demo_mode": config.DEMO_MODE, "warnings": config.STARTUP_WARNINGS[:3],
            "synthetic_data": True}


@app.post("/v1/events/payment")
def payment_event(e: PaymentEvent, x_shop_key: str | None = Header(default=None)):
    merchant_auth(e.mid, x_shop_key)
    p = {"txn_id": e.txn_id, "shop_id": e.mid, "payer_vpa": e.payer_vpa, "payer_name": e.payer_name,
         "amount_paise": e.amount_paise, "app": e.app, "status": e.status, "ts": e.ts.isoformat()}
    out = service.ingest_payment(p)
    return {"status": out["status"], "card": cards.public(out["card"]) if out.get("card") and out["status"] == "card_pending" else None}


@app.post("/v1/events/khata")
def khata_event(e: KhataEvent, x_shop_key: str | None = Header(default=None), conn=Depends(conn_dep)):
    merchant_auth(e.mid, x_shop_key)
    try:
        return service.ingest_khata(conn, {**e.model_dump(), "ts": e.ts.isoformat()})
    except ledger.LedgerError as ex:
        raise HTTPException(422, str(ex)) from ex


@app.get("/v1/merchants/{mid}/cards")
def get_cards(mid: str = PathParam(pattern=MID_RE), lang: str = Query(default="en", pattern="^(en|hi|te)$"),
              x_shop_key: str | None = Header(default=None), conn=Depends(conn_dep)):
    merchant_auth(mid, x_shop_key)
    items = service.get_public_cards(conn, mid, lang if lang in LANGS else "en")
    body = {"mid": mid, "lang": lang, "cards": items}
    body["bytes"] = len(json.dumps(body, ensure_ascii=False).encode())
    return body


@app.post("/v1/merchants/{mid}/decisions")
def post_decision(d: Decision, mid: str = PathParam(pattern=MID_RE), x_shop_key: str | None = Header(default=None),
                  conn=Depends(conn_dep)):
    merchant_auth(mid, x_shop_key)
    try:
        return service.decide(conn, mid, d.card_id, d.model_dump(exclude_none=True))
    except KeyError as ex:
        raise HTTPException(404, str(ex).strip("'")) from ex
    except (ValueError, ledger.LedgerError) as ex:
        raise HTTPException(422, str(ex)) from ex


@app.post("/v1/admin/reset", dependencies=[Depends(admin_auth)])
def admin_reset():
    service.reset_demo()
    return {"status": "reset to seeded demo state"}


@app.post("/v1/admin/retrain", dependencies=[Depends(admin_auth)])
def admin_retrain():
    r = learning.retrain_next()
    return {"before": r["before"], "after": r["after"], "labels": "repayment outcomes only"}


@app.exception_handler(Exception)
async def friendly_errors(request: Request, exc: Exception):   # never leak a traceback
    return JSONResponse({"detail": "internal error"}, status_code=500)


