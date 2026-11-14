"""LangGraph payment workflow with a human-in-the-loop pause (plan P1 step 4).

ingest_payment -> find_candidates -> build_card -> judge_card -> ask_shopkeeper (interrupt) -> apply_decision -> learn

- compiled with InMemorySaver; one thread per payment (thread_id = "<shop>:<txn_id>")
- ask_shopkeeper calls interrupt(card). It has NO side effects, because on resume LangGraph re-runs
  that node from its start. All ledger writes happen in apply_decision, after resume.
- resuming twice never writes twice: the card is marked decided and the ledger is idempotent on txn_id.
- if the process restarted (InMemorySaver lost the paused thread), decide() replays the flow up to the
  interrupt and then resumes it.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import config
from core import cards, db, judge, ledger, matcher
from core.timeutil import normalize_ts, now_iso

ACTIONS = {"clear_full", "clear_part", "purchase", "not_him"}


class PayState(TypedDict, total=False):
    payment: dict
    lang: str
    recover: bool
    status: str
    match: dict
    card: dict
    facts: dict
    decision: dict
    result: dict
    trace: list


def _trace(state: PayState, node: str, t0: float, **extra) -> list:
    return (state.get("trace") or []) + [{"node": node, "ms": int((time.perf_counter() - t0) * 1000), **extra}]


class PaymentFlow:
    def __init__(self, db_path=None, mode: str | None = None):
        self.db_path = db_path
        self.mode = mode
        self.saver = InMemorySaver()
        self.graph = self._build().compile(checkpointer=self.saver)

    def _conn(self):
        return db.connect(self.db_path)

    # ------------------------------------------------------------------ nodes
    def ingest_payment(self, state: PayState) -> dict:
        t0 = time.perf_counter()
        p = dict(state["payment"])
        p["ts"] = normalize_ts(p["ts"])
        p["status"] = (p.get("status") or "SUCCESS").upper()
        conn = self._conn()
        try:
            new = ledger.record_payment(conn, p)
            log = ledger.payment_summary_for_log(p)
            if not new and not state.get("recover"):
                db.log_event(conn, "payment_duplicate", log, p["shop_id"])
                return {"status": "duplicate", "payment": p, "trace": _trace(state, "ingest_payment", t0, result="duplicate")}
            if p["status"] != "SUCCESS":
                db.log_event(conn, "payment_ignored", {**log, "reason": p["status"]}, p["shop_id"])
                return {"status": "ignored", "payment": p, "trace": _trace(state, "ingest_payment", t0, result=f"ignored {p['status']}")}
            db.log_event(conn, "payment_ingested", log, p["shop_id"])
            return {"status": "ingested", "payment": p, "trace": _trace(state, "ingest_payment", t0, result="new")}
        finally:
            conn.close()

    def find_candidates(self, state: PayState) -> dict:
        t0 = time.perf_counter()
        p = state["payment"]
        conn = self._conn()
        try:
            m = matcher.find_candidates(conn, p["shop_id"], p, mode=self.mode)
            purchase = m["stage"] in ("no_open_udhaar", "no_match") or (not m.get("customer_id") and not m.get("candidates"))
            status = "purchase_no_card" if purchase else "matched"
            db.log_event(conn, "match", {"txn_id": p["txn_id"], "stage": m["stage"], "customer_id": m.get("customer_id"),
                                         "confidence": m.get("confidence"), "reason": m.get("reason"),
                                         "payer_name": p.get("payer_name"), "payer_norm": m.get("payer_norm"),
                                         "candidates": m.get("candidates"), "few_shot": m.get("few_shot"),
                                         "llm": m.get("llm")}, p["shop_id"])
            return {"match": m, "status": status,
                    "trace": _trace(state, "find_candidates", t0, result=m["stage"])}
        finally:
            conn.close()

    def build_card(self, state: PayState) -> dict:
        t0 = time.perf_counter()
        p = state["payment"]
        conn = self._conn()
        try:
            card, facts = cards.build_who_paid(conn, p["shop_id"], p, state["match"], state.get("lang", "en"))
            return {"card": card, "facts": facts, "trace": _trace(state, "build_card", t0)}
        finally:
            conn.close()

    def judge_card(self, state: PayState) -> dict:
        t0 = time.perf_counter()
        p = state["payment"]
        card, facts = dict(state["card"]), state["facts"]
        conn = self._conn()
        try:
            title_check = judge.stage1(card["title"], facts, conn)
            verdict = judge.judge_card(card["body"], facts, conn=conn, try_rephrase=(card.get("lang", "en") == "en"),
                                       shop_id=p["shop_id"], mode=self.mode)
            card["template_body"] = card["body"]
            card["body"] = verdict["text"]
            card["judge"] = {**verdict, "title_stage1": title_check}
            cards.save_card(conn, card, p["shop_id"], now_iso())
            db.log_event(conn, "card_created", {"card_id": card["card_id"], "title": card["title"], "body": card["body"],
                                                "judge": card["judge"]}, p["shop_id"])
            return {"card": card, "status": "card_pending",
                    "trace": _trace(state, "judge_card", t0, result=verdict["source"])}
        finally:
            conn.close()

    def ask_shopkeeper(self, state: PayState) -> dict:
        # NO side effects before interrupt(): this node re-runs from the top on resume.
        decision = interrupt(cards.public(state["card"]))
        return {"decision": decision, "trace": (state.get("trace") or []) + [{"node": "ask_shopkeeper", "ms": 0, "result": "resumed"}]}

    def apply_decision(self, state: PayState) -> dict:
        t0 = time.perf_counter()
        p, card = state["payment"], state["card"]
        shop = p["shop_id"]
        d = dict(state.get("decision") or {})
        action = d.get("action")
        conn = self._conn()
        try:
            stored = cards.get_card(conn, shop, card["card_id"])
            if stored and stored["status"] != "pending":
                return {"status": "already_decided", "result": {"status": "already_decided", "decision": stored["decision"]},
                        "trace": _trace(state, "apply_decision", t0, result="already decided")}
            try:
                res = self._apply(conn, p, card, d)
            except (ValueError, ledger.LedgerError) as e:
                db.log_event(conn, "decision_rejected", {"card_id": card["card_id"], "error": str(e)}, shop)
                return {"status": "rejected", "result": {"status": "rejected", "error": str(e)},
                        "trace": _trace(state, "apply_decision", t0, result="rejected")}
            decided = {k: v for k, v in d.items() if k in ("action", "amount_paise", "customer_id", "extra")}
            cards.mark_decided(conn, shop, card["card_id"], decided, now_iso())
            db.log_event(conn, "decision", {"card_id": card["card_id"], **res}, shop)
            return {"status": "done", "result": res, "trace": _trace(state, "apply_decision", t0, result=action)}
        finally:
            conn.close()

    @staticmethod
    def _apply(conn, p: dict, card: dict, d: dict) -> dict:
        shop, action = p["shop_id"], d.get("action")
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        res: dict[str, Any] = {"action": action, "txn_id": p["txn_id"]}
        if action in ("clear_full", "clear_part"):
            cid = d.get("customer_id") or card.get("customer_id")
            if not cid or not ledger.get_customer(conn, shop, cid):
                raise ValueError("customer not in this shop")
            open_amt = ledger.open_total(conn, shop, cid, as_of=p["ts"])
            cap = min(p["amount_paise"], open_amt)
            if cap <= 0:
                raise ValueError("this customer has no open udhaar for this payment")
            amt = cap if action == "clear_full" else int(d.get("amount_paise") or p["amount_paise"])
            if not (0 < amt <= cap):
                raise ValueError(f"amount must be between 1 paisa and {cap} paise")
            r = ledger.apply_payment(conn, shop, cid, p["txn_id"], amt)
            leftover = p["amount_paise"] - r.get("applied", 0)
            if d.get("extra") == "advance" and leftover > 0 and r["status"] == "applied":
                ledger.record_advance(conn, shop, cid, p["txn_id"], leftover)
            res.update(customer_id=cid, applied_paise=r.get("applied", 0), leftover_paise=leftover,
                       extra=d.get("extra"), ledger_status=r["status"], left_owed_paise=ledger.open_total(conn, shop, cid))
        return res

    def learn(self, state: PayState) -> dict:
        """Matcher memory only. NOTHING here touches trust-model labels."""
        t0 = time.perf_counter()
        p, res, m = state["payment"], state.get("result") or {}, state.get("match") or {}
        if state.get("status") != "done":
            return {"trace": _trace(state, "learn", t0, result="skipped")}
        shop, action = p["shop_id"], res.get("action")
        proposed = m.get("customer_id")
        learned = []
        conn = self._conn()
        try:
            if action in ("clear_full", "clear_part") and res.get("customer_id"):
                cid = res["customer_id"]
                khata = ledger.get_customer(conn, shop, cid)["khata_name"]
                if p.get("payer_vpa"):
                    conn.execute("INSERT OR REPLACE INTO vpa_map(shop_id,payer_vpa,customer_id,confirmed_at) VALUES (?,?,?,?)",
                                 (shop, p["payer_vpa"], cid, now_iso()))
                    learned.append("vpa_map")
                if p.get("payer_name"):
                    conn.execute("INSERT INTO match_examples(shop_id,payer_name,khata_name,label,created_at) VALUES (?,?,?,?,?)",
                                 (shop, p["payer_name"], khata, "match", now_iso()))
                    learned.append("match_example")
                if proposed and proposed != cid and p.get("payer_name"):
                    wrong = ledger.get_customer(conn, shop, proposed)["khata_name"]
                    conn.execute("INSERT INTO match_examples(shop_id,payer_name,khata_name,label,created_at) VALUES (?,?,?,?,?)",
                                 (shop, p["payer_name"], wrong, "not_match", now_iso()))
                    learned.append("not_match_example")
            elif action == "not_him" and proposed and p.get("payer_name"):
                wrong = ledger.get_customer(conn, shop, proposed)["khata_name"]
                conn.execute("INSERT INTO match_examples(shop_id,payer_name,khata_name,label,created_at) VALUES (?,?,?,?,?)",
                             (shop, p["payer_name"], wrong, "not_match", now_iso()))
                learned.append("not_match_example")
            conn.commit()
            if learned:
                db.log_event(conn, "learned", {"txn_id": p["txn_id"], "what": learned}, shop)
            return {"trace": _trace(state, "learn", t0, result=",".join(learned) or "nothing")}
        finally:
            conn.close()

    # ------------------------------------------------------------------ wiring
    def _build(self) -> StateGraph:
        g = StateGraph(PayState)
        for name in ("ingest_payment", "find_candidates", "build_card", "judge_card", "ask_shopkeeper", "apply_decision", "learn"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "ingest_payment")
        g.add_conditional_edges("ingest_payment", lambda s: "find_candidates" if s["status"] == "ingested" else END,
                                ["find_candidates", END])
        g.add_conditional_edges("find_candidates", lambda s: "build_card" if s["status"] == "matched" else END,
                                ["build_card", END])
        g.add_edge("build_card", "judge_card")
        g.add_edge("judge_card", "ask_shopkeeper")
        g.add_edge("ask_shopkeeper", "apply_decision")
        g.add_edge("apply_decision", "learn")
        g.add_edge("learn", END)
        return g

    @staticmethod
    def thread(shop_id: str, txn_id: str) -> dict:
        return {"configurable": {"thread_id": f"{shop_id}:{txn_id}"}}

    # ------------------------------------------------------------------ public API
    def ingest(self, payment: dict, lang: str = "en") -> dict:
        """Run a payment event through the graph. Returns {"status", "card"?, "match"?, "trace"}."""
        conn = self._conn()
        try:
            seen = conn.execute("SELECT 1 FROM payments WHERE shop_id=? AND txn_id=?",
                                (payment["shop_id"], payment["txn_id"])).fetchone()
        finally:
            conn.close()
        cfg = self.thread(payment["shop_id"], payment["txn_id"])
        if seen:   # duplicate event: record it on a throwaway thread, never disturb the paused original
            cfg = {"configurable": {"thread_id": f"{payment['shop_id']}:{payment['txn_id']}:dup:{uuid.uuid4().hex[:6]}"}}
        out = self.graph.invoke({"payment": payment, "lang": lang, "trace": []}, cfg)
        status = "card_pending" if out.get("__interrupt__") else out.get("status")
        return {"status": status, "card": out.get("card"), "match": out.get("match"), "trace": out.get("trace"),
                "payment": out.get("payment")}

    def state(self, shop_id: str, txn_id: str) -> dict:
        snap = self.graph.get_state(self.thread(shop_id, txn_id))
        return {"next": list(snap.next or []), "values": snap.values or {}}

    def decide(self, shop_id: str, txn_id: str, decision: dict) -> dict:
        conn = self._conn()
        try:
            card = cards.get_card(conn, shop_id, f"pay:{txn_id}")
            if not card:
                raise KeyError("no card for this payment in this shop")
            if card["status"] != "pending":
                return {"status": "already_decided", "decision": card["decision"]}
            pay = ledger.get_payment(conn, shop_id, txn_id)
        finally:
            conn.close()
        cfg = self.thread(shop_id, txn_id)
        snap = self.graph.get_state(cfg)
        if "ask_shopkeeper" not in (snap.next or ()):
            # paused thread was lost (restart): replay up to the interrupt, then resume
            self.graph.invoke({"payment": pay, "lang": card.get("lang", "en"), "recover": True, "trace": []}, cfg)
        out = self.graph.invoke(Command(resume=decision), cfg)
        return {"status": out.get("status"), "result": out.get("result"), "trace": out.get("trace")}


_flows: dict[str, PaymentFlow] = {}


def get_flow(db_path=None) -> PaymentFlow:
    key = str(db_path or config.DB_PATH)
    if key not in _flows:
        _flows[key] = PaymentFlow(db_path)
    return _flows[key]


def reset_flows() -> None:
    _flows.clear()
