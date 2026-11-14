import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tempfile  # noqa: E402

os.environ["DEMO_MODE"] = "replay"          # tests never touch the network
os.environ["PAKKA_FAKE_NOW"] = "2026-11-14T09:30:00+05:30"
os.environ["PAKKA_DB"] = str(Path(tempfile.mkdtemp()) / "events_sink.db")   # never write to the real demo DB

from core import db, ledger  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.init_schema(c)
    ledger.add_shop(c, "S1", "Test Kirana")
    ledger.add_shop(c, "S2", "Other Shop")
    yield c
    c.close()


def pay(conn, txn_id, amount_paise, shop_id="S1", name="RAMESH K", vpa="9849012345@ybl",
        ts="2026-11-14T09:00:00+05:30", status="SUCCESS", app="PhonePe"):
    p = {"txn_id": txn_id, "shop_id": shop_id, "payer_vpa": vpa, "payer_name": name,
         "amount_paise": amount_paise, "app": app, "status": status, "ts": ts}
    ledger.record_payment(conn, p)
    return p
