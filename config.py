"""Central configuration: paths, model IDs, thresholds, ladder, seeds, security.

Secrets come from .env (never committed). Synthetic-world parameters that are shaped on the
study cite the facts.py key they come from.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------- paths
DB_PATH = Path(os.getenv("PAKKA_DB", str(ROOT / "data" / "pakkakhata.db")))
DB_SEED_PATH = ROOT / "data" / "pakkakhata_seed.db"      # copy taken right after generate.py (Reset demo)
TRAIN_DB_PATH = ROOT / "data" / "train_world.db"          # 200 synthetic training shops (regenerated, not committed)
MODELS_DIR = ROOT / "models"
MODELS_SEED_DIR = ROOT / "models" / "seed"                # model state right after generate.py (Reset demo)
REPORTS_DIR = ROOT / "reports"
CACHE_PATH = ROOT / "cache" / "llm_cache.json"
I18N_PATH = ROOT / "app" / "i18n.json"

# ---------------------------------------------------------------- time + seeds
SEED = 42
TZ_OFFSET = "+05:30"                      # all timestamps are IST
DEMO_NOW = "2026-11-14T09:30:00+05:30"    # "demo morning" in the seeded world
DEMO_SHOP_ID = "S001"                     # Suresh Kirana
DEMO_SHOP2_ID = "S002"                    # Sri Sai Medicals (shows it works for any small shop)

# ---------------------------------------------------------------- LLM
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_MODEL_HINT = "flash"               # actual Gemini ID is resolved at runtime from client.models.list()
LLM_TIMEOUT_S = 8
LLM_RETRY_AFTER_MAX_S = 5
LLM_MAX_PROMPT_TOKENS = 1500              # Groq free tier: 8K tokens/min is the binding limit
REPHRASE_WITH_LLM = os.getenv("REPHRASE_WITH_LLM", "true").lower() == "true"

STARTUP_WARNINGS: list[str] = []
_mode = os.getenv("DEMO_MODE", "replay").strip().lower()
if _mode not in {"live", "record", "replay"}:
    STARTUP_WARNINGS.append(f"DEMO_MODE={_mode!r} is not live|record|replay; using replay.")
    _mode = "replay"
if _mode in {"live", "record"} and not (GROQ_API_KEY or GEMINI_API_KEY):
    STARTUP_WARNINGS.append(f"DEMO_MODE={_mode} but no GROQ_API_KEY or GEMINI_API_KEY in .env; using replay (cache + rules).")
    _mode = "replay"
DEMO_MODE = _mode

# ---------------------------------------------------------------- matcher
VPA_MEMORY_CONFIDENCE = 0.99
MATCH_CONFIDENT_SCORE = 90
MATCH_MARGIN = 10
MATCH_MIN_SCORE = 60
AMOUNT_BONUS = 5                 # payment equals one open udhaar exactly
INITIAL_MATCH_BONUS = 5          # "RAMESH K" vs "Ramesh K. Rao"
INITIAL_CONFLICT_PENALTY = 15    # "RAMESH K" vs "Ramesh Gupta"
MAX_LLM_CANDIDATES = 5
MAX_FEWSHOT_EXAMPLES = 6

# ---------------------------------------------------------------- trust model + recommendations
ONTIME_DAYS = 14                          # label: repaid within 14 days of being given
HIDDEN_REGULAR_MIN_PAYMENTS_90D = 12
HIDDEN_REGULAR_MAX_RECENCY_DAYS = 14
HIDDEN_REGULAR_TOP_K = 3
MIN_SHOP_HISTORY_DAYS = 28                # "Need about 4 weeks of payments to suggest anyone."
TRUST_TARGET_PRECISION = 0.90             # threshold picked on validation shops for ~90% precision
TRUST_THRESHOLD_DEFAULT = 0.80            # used only if models/trust_meta.json is missing
DECLINE_SNOOZE_DAYS = 30                  # after a "No", don't suggest the same customer again for 30 days


def trust_threshold() -> float:
    """Threshold chosen on validation shops at training time (models/trust_meta.json)."""
    try:
        return float(json.loads((MODELS_DIR / "trust_meta.json").read_text())["threshold"])
    except Exception:
        return TRUST_THRESHOLD_DEFAULT


# ---------------------------------------------------------------- starter credit ladder (our design choice)
LADDER_STEPS_PAISE = [10_000, 20_000, 40_000, 70_000, 100_000]   # ₹100 → ₹200 → ₹400 → ₹700 → ₹1,000 cap
LADDER_UP_AFTER_ONTIME = 3
LADDER_LATE_DAYS = 7                      # repaid > 7 days past due -> drop one step
LADDER_FREEZE_DAYS = 30                   # unpaid at 30 days -> freeze

# ---------------------------------------------------------------- forecast
FORECAST_HORIZON_DAYS = 7
MC_DRAWS = 2000
MC_SHOCK_SD = 0.5        # shared weekly shock on the logit scale (bad week / festival moves everyone together)
FORECAST_FEW_ENTRIES = 3

# ---------------------------------------------------------------- synthetic training world (data/generate.py)
WORLD = dict(
    n_shops=200,
    test_shops=40,               # held out by shop (leakage control)
    cust_min=40, cust_max=120,
    beta_a=4.0, beta_b=2.0,      # latent reliability r ~ Beta(a, b)
    in_group_share=0.5,
    offer_percentile=0.82,       # shopkeeper's credit threshold near the 82nd percentile (study)
    offer_p_eligible=0.55,       # P(offer | above threshold, out-group)
    in_group_mult=1.42,          # facts: in_group_favouritism (+42%)
    offer_p_below=0.01,
    explore_share=0.15,          # exploration arm: random ₹100 starter offers (facts: random_borrowers)
    explore_amount_paise=10_000,
    ticket_median_rupees=220,
    ingroup_ticket_mult=1.3,     # PROXY: in-group buys slightly bigger baskets. Unrelated to repayment. See README.
    shock_sd=0.4,                # per shop-week repayment shock (everyone delays together)
    history_days=180,
    world_start="2026-03-01T00:00:00+05:30",
)

# ---------------------------------------------------------------- judge
JUDGE_BLOCKLIST = [
    # sensitive personal attributes / slurs must never appear on a card
    "caste", "religion", "hindu", "muslim", "christian", "sikh", "jain", "dalit", "brahmin",
    "tribal", "gender", "pregnant", "disabled", "lazy", "cheat", "fraud", "thief", "chor",
    "untrustworthy", "liar", "poor", "illiterate", "beggar",
    # compliance wording: PakkaKhata records the shop's own udhaar; it never lends or offers credit
    "loan", "loans", "lend", "lends", "lending", "lender", "credit line", "offer credit",
]

# ---------------------------------------------------------------- API security
ENABLED_MERCHANTS = {"S001", "S002"}      # feature flag: pilot list only
try:
    SHOP_KEYS: dict[str, str] = json.loads(os.getenv("SHOP_KEYS", "") or "{}")
except json.JSONDecodeError:
    SHOP_KEYS = {}
    STARTUP_WARNINGS.append("SHOP_KEYS in .env is not valid JSON; API shop auth will reject everything.")
if not SHOP_KEYS:
    SHOP_KEYS = {"S001": "dev-s001", "S002": "dev-s002"}
    STARTUP_WARNINGS.append("SHOP_KEYS not set; using dev keys (dev-s001 / dev-s002). Set them in .env.")
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip() or "dev-admin"
ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]   # Vite dev server; prod is same-origin
RATE_LIMIT_PER_MIN = 60                   # per key on /v1/events + /v1/merchants (also protects the Groq free quota)
DEMO_RATE_LIMIT_PER_MIN = 600             # demo console routes (/v1/demo/*)
# Demo console: exposes the dev shop keys to the bundled web UI and inspection routes for judges.
# Turn OFF for anything real (production would use Paytm's merchant login).
DEMO_ROUTES = os.getenv("DEMO_ROUTES", "true").lower() == "true"
DEMO_OPEN_ADMIN = os.getenv("DEMO_OPEN_ADMIN", "true").lower() == "true"   # false -> reset/retrain need X-Admin-Key
WEB_DIST = ROOT / "web" / "dist"
MAX_AMOUNT_PAISE = 10_000_000             # ₹1,00,000 per event: anything larger is rejected
MAX_NAME_LEN = 80
