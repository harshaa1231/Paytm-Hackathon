"""PakkaKhata service: integration API (plan 12c) + the bundled web app.

Events in, cards out. It never moves money and never changes Paytm's own records; ledger changes happen only
after the shopkeeper taps. Every endpoint is scoped to one merchant (mid). Every endpoint only calls core/.

  /v1/events/*, /v1/merchants/*   the integration contract (X-Shop-Key per merchant)
  /v1/admin/*                     reset / retrain (X-Admin-Key)
  /v1/demo/*                      demo console + "under the hood" inspection for judges (DEMO_ROUTES=true only)
  /                               the React web app (web/dist), same origin

Run:  uvicorn api.main:app --port 8000      ->  app http://localhost:8000   docs http://localhost:8000/docs
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

os.environ.setdefault("PAKKA_FAKE_NOW", config.DEMO_NOW)   # the seeded demo lives on "demo morning"

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

from core import cards, db, graph, learning, ledger, recommend, service  # noqa: E402
from core.i18n import LANGS, coverage  # noqa: E402
from core.privacy import mask_vpa  # noqa: E402
from core.timeutil import now_iso  # noqa: E402
from facts import FACTS, SYNTHETIC_FOOTER  # noqa: E402

MID_RE = r"^[A-Za-z0-9_\-]{2,32}$"
ID_RE = r"^[A-Za-z0-9_\-:.]{3,64}$"

app = FastAPI(title="PakkaKhata API", version="1.0.0",
              description="Plug-in service for the Business Khata tab: payment and khata events in, cards out. "
                          "Synthetic demo data; not connected to real Paytm systems.")
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["X-Shop-Key", "X-Admin-Key", "Content-Type"])


# ------------------------------------------------------------------ middleware: rate limit + security headers
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/v1/"):
        demo = path.startswith("/v1/demo/")
        limit = config.DEMO_RATE_LIMIT_PER_MIN if demo else config.RATE_LIMIT_PER_MIN
        who = request.headers.get("X-Shop-Key") or request.headers.get("X-Admin-Key") or (request.client.host if request.client else "?")
        key = ("demo:" if demo else "") + who
        now = time.monotonic()
        q = _hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"detail": f"rate limit: {limit} requests per minute"}, status_code=429,
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


def demo_only() -> None:
    if not config.DEMO_ROUTES:
        raise HTTPException(404, "demo routes are disabled")


def demo_admin(x_admin_key: str | None = Header(default=None)) -> None:
    demo_only()
    if not config.DEMO_OPEN_ADMIN and x_admin_key != config.ADMIN_KEY:
        raise HTTPException(401, "admin key required")


def demo_shop(mid: str) -> None:
    demo_only()
    if mid not in config.ENABLED_MERCHANTS:
        raise HTTPException(403, "not enabled for this merchant")


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


class UndoReq(BaseModel):
    txn_id: str = Field(pattern=ID_RE)


# ------------------------------------------------------------------ integration contract
@app.get("/health")
def health():
    return {"status": "ok", "demo_mode": config.DEMO_MODE, "warnings": config.STARTUP_WARNINGS[:3], "synthetic_data": True}


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


# ------------------------------------------------------------------ demo console + inspection (judges)
def _report(name: str) -> dict | None:
    try:
        return json.loads((config.REPORTS_DIR / name).read_text())
    except Exception:
        return None


@app.get("/v1/demo/config", dependencies=[Depends(demo_only)])
def demo_config(conn=Depends(conn_dep)):
    shops = [dict(r) for r in conn.execute("SELECT id, name, shop_type FROM shops ORDER BY id")
             if r["id"] in config.ENABLED_MERCHANTS]
    return {"shops": shops, "demo_mode": config.DEMO_MODE, "warnings": config.STARTUP_WARNINGS,
            "shop_keys": {s["id"]: config.SHOP_KEYS.get(s["id"]) for s in shops},   # demo only: prod uses merchant login
            "open_admin": config.DEMO_OPEN_ADMIN, "footer": SYNTHETIC_FOOTER, "demo_now": now_iso(),
            "langs": {k: {"name": v, "reviewed": coverage(k)[0], "total": coverage(k)[1]} for k, v in LANGS.items()}}


@app.get("/v1/demo/i18n", dependencies=[Depends(demo_only)])
def demo_i18n(lang: str = Query(default="en", pattern="^(en|hi|te)$")):
    """Shopkeeper-facing UI strings from app/i18n.json (unreviewed keys fall back to English)."""
    from core.i18n import _strings
    s = _strings()
    return {**s["en"], **s.get(lang, {})}


def _undo_candidate(conn, mid: str) -> dict | None:
    for r in conn.execute("SELECT txn_id, decision_json, payload_json FROM cards WHERE shop_id=? AND type='who_paid' "
                          "AND status='decided' ORDER BY decided_at DESC LIMIT 5", (mid,)):
        d = json.loads(r["decision_json"] or "{}")
        if d.get("action") in ("clear_full", "clear_part") and ledger.net_applied(conn, r["txn_id"]) > 0:
            return {"txn_id": r["txn_id"], "title": json.loads(r["payload_json"])["title"]}
    return None


@app.get("/v1/demo/{mid}/state")
def demo_state(mid: str = PathParam(pattern=MID_RE), conn=Depends(conn_dep)):
    demo_shop(mid)
    nxt = conn.execute("SELECT label FROM demo_queue WHERE shop_id=? AND ingested=0 ORDER BY seq LIMIT 1", (mid,)).fetchone()
    return {**service.shop_summary(conn, mid), "queue_left": service.demo_queue_left(conn, mid),
            "next_label": nxt["label"] if nxt else None, "undo": _undo_candidate(conn, mid)}


@app.post("/v1/demo/{mid}/simulate")
def demo_simulate(mid: str = PathParam(pattern=MID_RE), lang: str = Query(default="en", pattern="^(en|hi|te)$"),
                  conn=Depends(conn_dep)):
    demo_shop(mid)
    r = service.next_demo_payment(conn, mid, lang)
    if r is None:
        raise HTTPException(409, "demo queue finished; reset the demo to replay it")
    p = r["payment"]
    return {"label": r["label"], "status": r["status"], "match_stage": (r.get("match") or {}).get("stage"),
            "payment": {"txn_id": p["txn_id"], "payer_name": p.get("payer_name"), "payer_vpa": mask_vpa(p.get("payer_vpa")),
                        "amount_paise": p["amount_paise"], "app": p.get("app"), "status": p.get("status", "SUCCESS")},
            "card": cards.public(r["card"]) if r.get("card") and r["status"] == "card_pending" else None}


@app.get("/v1/demo/{mid}/today")
def demo_today(mid: str = PathParam(pattern=MID_RE), conn=Depends(conn_dep)):
    """Today's QR payments for the app's Home and Payments screens (read-only)."""
    demo_shop(mid)
    day = now_iso()[:10]
    rows = conn.execute("SELECT * FROM payments WHERE shop_id=? AND substr(ts,1,10)=? ORDER BY ts DESC", (mid, day)).fetchall()
    out, total = [], 0
    for r in rows:
        card = cards.get_card(conn, mid, f"pay:{r['txn_id']}")
        applied = ledger.net_applied(conn, r["txn_id"])
        if r["status"] != "SUCCESS":
            status = "failed"
        elif card and card["status"] == "pending":
            status = "needs_tap"
        elif applied > 0:
            status = "udhaar_cleared"
        else:
            status = "purchase"
        if r["status"] == "SUCCESS":
            total += r["amount_paise"]
        out.append({"txn_id": r["txn_id"], "payer_name": r["payer_name"], "payer_vpa": mask_vpa(r["payer_vpa"]),
                    "amount_paise": r["amount_paise"], "app": r["app"], "ts": r["ts"], "status": status, "applied_paise": applied,
                    "card_title": card["title"] if card else None})
    return {"date": day, "total_paise": total, "count": sum(1 for p in out if p["status"] != "failed"), "payments": out}


@app.get("/v1/demo/{mid}/khata")
def demo_khata(mid: str = PathParam(pattern=MID_RE), conn=Depends(conn_dep)):
    """Customers with open udhaar for the Business Khata screen (read-only)."""
    demo_shop(mid)
    now = now_iso()
    out = []
    for cid, us in ledger.customers_with_open_udhaar(conn, mid).items():
        c = ledger.get_customer(conn, mid, cid)
        oldest = min(u["given_at"] for u in us)
        out.append({"customer_id": cid, "name": c["khata_name"], "owed_paise": sum(u["remaining_paise"] for u in us),
                    "since_days": max(0, int((datetime.fromisoformat(now) - datetime.fromisoformat(oldest)).days))})
    out.sort(key=lambda x: -x["owed_paise"])
    return {"customers": out, "total_paise": sum(x["owed_paise"] for x in out)}


@app.post("/v1/demo/{mid}/undo")
def demo_undo(body: UndoReq, mid: str = PathParam(pattern=MID_RE), conn=Depends(conn_dep)):
    demo_shop(mid)
    try:
        return ledger.undo_payment(conn, mid, body.txn_id)
    except ledger.LedgerError as ex:
        raise HTTPException(404, str(ex)) from ex


@app.get("/v1/demo/{mid}/payments")
def demo_payments(mid: str = PathParam(pattern=MID_RE), conn=Depends(conn_dep)):
    demo_shop(mid)
    out, seen = [], set()
    for e in db.recent_events(conn, mid, 500):
        if e["type"] in ("match", "payment_duplicate", "payment_ignored"):
            p = e["payload"]
            key = (p.get("txn_id"), e["type"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"txn_id": p.get("txn_id"), "kind": e["type"], "stage": p.get("stage"), "payer_name": p.get("payer_name"),
                        "amount_paise": p.get("amount_paise"), "ts": e["ts"], "reason": p.get("reason")})
    return {"payments": out}


@app.get("/v1/demo/{mid}/trace/{txn_id}")
def demo_trace(mid: str = PathParam(pattern=MID_RE), txn_id: str = PathParam(pattern=ID_RE), conn=Depends(conn_dep)):
    demo_shop(mid)
    match = next((e["payload"] for e in db.recent_events(conn, mid, 500) if e["type"] == "match" and e["payload"].get("txn_id") == txn_id), None)
    pay = ledger.get_payment(conn, mid, txn_id)
    if not pay:
        raise HTTPException(404, "unknown payment for this shop")
    pay = {**pay, "payer_vpa": mask_vpa(pay.get("payer_vpa"))}
    card = cards.get_card(conn, mid, f"pay:{txn_id}")
    proposed = ledger.get_customer(conn, mid, match["customer_id"]) if match and match.get("customer_id") else None
    st = graph.get_flow().state(mid, txn_id)
    return {"payment": pay, "match": match, "proposed_khata_name": proposed["khata_name"] if proposed else None,
            "card": card, "graph": {"next": st["next"], "trace": st["values"].get("trace") or []},
            "thresholds": {"confident": config.MATCH_CONFIDENT_SCORE, "margin": config.MATCH_MARGIN, "min": config.MATCH_MIN_SCORE}}


@app.get("/v1/demo/{mid}/internals")
def demo_internals(mid: str = PathParam(pattern=MID_RE), conn=Depends(conn_dep)):
    demo_shop(mid)
    recs = recommend.hidden_regulars(conn, mid, now_iso())
    for it in recs["items"]:
        it["payer_vpa"] = mask_vpa(it["payer_vpa"])
    fc = service.forecast_card(conn, mid)
    return {"hidden_regulars": recs, "forecast": fc.get("forecast"), "forecast_judge": fc.get("judge"),
            "rule": {"min_payments_90d": config.HIDDEN_REGULAR_MIN_PAYMENTS_90D, "max_recency_days": config.HIDDEN_REGULAR_MAX_RECENCY_DAYS,
                     "top_k": config.HIDDEN_REGULAR_TOP_K},
            "mc": {"draws": config.MC_DRAWS, "shock_sd": config.MC_SHOCK_SD}}


@app.get("/v1/demo/{mid}/events")
def demo_events(mid: str = PathParam(pattern=MID_RE), limit: int = Query(default=60, ge=1, le=300), conn=Depends(conn_dep)):
    demo_shop(mid)
    return {"events": db.recent_events(conn, mid, limit)}


@app.get("/v1/demo/reports", dependencies=[Depends(demo_only)])
def demo_reports():
    return {"trust": _report("metrics.json"), "forecast": _report("forecast_metrics.json"), "bias": _report("bias_experiment.json"),
            "sweep": _report("bias_sweep.json"), "matcher_replay": _report("learning_matcher.json"),
            "learning_state": learning.load_state(), "real_retail": _report("real_retail_metrics.json"),
            "fairness_external": _report("fairness_external.json"), "matcher_metrics": _report("matcher_metrics.json"),
            "facts": FACTS, "trust_target_precision": config.TRUST_TARGET_PRECISION}


@app.post("/v1/demo/reset", dependencies=[Depends(demo_admin)])
def demo_reset():
    service.reset_demo()
    return {"status": "reset to seeded demo state"}


@app.post("/v1/demo/retrain", dependencies=[Depends(demo_admin)])
def demo_retrain():
    r = learning.retrain_next()
    return {"before": r["before"], "after": r["after"], "history": learning.load_state().get("history", []),
            "labels": "repayment outcomes only (never the shopkeeper's yes/no)"}


@app.exception_handler(Exception)
async def friendly_errors(request: Request, exc: Exception):   # never leak a traceback
    return JSONResponse({"detail": "internal error"}, status_code=500)


# ------------------------------------------------------------------ web app (same origin), mounted last
if config.WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(config.WEB_DIST), html=True), name="web")
