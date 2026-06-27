from contextlib import asynccontextmanager
from decimal import Decimal
import hashlib
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import routes


@asynccontextmanager
async def lifespan(app):
    routes.load_state()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8011",
        "http://localhost:8011",
        "http://127.0.0.1:8020",
        "http://localhost:8020",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _first_seller():
    if routes.sellers:
        return next(iter(routes.sellers.values()))
    seller_id = "Seller123"
    seller = {
        "id": seller_id,
        "name": "Default Seller",
        "email": "seller@example.com",
        "ads_contracted": False,
        "balance": _money("0.00"),
    }
    routes.sellers[seller_id] = seller
    return seller


def _first_buyer():
    if routes.buyers:
        return next(iter(routes.buyers.values()))
    buyer_id = "Buyer123"
    buyer = {
        "id": buyer_id,
        "name": "Default Buyer",
        "email": "buyer@example.com",
        "is_prime_member": False,
        "wallet_balance": _money("0.00"),
    }
    routes.buyers[buyer_id] = buyer
    routes.wallets[buyer_id] = _money("0.00")
    return buyer


def _ensure_wallet(buyer_id):
    if buyer_id not in routes.wallets:
        routes.wallets[buyer_id] = _money("0.00")


def _hash_password(password):
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def _role_requires_mfa(role):
    _ensure_launch_defaults()
    return (
        routes.launch_security.get("mfa_required", True)
        and (
            role == "admin"
            or (role == "seller" and routes.launch_security.get("mfa_for_sellers", True))
        )
    )


def _issue_session(user_id, mfa_verified=False):
    token = secrets.token_urlsafe(24)
    session_id = routes.session_seq
    routes.session_seq += 1
    routes.sessions[token] = {
        "id": session_id,
        "user_id": user_id,
        "role": routes.users[user_id]["role"],
        "mfa_verified": mfa_verified,
    }
    return token


def _session_from_header(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    session = routes.sessions.get(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    return session


def _require_role(authorization, roles):
    session = _session_from_header(authorization)
    if session["role"] not in roles:
        raise HTTPException(status_code=403, detail="Forbidden")
    if _role_requires_mfa(session["role"]) and not session.get("mfa_verified", False):
        raise HTTPException(status_code=403, detail="MFA required")
    return session


def _checkout_total(payload):
    if "total_amount" in payload:
        return _money(payload["total_amount"])
    items = payload.get("items", [])
    total = Decimal("0.00")
    for entry in items:
        item_id = entry.get("item_id")
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            pass
        quantity = int(entry.get("quantity", 1))
        item = routes.items.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        total += _money(item["price"]) * quantity
    return total.quantize(Decimal("0.01"))


def _resolve_checkout_buyer(payload):
    buyer_id = payload.get("buyer_id")
    buyer = routes.buyers.get(buyer_id)
    if buyer is None:
        buyer = _first_buyer()
        buyer_id = buyer["id"]
    _ensure_wallet(buyer_id)
    return buyer_id, buyer


def _ensure_payment_gateways():
    if not routes.payment_gateways:
        routes.payment_gateways.update({
            "partner_a": {"enabled": True, "mode": "sandbox", "healthy": True},
            "partner_b": {"enabled": True, "mode": "sandbox", "healthy": True},
        })


def _ensure_carriers():
    if not routes.carrier_rates:
        routes.carrier_rates.update({
            "carrier_a": {"enabled": True, "mode": "sandbox", "healthy": True, "base_rate": Decimal("8.50"), "eta_days": 3},
            "carrier_b": {"enabled": True, "mode": "sandbox", "healthy": True, "base_rate": Decimal("7.25"), "eta_days": 5},
        })


def _ensure_notifications():
    if not routes.notification_providers:
        routes.notification_providers.update({
            "email": {"enabled": True, "mode": "sandbox", "healthy": True},
            "webhook": {"enabled": True, "mode": "sandbox", "healthy": True},
        })


def _ensure_launch_defaults():
    if not routes.launch_environments:
        routes.launch_environments.update({
            "staging": {"deployed": True, "healthy": True},
            "production": {"deployed": False, "healthy": False},
        })
    if not routes.launch_security:
        routes.launch_security.update({
            "mfa_required": True,
            "mfa_for_sellers": True,
            "mfa_for_finance": True,
        })
    if not routes.launch_finance:
        routes.launch_finance.update({
            "invoice_enabled": False,
            "payouts_enabled": False,
            "repasse_cycle_days": 7,
        })


def _seller_items(seller_id):
    return [item for item in routes.items.values() if item.get("seller_id") == seller_id]


def _seller_sales(seller_id):
    return [sale for sale in routes.sales.values() if sale.get("seller_id") == seller_id]


def _seller_returns(seller_id):
    seller_order_ids = {order_id for order_id, order in routes.orders.items() if order.get("seller_id") == seller_id}
    return [ret for ret in routes.returns.values() if ret.get("order_id") in seller_order_ids]


def _seller_reputation_score(seller_id):
    reviews = routes.seller_reviews.get(seller_id, [])
    if not reviews:
        return 0.0
    avg_stars = sum(review["stars"] for review in reviews) / len(reviews)
    no_return_count = sum(1 for review in reviews if not review.get("returned", False))
    no_complaint_count = sum(1 for review in reviews if not review.get("complaint", False))
    no_return_pct = no_return_count / len(reviews)
    no_complaint_pct = no_complaint_count / len(reviews)
    return round((avg_stars * 20) * no_return_pct * no_complaint_pct, 2)


def _launch_ready():
    _ensure_launch_defaults()
    _ensure_payment_gateways()
    _ensure_carriers()
    _ensure_notifications()
    return (
        routes.launch_environments["staging"]["deployed"]
        and routes.launch_environments["staging"]["healthy"]
        and routes.launch_environments["production"]["deployed"]
        and routes.launch_environments["production"]["healthy"]
        and routes.launch_security["mfa_required"]
        and routes.launch_security["mfa_for_sellers"]
        and routes.launch_security["mfa_for_finance"]
        and routes.launch_finance["invoice_enabled"]
        and routes.launch_finance["payouts_enabled"]
        and any(provider.get("enabled") and provider.get("healthy") for provider in routes.payment_gateways.values())
        and sum(1 for carrier in routes.carrier_rates.values() if carrier.get("enabled") and carrier.get("healthy")) >= 2
        and any(provider.get("enabled") and provider.get("healthy") for provider in routes.notification_providers.values())
    )


def _normalize_category(category):
    if isinstance(category, list):
        parts = [str(part).strip() for part in category if str(part).strip()]
    else:
        parts = [part.strip() for part in str(category).split(">") if part.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="Category is required")
    if len(parts) > 3:
        raise HTTPException(status_code=400, detail="Category depth exceeds 3 levels")
    return parts


def _validate_item_payload(payload, partial=False):
    if not partial or "title" in payload:
        if not str(payload.get("title", "")).strip():
            raise HTTPException(status_code=400, detail="Title is required")
    if not partial or "description" in payload:
        if not str(payload.get("description", "")).strip():
            raise HTTPException(status_code=400, detail="Description is required")
    if not partial or "category" in payload:
        _normalize_category(payload.get("category", ""))
    if not partial or "photos" in payload:
        photos = payload.get("photos", [])
        if not isinstance(photos, list) or not (1 <= len(photos) <= 10):
            raise HTTPException(status_code=400, detail="Photos must contain between 1 and 10 images")
    if not partial or "price" in payload:
        if _money(payload.get("price", "0.00")) <= Decimal("0.00"):
            raise HTTPException(status_code=400, detail="Price must be greater than zero")
    if not partial or "stock" in payload:
        if int(payload.get("stock", -1)) < 0:
            raise HTTPException(status_code=400, detail="Stock must be non-negative")
    if not partial or "sku" in payload:
        if not str(payload.get("sku", "")).strip():
            raise HTTPException(status_code=400, detail="SKU is required")


@app.post("/auth/register", status_code=201)
async def register_user(payload: dict):
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "buyer")).strip().lower()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    if role not in {"buyer", "seller", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if any(user["email"] == email for user in routes.users.values()):
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = f"User{routes.user_seq}"
    routes.user_seq += 1
    routes.users[user_id] = {
        "id": user_id,
        "email": email,
        "password_hash": _hash_password(password),
        "role": role,
        "mfa_enabled": _role_requires_mfa(role),
    }
    return {"user_id": user_id, "email": email, "role": role, "mfa_enabled": routes.users[user_id]["mfa_enabled"]}


@app.post("/auth/login")
async def login_user(payload: dict):
    email = str(payload.get("email", "")).strip().lower()
    password_hash = _hash_password(payload.get("password", ""))
    user = next((item for item in routes.users.values() if item["email"] == email), None)
    if user is None or user["password_hash"] != password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if _role_requires_mfa(user["role"]):
        challenge_id = f"MFA{routes.mfa_seq}"
        routes.mfa_seq += 1
        routes.mfa_challenges[challenge_id] = {
            "user_id": user["id"],
            "code": "123456",
            "verified": False,
        }
        return {"mfa_required": True, "challenge_id": challenge_id}

    token = _issue_session(user["id"], mfa_verified=True)
    return {"mfa_required": False, "access_token": token, "role": user["role"]}


@app.post("/auth/mfa/verify")
async def verify_mfa(payload: dict):
    challenge_id = payload.get("challenge_id")
    code = str(payload.get("code", ""))
    challenge = routes.mfa_challenges.get(challenge_id)
    if challenge is None or challenge["code"] != code:
        raise HTTPException(status_code=401, detail="Invalid MFA code")
    challenge["verified"] = True
    token = _issue_session(challenge["user_id"], mfa_verified=True)
    user = routes.users[challenge["user_id"]]
    return {"access_token": token, "role": user["role"]}


@app.get("/auth/me")
async def auth_me(authorization: str | None = Header(default=None)):
    session = _session_from_header(authorization)
    user = routes.users[session["user_id"]]
    return {"user_id": user["id"], "email": user["email"], "role": user["role"], "mfa_verified": session["mfa_verified"]}


@app.get("/admin/summary")
async def admin_summary(authorization: str | None = Header(default=None)):
    session = _require_role(authorization, {"admin"})
    return {
        "admin_user_id": session["user_id"],
        "users": len(routes.users),
        "sellers": len(routes.sellers),
        "buyers": len(routes.buyers),
        "orders": len(routes.orders),
    }


@app.post("/sellers")
async def create_seller(payload: dict):
    seller_id = "Seller123" if routes.seller_seq == 1 else f"Seller{routes.seller_seq}"
    routes.seller_seq += 1
    seller = {
        "id": seller_id,
        "name": payload.get("name", "Seller"),
        "email": payload.get("email", f"{seller_id.lower()}@example.com"),
        "ads_contracted": bool(payload.get("ads_contracted", False)),
        "balance": _money("0.00"),
    }
    routes.sellers[seller_id] = seller
    return seller


@app.post("/buyers")
async def create_buyer(payload: dict):
    buyer_id = "Buyer123" if routes.buyer_seq == 1 else f"Buyer{routes.buyer_seq}"
    routes.buyer_seq += 1
    buyer = {
        "id": buyer_id,
        "name": payload.get("name", "Buyer"),
        "email": payload.get("email", f"{buyer_id.lower()}@example.com"),
        "is_prime_member": bool(payload.get("is_prime_member", False)),
        "wallet_balance": _money("0.00"),
    }
    routes.buyers[buyer_id] = buyer
    routes.wallets[buyer_id] = _money("0.00")
    return buyer


@app.post("/items", status_code=201)
async def create_item(payload: dict):
    _validate_item_payload(payload)
    seller = _first_seller()
    item_id = routes.next_item_id()
    item = {
        "id": item_id,
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),
        "category": _normalize_category(payload.get("category", "")),
        "photos": list(payload.get("photos", [])),
        "price": _money(payload.get("price", "0.00")),
        "stock": payload.get("stock", 0),
        "sku": payload.get("sku", ""),
        "seller_id": seller["id"],
        "active": True,
        "listing_fee": _money("0.00"),
    }
    routes.items[item_id] = item
    return item


@app.put("/items/{item_id}")
async def update_item(item_id: int, payload: dict):
    item = routes.items.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    _validate_item_payload(payload, partial=True)
    if "title" in payload:
        item["title"] = payload["title"]
    if "description" in payload:
        item["description"] = payload["description"]
    if "category" in payload:
        item["category"] = _normalize_category(payload["category"])
    if "photos" in payload:
        item["photos"] = list(payload["photos"])
    if "price" in payload:
        item["price"] = _money(payload["price"])
    if "stock" in payload:
        item["stock"] = int(payload["stock"])
    if "sku" in payload:
        item["sku"] = payload["sku"]
    return item


@app.post("/items/{item_id}/deactivate")
async def deactivate_item(item_id: int):
    item = routes.items.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    item["active"] = False
    return {"item_id": item_id, "active": False}


@app.post("/sales")
async def create_sale(payload: dict):
    item_id = payload.get("item_id")
    buyer_id = payload.get("buyer_id")
    if item_id not in routes.items:
        raise HTTPException(status_code=404, detail="Item not found")
    item = routes.items[item_id]
    buyer = routes.buyers.get(buyer_id) or _first_buyer()
    _ensure_wallet(buyer["id"])
    seller = routes.sellers.get(item["seller_id"])
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")

    sale_id = routes.sale_seq
    routes.sale_seq += 1
    amount = _money(item["price"])
    commission_rate = Decimal("0.08") if seller.get("ads_contracted") else Decimal("0.10")
    commission = (amount * commission_rate).quantize(Decimal("0.01"))
    net = (amount - commission).quantize(Decimal("0.01"))

    sale = {
        "id": sale_id,
        "item_id": item_id,
        "buyer_id": buyer["id"],
        "seller_id": seller["id"],
        "amount": amount,
        "commission": commission,
        "net_amount": net,
    }
    routes.sales[sale_id] = sale
    routes.orders[sale_id] = {
        "id": sale_id,
        "buyer_id": buyer["id"],
        "item_id": item_id,
        "seller_id": seller["id"],
        "total_amount": amount,
        "status": "paid",
        "created_via": "sale",
    }
    seller["balance"] = _money(seller.get("balance", Decimal("0.00")) + net)
    return sale


@app.post("/subscriptions")
async def create_subscription(payload: dict):
    buyer_id = payload.get("buyer_id")
    program = payload.get("program")
    buyer = routes.buyers.get(buyer_id)
    if buyer is None:
        buyer = _first_buyer()
        buyer_id = buyer["id"]
    buyer["is_prime_member"] = program == "Prime-like"
    routes.subscriptions[buyer_id] = {"buyer_id": buyer_id, "program": program}
    return {"buyer_id": buyer_id, "program": program}


@app.post("/orders")
async def create_order(payload: dict):
    buyer_id, buyer = _resolve_checkout_buyer(payload)

    order_id = routes.order_seq
    routes.order_seq += 1
    total_amount = _money(payload.get("total_amount", "0.00"))
    shipping_free = buyer.get("is_prime_member", False) and total_amount > Decimal("21.00")
    cashback = _money(total_amount * Decimal("0.01")) if buyer.get("is_prime_member", False) else _money("0.00")
    routes.wallets[buyer_id] = _money(routes.wallets[buyer_id] + cashback)

    order = {
        "id": order_id,
        "buyer_id": buyer_id,
        "items": payload.get("items", []),
        "total_amount": total_amount,
        "shipping_address": payload.get("shipping_address", ""),
        "shipping_free": shipping_free,
        "cashback": cashback,
        "status": "created",
    }
    routes.orders[order_id] = order
    return order


@app.post("/wallets/{buyer_id}/credit")
async def credit_wallet(buyer_id: str, payload: dict):
    _ensure_wallet(buyer_id)
    amount = _money(payload.get("amount", "0.00"))
    if amount <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")
    routes.wallets[buyer_id] = _money(routes.wallets[buyer_id] + amount)
    return {"buyer_id": buyer_id, "credited": f"{amount:.2f}", "balance": f"{routes.wallets[buyer_id]:.2f}"}


@app.post("/checkout")
async def checkout(payload: dict):
    buyer_id, buyer = _resolve_checkout_buyer(payload)
    total_amount = _checkout_total(payload)
    payment_method = payload.get("payment_method")
    risk_score = int(payload.get("risk_score", 10))

    if payment_method == "wallet":
        if routes.wallets[buyer_id] < total_amount:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")
        routes.wallets[buyer_id] = _money(routes.wallets[buyer_id] - total_amount)
        gateway = "wallet"
        status = "approved"
    elif payment_method == "partner_card":
        _ensure_payment_gateways()
        gateway = payload.get("gateway")
        provider = routes.payment_gateways.get(gateway)
        if not provider or not provider.get("enabled") or not provider.get("healthy"):
            raise HTTPException(status_code=400, detail="Unsupported gateway")
        if risk_score >= 80:
            event_id = routes.antifraud_seq
            routes.antifraud_seq += 1
            routes.antifraud_events[event_id] = {
                "id": event_id,
                "buyer_id": buyer_id,
                "risk_score": risk_score,
                "status": "blocked",
            }
            event_id = routes.checkout_event_seq
            routes.checkout_event_seq += 1
            routes.checkout_events[event_id] = {
                "id": event_id,
                "buyer_id": buyer_id,
                "amount": total_amount,
                "payment_method": payment_method,
                "gateway": gateway,
                "status": "blocked",
                "risk_score": risk_score,
            }
            raise HTTPException(status_code=402, detail="Transaction blocked by antifraud")
        status = "approved"
    else:
        raise HTTPException(status_code=400, detail="Unsupported payment method")

    payment_id = routes.payment_seq
    routes.payment_seq += 1
    payment = {
        "id": payment_id,
        "buyer_id": buyer_id,
        "amount": total_amount,
        "payment_method": payment_method,
        "gateway": gateway,
        "status": status,
        "risk_score": risk_score,
    }
    routes.payments[payment_id] = payment
    order_id = routes.order_seq
    routes.order_seq += 1
    routes.orders[order_id] = {
        "id": order_id,
        "buyer_id": buyer_id,
        "items": payload.get("items", []),
        "total_amount": total_amount,
        "shipping_address": payload.get("shipping_address", ""),
        "status": "paid",
        "payment_id": payment_id,
    }
    event_id = routes.checkout_event_seq
    routes.checkout_event_seq += 1
    routes.checkout_events[event_id] = {
        "id": event_id,
        "buyer_id": buyer_id,
        "amount": total_amount,
        "payment_method": payment_method,
        "gateway": gateway,
        "status": status,
        "risk_score": risk_score,
    }
    return {"payment_id": payment_id, "order_id": order_id, "status": status, "gateway": gateway, "total_amount": f"{total_amount:.2f}"}


@app.post("/shipping/quote")
async def shipping_quote(payload: dict):
    _ensure_carriers()
    total_amount = _checkout_total(payload)
    quotes = []
    for carrier_name, meta in routes.carrier_rates.items():
        if not meta.get("enabled", False) or not meta.get("healthy", False):
            continue
        multiplier = Decimal("1.00")
        if total_amount > Decimal("100.00"):
            multiplier = Decimal("1.10")
        price = _money(meta["base_rate"] * multiplier)
        quotes.append({
            "carrier": carrier_name,
            "price": f"{price:.2f}",
            "eta_days": meta["eta_days"],
        })
    return {"quotes": quotes}


@app.post("/shipping/dispatch")
async def shipping_dispatch(payload: dict):
    _ensure_carriers()
    order_id = payload.get("order_id")
    order = routes.orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    carrier = payload.get("carrier")
    if carrier not in routes.carrier_rates or not routes.carrier_rates[carrier].get("enabled") or not routes.carrier_rates[carrier].get("healthy"):
        raise HTTPException(status_code=400, detail="Unsupported carrier")

    shipment_id = routes.shipment_seq
    routes.shipment_seq += 1
    tracking_code = f"TRK-{shipment_id:06d}"
    shipment = {
        "id": shipment_id,
        "order_id": order_id,
        "carrier": carrier,
        "tracking_code": tracking_code,
        "status": "scheduled",
    }
    routes.shipments[shipment_id] = shipment
    order["shipment_id"] = shipment_id
    order["tracking_code"] = tracking_code
    return shipment


@app.get("/shipments/{shipment_id}")
async def get_shipment(shipment_id: int):
    shipment = routes.shipments.get(shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


@app.get("/sellers/{seller_id}/central")
async def seller_central(seller_id: str):
    seller = routes.sellers.get(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    items = _seller_items(seller_id)
    sales = _seller_sales(seller_id)
    returns = _seller_returns(seller_id)
    commission_retained = sum((sale["commission"] for sale in sales), Decimal("0.00"))
    gross_revenue = sum((sale["amount"] for sale in sales), Decimal("0.00"))
    reputation_score = _seller_reputation_score(seller_id)
    active_items = sum(1 for item in items if item.get("active", False))
    paused_items = sum(1 for item in items if not item.get("active", False))
    return {
        "seller_id": seller_id,
        "active_items": active_items,
        "paused_items": paused_items,
        "impressions": active_items * 10 + len(sales) * 5,
        "clicks": active_items * 3 + len(sales) * 2,
        "conversions": len(sales),
        "sales_count": len(sales),
        "gross_revenue": f"{gross_revenue:.2f}",
        "commission_retained": f"{commission_retained:.2f}",
        "returns_count": len(returns),
        "reputation_score": f"{reputation_score:.2f}",
        "badges": ["starter-seller"] if len(sales) else [],
        "sales_ranking": max(1, 100 - len(sales) * 3),
    }


@app.post("/sellers/{seller_id}/reviews")
async def create_seller_review(seller_id: str, payload: dict):
    seller = routes.sellers.get(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    stars = int(payload.get("stars", 0))
    if stars < 1 or stars > 5:
        raise HTTPException(status_code=400, detail="Stars must be between 1 and 5")
    review = {
        "stars": stars,
        "returned": bool(payload.get("returned", False)),
        "complaint": bool(payload.get("complaint", False)),
    }
    routes.seller_reviews.setdefault(seller_id, []).append(review)
    return review


@app.get("/sellers/{seller_id}/reputation")
async def get_seller_reputation(seller_id: str):
    if seller_id not in routes.sellers:
        raise HTTPException(status_code=404, detail="Seller not found")
    reviews = routes.seller_reviews.get(seller_id, [])
    score = _seller_reputation_score(seller_id)
    if reviews:
        avg_stars = sum(review["stars"] for review in reviews) / len(reviews)
        no_return_pct = sum(1 for review in reviews if not review.get("returned", False)) / len(reviews)
        no_complaint_pct = sum(1 for review in reviews if not review.get("complaint", False)) / len(reviews)
    else:
        avg_stars = 0.0
        no_return_pct = 0.0
        no_complaint_pct = 0.0
    return {
        "seller_id": seller_id,
        "average_rating": f"{avg_stars:.2f}",
        "no_return_pct": f"{no_return_pct:.2f}",
        "no_complaint_pct": f"{no_complaint_pct:.2f}",
        "reputation_score": f"{score:.2f}",
    }


@app.post("/returns", status_code=201)
async def create_return(payload: dict):
    order_id = payload.get("order_id")
    order = routes.orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    return_id = routes.return_seq
    routes.return_seq += 1
    item = routes.items.get(order.get("item_id")) if order.get("item_id") else None
    seller = routes.sellers.get(order.get("seller_id")) if order.get("seller_id") else None
    buyer_id = order["buyer_id"]
    _ensure_wallet(buyer_id)

    net_refund = _money("0.00")
    if item is not None and seller is not None:
        commission_rate = Decimal("0.08") if seller.get("ads_contracted") else Decimal("0.10")
        commission = (_money(item["price"]) * commission_rate).quantize(Decimal("0.01"))
        net_refund = (_money(item["price"]) - commission).quantize(Decimal("0.01"))
    elif order.get("total_amount"):
        net_refund = (_money(order["total_amount"]) * Decimal("0.90")).quantize(Decimal("0.01"))

    routes.wallets[buyer_id] = _money(routes.wallets[buyer_id] + net_refund)
    ret = {
        "id": return_id,
        "order_id": order_id,
        "reason": payload.get("reason", ""),
        "refund_amount": net_refund,
        "status": "requested",
    }
    routes.returns[return_id] = ret
    return ret


@app.get("/returns/{return_id}")
async def get_return(return_id: int):
    ret = routes.returns.get(return_id)
    if ret is None:
        raise HTTPException(status_code=404, detail="Return not found")
    return ret


@app.post("/returns/{return_id}/process")
async def process_return(return_id: int):
    ret = routes.returns.get(return_id)
    if ret is None:
        raise HTTPException(status_code=404, detail="Return not found")
    ret["status"] = "processed"
    return {"return_id": return_id, "status": "processed", "refund_amount": f"{ret['refund_amount']:.2f}"}


@app.post("/navigation_sessions")
async def create_navigation_session(payload: dict):
    buyer_id = payload.get("buyer_id")
    routes.navigation_sessions.setdefault(buyer_id, []).append(payload)
    return {"buyer_id": buyer_id, "recorded": True}


@app.get("/buyers/{buyer_id}/wallet")
async def get_wallet(buyer_id: str):
    _ensure_wallet(buyer_id)
    return {"buyer_id": buyer_id, "balance": f"{routes.wallets[buyer_id]:.2f}"}


@app.get("/buyers/{buyer_id}/recommendations")
async def get_recommendations(buyer_id: str):
    sessions = routes.navigation_sessions.get(buyer_id, [])
    if sessions:
        products = [
            {
                "id": item_id,
                "title": item["title"],
                "price": f"{item['price']:.2f}",
            }
            for item_id, item in routes.items.items()
        ]
        if not products:
            products = [{"id": 1, "title": "Recommended Item", "price": "10.00"}]
        contents = [
            {"title": "Buying guide", "url": "/content/buying-guide"},
            {"title": "Top deals", "url": "/content/top-deals"},
        ]
    else:
        products = [{"id": 1, "title": "Recommended Item", "price": "10.00"}]
        contents = [{"title": "Starter guide", "url": "/content/starter-guide"}]

    routes.recommendations[buyer_id] = {"products": products, "contents": contents}
    return {"buyer_id": buyer_id, "products": products, "contents": contents}


@app.get("/sellers/{seller_id}/balance")
async def get_seller_balance(seller_id: str):
    seller = routes.sellers.get(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    return {"seller_id": seller_id, "seller_net": f"{seller.get('balance', Decimal('0.00')):.2f}"}


@app.get("/launch/readiness")
async def launch_readiness():
    _ensure_launch_defaults()
    return {
        "ready": _launch_ready(),
        "environments": routes.launch_environments,
        "security": routes.launch_security,
        "finance": routes.launch_finance,
    }


@app.post("/launch/environments/{environment}/deploy")
async def deploy_launch_environment(environment: str, payload: dict):
    _ensure_launch_defaults()
    if environment not in routes.launch_environments:
        raise HTTPException(status_code=404, detail="Environment not found")
    if "deployed" in payload:
        routes.launch_environments[environment]["deployed"] = bool(payload["deployed"])
    if "healthy" in payload:
        routes.launch_environments[environment]["healthy"] = bool(payload["healthy"])
    return {"environment": environment, **routes.launch_environments[environment]}


@app.post("/launch/security/mfa")
async def configure_launch_mfa(payload: dict):
    _ensure_launch_defaults()
    for key in ("mfa_required", "mfa_for_sellers", "mfa_for_finance"):
        if key in payload:
            routes.launch_security[key] = bool(payload[key])
    return routes.launch_security


@app.post("/launch/finance")
async def configure_launch_finance(payload: dict):
    _ensure_launch_defaults()
    for key in ("invoice_enabled", "payouts_enabled", "repasse_cycle_days"):
        if key in payload:
            routes.launch_finance[key] = bool(payload[key]) if key != "repasse_cycle_days" else int(payload[key])
    return routes.launch_finance


@app.get("/persistence/status")
async def persistence_status():
    routes.init_db()
    return {
        "db_path": routes.DB_PATH,
        "state_groups": len(routes.STATE_NAMES),
        "counter_groups": len(routes.COUNTER_NAMES),
    }


@app.post("/persistence/save")
async def persistence_save():
    routes.save_state()
    return {"saved": True, "db_path": routes.DB_PATH}


@app.post("/persistence/load")
async def persistence_load():
    loaded = routes.load_state()
    return {"loaded": loaded, "db_path": routes.DB_PATH}


@app.get("/integrations/status")
async def integrations_status():
    _ensure_payment_gateways()
    _ensure_carriers()
    _ensure_notifications()
    return {
        "payments": routes.payment_gateways,
        "carriers": routes.carrier_rates,
        "notifications": routes.notification_providers,
    }


@app.post("/integrations/payments/{provider}")
async def configure_payment_provider(provider: str, payload: dict):
    _ensure_payment_gateways()
    routes.payment_gateways.setdefault(provider, {"enabled": False, "mode": "sandbox", "healthy": False})
    for key in ("enabled", "healthy"):
        if key in payload:
            routes.payment_gateways[provider][key] = bool(payload[key])
    if "mode" in payload:
        routes.payment_gateways[provider]["mode"] = str(payload["mode"])
    return routes.payment_gateways[provider]


@app.post("/integrations/carriers/{carrier}")
async def configure_carrier(carrier: str, payload: dict):
    _ensure_carriers()
    routes.carrier_rates.setdefault(carrier, {
        "enabled": False,
        "mode": "sandbox",
        "healthy": False,
        "base_rate": Decimal("10.00"),
        "eta_days": 5,
    })
    for key in ("enabled", "healthy"):
        if key in payload:
            routes.carrier_rates[carrier][key] = bool(payload[key])
    if "mode" in payload:
        routes.carrier_rates[carrier]["mode"] = str(payload["mode"])
    if "base_rate" in payload:
        routes.carrier_rates[carrier]["base_rate"] = _money(payload["base_rate"])
    if "eta_days" in payload:
        routes.carrier_rates[carrier]["eta_days"] = int(payload["eta_days"])
    return routes.carrier_rates[carrier]


@app.post("/integrations/notifications/{provider}/test")
async def send_test_notification(provider: str, payload: dict):
    _ensure_notifications()
    meta = routes.notification_providers.get(provider)
    if not meta or not meta.get("enabled") or not meta.get("healthy"):
        raise HTTPException(status_code=400, detail="Unsupported notification provider")
    notification_id = routes.notification_seq
    routes.notification_seq += 1
    notification = {
        "id": notification_id,
        "provider": provider,
        "target": payload.get("target", "ops@example.com"),
        "status": "sent",
    }
    routes.notifications[notification_id] = notification
    return notification


@app.get("/ops/checkout/metrics")
async def checkout_metrics():
    events = list(routes.checkout_events.values())
    total = len(events)
    approved = sum(1 for event in events if event.get("status") == "approved")
    blocked = sum(1 for event in events if event.get("status") == "blocked")
    approval_rate = 0 if total == 0 else round(approved / total, 4)
    return {"total": total, "approved": approved, "blocked": blocked, "approval_rate": approval_rate}


@app.post("/ops/smoke")
async def run_smoke_test():
    _ensure_launch_defaults()
    _ensure_payment_gateways()
    _ensure_carriers()
    _ensure_notifications()
    checks = {
        "persistence": True,
        "payments": any(provider.get("enabled") and provider.get("healthy") for provider in routes.payment_gateways.values()),
        "carriers": sum(1 for carrier in routes.carrier_rates.values() if carrier.get("enabled") and carrier.get("healthy")) >= 2,
        "notifications": any(provider.get("enabled") and provider.get("healthy") for provider in routes.notification_providers.values()),
        "launch": _launch_ready(),
    }
    routes.smoke_results["last"] = checks
    return {"passed": all(checks.values()), "checks": checks}


@app.post("/ops/rollback/checkpoint")
async def create_rollback_checkpoint():
    checkpoint_id = f"RB{routes.rollback_seq}"
    routes.rollback_seq += 1
    snapshot = {
        "launch_environments": routes._encode(routes.launch_environments),
        "launch_finance": routes._encode(routes.launch_finance),
        "launch_security": routes._encode(routes.launch_security),
        "payment_gateways": routes._encode(routes.payment_gateways),
        "carrier_rates": routes._encode(routes.carrier_rates),
        "notification_providers": routes._encode(routes.notification_providers),
    }
    routes.rollback_points[checkpoint_id] = snapshot
    return {"checkpoint_id": checkpoint_id}


@app.post("/ops/rollback/{checkpoint_id}/restore")
async def restore_rollback_checkpoint(checkpoint_id: str):
    snapshot = routes.rollback_points.get(checkpoint_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Rollback checkpoint not found")
    for name, payload in snapshot.items():
        getattr(routes, name).clear()
        getattr(routes, name).update(routes._decode(payload))
    return {"restored": True, "checkpoint_id": checkpoint_id}


@app.post("/demo/investor-seed")
async def investor_demo_seed():
    _ensure_payment_gateways()
    _ensure_carriers()
    _ensure_notifications()
    _ensure_launch_defaults()

    seller = routes.sellers.get("Seller123") or {
        "id": "Seller123",
        "name": "Investor Demo Seller",
        "email": "seller@demo.local",
        "ads_contracted": True,
        "balance": _money("0.00"),
    }
    seller["ads_contracted"] = True
    routes.sellers["Seller123"] = seller

    buyer = routes.buyers.get("Buyer123") or {
        "id": "Buyer123",
        "name": "Investor Demo Buyer",
        "email": "buyer@demo.local",
        "is_prime_member": True,
        "wallet_balance": _money("0.00"),
    }
    buyer["is_prime_member"] = True
    routes.buyers["Buyer123"] = buyer
    routes.wallets["Buyer123"] = _money("500.00")

    item_id = routes.next_item_id()
    routes.items[item_id] = {
        "id": item_id,
        "title": "Demo Smart Camera",
        "description": "Produto demonstrativo para fluxo investidor",
        "category": ["Electronics", "Cameras"],
        "photos": ["demo-camera.jpg"],
        "price": _money("120.00"),
        "stock": 20,
        "sku": f"DEMO-CAM-{item_id}",
        "seller_id": "Seller123",
        "active": True,
        "listing_fee": _money("0.00"),
    }

    checkout_payload = {
        "buyer_id": "Buyer123",
        "payment_method": "partner_card",
        "gateway": "partner_a",
        "items": [{"item_id": item_id, "quantity": 1}],
        "shipping_address": "Demo Street 100",
        "risk_score": 12,
    }
    checkout_result = await checkout(checkout_payload)
    sale = await create_sale({"item_id": item_id, "buyer_id": "Buyer123"})
    dispatch = await shipping_dispatch({"order_id": checkout_result["order_id"], "carrier": "carrier_a"})
    review = await create_seller_review("Seller123", {"stars": 5, "returned": False, "complaint": False})

    await deploy_launch_environment("production", {"deployed": True, "healthy": True})
    await configure_launch_finance({"invoice_enabled": True, "payouts_enabled": True, "repasse_cycle_days": 3})
    await configure_launch_mfa({"mfa_required": True, "mfa_for_sellers": True, "mfa_for_finance": True})
    smoke = await run_smoke_test()
    routes.save_state()

    dashboard = await seller_central("Seller123")
    reputation = await get_seller_reputation("Seller123")
    readiness = await launch_readiness()
    return {
        "demo": "investor",
        "mode": "sandbox",
        "item_id": item_id,
        "checkout": checkout_result,
        "sale": sale,
        "shipment": dispatch,
        "review": review,
        "seller_central": dashboard,
        "reputation": reputation,
        "readiness": readiness,
        "smoke": smoke,
        "disclaimer": "Demo local com adapters sandbox; nao representa homologacao real de pagamento, frete ou compliance.",
    }
