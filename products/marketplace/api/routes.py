import json
import os
import sqlite3
from decimal import Decimal

sellers = {}
buyers = {}
users = {}
sessions = {}
mfa_challenges = {}
items = {}
sales = {}
orders = {}
returns = {}
subscriptions = {}
navigation_sessions = {}
wallets = {}
recommendations = {}
payments = {}
shipments = {}
seller_reviews = {}
notifications = {}
antifraud_events = {}
checkout_events = {}
rollback_points = {}
smoke_results = {}

seller_seq = 1
buyer_seq = 1
user_seq = 1
session_seq = 1
mfa_seq = 1
item_seq = 1
sale_seq = 1
order_seq = 1
return_seq = 1
payment_seq = 1
shipment_seq = 1
notification_seq = 1
antifraud_seq = 1
checkout_event_seq = 1
rollback_seq = 1

payment_gateways = {
    "partner_a": {"enabled": True, "mode": "sandbox", "healthy": True},
    "partner_b": {"enabled": True, "mode": "sandbox", "healthy": True},
}

carrier_rates = {
    "carrier_a": {"enabled": True, "mode": "sandbox", "healthy": True, "base_rate": Decimal("8.50"), "eta_days": 3},
    "carrier_b": {"enabled": True, "mode": "sandbox", "healthy": True, "base_rate": Decimal("7.25"), "eta_days": 5},
}

notification_providers = {
    "email": {"enabled": True, "mode": "sandbox", "healthy": True},
    "webhook": {"enabled": True, "mode": "sandbox", "healthy": True},
}

launch_environments = {
    "staging": {"deployed": True, "healthy": True},
    "production": {"deployed": False, "healthy": False},
}

launch_security = {
    "mfa_required": True,
    "mfa_for_sellers": True,
    "mfa_for_finance": True,
}

launch_finance = {
    "invoice_enabled": False,
    "payouts_enabled": False,
    "repasse_cycle_days": 7,
}

ZERO = Decimal("0.00")
DB_PATH = os.environ.get("MARKETPLACE_DB_PATH", "marketplace_state.sqlite3")

STATE_NAMES = [
    "sellers",
    "buyers",
    "users",
    "sessions",
    "mfa_challenges",
    "items",
    "sales",
    "orders",
    "returns",
    "subscriptions",
    "navigation_sessions",
    "wallets",
    "recommendations",
    "payments",
    "shipments",
    "seller_reviews",
    "notifications",
    "antifraud_events",
    "checkout_events",
    "rollback_points",
    "smoke_results",
    "payment_gateways",
    "carrier_rates",
    "notification_providers",
    "launch_environments",
    "launch_security",
    "launch_finance",
]

COUNTER_NAMES = [
    "seller_seq",
    "buyer_seq",
    "user_seq",
    "session_seq",
    "mfa_seq",
    "item_seq",
    "sale_seq",
    "order_seq",
    "return_seq",
    "payment_seq",
    "shipment_seq",
    "notification_seq",
    "antifraud_seq",
    "checkout_event_seq",
    "rollback_seq",
]


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def next_item_id():
    global item_seq
    value = item_seq
    item_seq += 1
    return value


def _encode(value):
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, dict):
        return {"__dict__": [[_encode(key), _encode(val)] for key, val in value.items()]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    return value


def _decode(value):
    if isinstance(value, dict) and set(value.keys()) == {"__decimal__"}:
        return Decimal(value["__decimal__"])
    if isinstance(value, dict) and set(value.keys()) == {"__dict__"}:
        return {_decode(key): _decode(val) for key, val in value["__dict__"]}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_state (name TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )


def save_state():
    init_db()
    with _connect() as conn:
        for name in STATE_NAMES:
            conn.execute(
                "INSERT OR REPLACE INTO app_state (name, payload) VALUES (?, ?)",
                (name, json.dumps(_encode(globals()[name]), sort_keys=True)),
            )
        counters = {name: globals()[name] for name in COUNTER_NAMES}
        conn.execute(
            "INSERT OR REPLACE INTO app_state (name, payload) VALUES (?, ?)",
            ("__counters__", json.dumps(_encode(counters), sort_keys=True)),
        )


def load_state():
    init_db()
    with _connect() as conn:
        rows = dict(conn.execute("SELECT name, payload FROM app_state").fetchall())
    if not rows:
        return False
    for name in STATE_NAMES:
        if name in rows:
            globals()[name].clear()
            globals()[name].update(_decode(json.loads(rows[name])))
    if "__counters__" in rows:
        counters = _decode(json.loads(rows["__counters__"]))
        for name in COUNTER_NAMES:
            if name in counters:
                globals()[name] = counters[name]
    return True
