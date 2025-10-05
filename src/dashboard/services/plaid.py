# pages/plaid.py (or pages/plaid_routes.py)
from datetime import date, timedelta
import traceback
from flask import Blueprint, request, jsonify
from plaid.exceptions import ApiException
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.sandbox_item_fire_webhook_request import SandboxItemFireWebhookRequest

from dashboard.services.plaid_client import (
    plaid_client, PLAID_CLIENT_NAME, PLAID_PRODUCTS, PLAID_COUNTRIES, PLAID_REDIRECT_URI, PLAID_ENV, normalize_money
)
from dashboard.services.storage import STORE

plaid_bp = Blueprint("plaid", __name__)

# -------- Helpers --------
def _as_date(v):
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            # Plaid uses 'YYYY-MM-DD' — slice just in case
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None

def to_account_display(a: dict) -> dict:
    bal = a.get("balances", {}) or {}
    return {
        "account_id": a["account_id"],
        "name": a.get("name") or a.get("official_name"),
        "mask": a.get("mask"),
        "type": a.get("type"),
        "subtype": a.get("subtype"),
        "available": normalize_money(bal.get("available")),
        "current": normalize_money(bal.get("current")),
        "currency": bal.get("iso_currency_code") or bal.get("unofficial_currency_code"),
    }

def plaid_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ApiException as e:
        print(e)
        body = getattr(e, "body", "") or str(e)
        # bubble a compact error up to client
        return {"_plaid_error": True, "body": body}

def sync_all(access_token: str, starting_cursor: str | None = "") -> dict:
    """
    Pull all available changes using transactions/sync loop.
    Returns {"added": [...], "next_cursor": "..."}
    """
    client = plaid_client()
    added = []
    cursor = starting_cursor or ""  # IMPORTANT: empty string, not None
    while True:
        req = TransactionsSyncRequest(access_token=access_token, cursor=cursor, count=250)
        res = plaid_call(client.transactions_sync, req)
        if isinstance(res, dict) and res.get("_plaid_error"):
            raise RuntimeError(res["body"])
        data = res.to_dict()

        added.extend(data.get("added", []))
        cursor = data["next_cursor"]
        if not data.get("has_more", False):
            break
    return {"added": added, "next_cursor": cursor}

# -------- Routes --------

@plaid_bp.post("/plaid/link-token")
def create_link_token():
    """Create a Link token for the client."""
    client = plaid_client()
    payload = request.get_json(silent=True) or {}
    user_id = str(payload.get("user_id", "default-user"))  # arbitrary per dev

    body = LinkTokenCreateRequest(
        user={"client_user_id": user_id},
        client_name=PLAID_CLIENT_NAME,
        products=PLAID_PRODUCTS,
        country_codes=PLAID_COUNTRIES,
        language="en",
    )
    if PLAID_REDIRECT_URI:
        body.redirect_uri = PLAID_REDIRECT_URI

    res = plaid_call(client.link_token_create, body)
    if isinstance(res, dict) and res.get("_plaid_error"):
        return jsonify({"error": "LINK_TOKEN_CREATE_FAILED", "details": res["body"]}), 502
    return jsonify(res.to_dict()), 200


@plaid_bp.post("/plaid/exchange")
def exchange_public_token():
    """Exchange public_token for access_token. Also cache item_id->token."""
    client = plaid_client()
    data = request.get_json(force=True)
    public_token = data["public_token"]
    user_id = str(data.get("user_id", "default-user"))

    res = plaid_call(client.item_public_token_exchange,
                     ItemPublicTokenExchangeRequest(public_token=public_token))
    if isinstance(res, dict) and res.get("_plaid_error"):
        return jsonify({"error": "PUBLIC_TOKEN_EXCHANGE_FAILED", "details": res["body"]}), 502

    info = res.to_dict()
    access_token = info["access_token"]
    item_id = info["item_id"]

    STORE.add_access_token(user_id, access_token)
    STORE.upsert_item_map(item_id, access_token)

    # Fetch accounts now for immediate UI display
    acc_res = plaid_call(client.accounts_get, AccountsGetRequest(access_token=access_token))
    if isinstance(acc_res, dict) and acc_res.get("_plaid_error"):
        # still consider exchange successful; just warn about accounts
        return jsonify({"status": "ok", "warning": acc_res["body"]}), 200

    accounts = [to_account_display(a) for a in acc_res.to_dict().get("accounts", [])]
    return jsonify({"status": "ok", "accounts": accounts}), 200


@plaid_bp.get("/plaid/accounts")
def get_accounts():
    """Return normalized accounts for the user."""
    user_id = request.args.get("user_id", "default-user")
    client = plaid_client()
    out = []
    for at in STORE.get_access_tokens(user_id):
        res = plaid_call(client.accounts_get, AccountsGetRequest(access_token=at))
        if isinstance(res, dict) and res.get("_plaid_error"):
            # If item needs relink, bubble that status
            if "ITEM_LOGIN_REQUIRED" in res["body"]:
                return jsonify({"relink_required": True}), 409
            return jsonify({"error": "ACCOUNTS_GET_FAILED", "details": res["body"]}), 502
        out.extend([to_account_display(a) for a in res.to_dict().get("accounts", [])])
    return jsonify(out), 200


@plaid_bp.get("/transactions")
def transactions():
    """Return transactions with optional filters; keeps full sync + cursor logic."""
    user_id   = request.args.get("user_id", "default-user")
    limit     = int(request.args.get("limit", 250))
    since     = request.args.get("since")        # 'YYYY-MM-DD'
    until     = request.args.get("until")        # 'YYYY-MM-DD'
    account_f = request.args.get("account_id")   # optional
    include_pending = (request.args.get("include_pending", "true").lower() == "true")

    rows = []

    for at in STORE.get_access_tokens(user_id):
        try:
            result = sync_all(at, STORE.get_cursor(at) or "")
        except RuntimeError as e:
            body = str(e)
            if "ITEM_LOGIN_REQUIRED" in body:
                return jsonify({"relink_required": True}), 409
            if "PRODUCT_NOT_ENABLED" in body:
                return jsonify({"error": "TRANSACTIONS_NOT_ENABLED"}), 400
            return jsonify({"error": "PLAID_ERROR", "details": body}), 502

        STORE.set_cursor(at, result["next_cursor"])

        for tx in result["added"]:
            d = tx["date"]
            if since and d < since: 
                continue
            if until and d > until: 
                continue

            pending = tx.get("pending", False)
            if pending and not include_pending:
                continue

            if account_f and tx["account_id"] != account_f:
                continue

            pfc = tx.get("personal_finance_category") or {}
            rows.append({
                "id": tx["transaction_id"],
                "date": d,
                "name": tx["name"],
                "amount": normalize_money(tx["amount"]),
                "account_id": tx["account_id"],
                "category": pfc.get("detailed"),
                "pending": pending,
            })

    rows.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    return jsonify(rows[:limit]), 200


@plaid_bp.post("/plaid/unlink")
def unlink():
    """Forget an access token (dev hygiene)."""
    data = request.get_json(force=True)
    user_id = str(data.get("user_id", "default-user"))
    access_token = data["access_token"]
    STORE.remove_access_token(user_id, access_token)
    return jsonify({"ok": True})


@plaid_bp.post("/plaid/webhook")
def plaid_webhook():
    """Transactions webhook handler. Sandbox + Dev friendly."""
    evt = request.get_json(force=True)
    if evt.get("webhook_type") == "TRANSACTIONS":
        item_id = evt.get("item_id")
        at = STORE.token_from_item(item_id) if item_id else None
        if at:
            try:
                result = sync_all(at, STORE.get_cursor(at) or "")
                STORE.set_cursor(at, result["next_cursor"])
            except RuntimeError as e:
                # Log-only in dev
                print("Webhook sync error:", e)
    return jsonify({"ok": True}), 200


# ---------- Sandbox helpers ----------
@plaid_bp.post("/plaid/sandbox/seed")
def sandbox_seed():
    """
    Sandbox: create a public_token for a test institution, exchange it,
    fire a transactions webhook to generate sample tx.
    """
    if PLAID_ENV != "sandbox":
        return jsonify({"error": "SANDBOX_ONLY"}), 400

    client = plaid_client()
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "default-user"))

    # 1) Create sandbox public token
    req = SandboxPublicTokenCreateRequest(
        institution_id="ins_109508",   # First Platypus Bank (US)
        initial_products=[p.value for p in PLAID_PRODUCTS],
    )
    res = plaid_call(client.sandbox_public_token_create, req)
    if isinstance(res, dict) and res.get("_plaid_error"):
        return jsonify({"error": "SANDBOX_CREATE_PUBLIC_TOKEN_FAILED", "details": res["body"]}), 502
    public_token = res.to_dict()["public_token"]

    # 2) Exchange
    ex = plaid_call(client.item_public_token_exchange,
                    ItemPublicTokenExchangeRequest(public_token=public_token))
    if isinstance(ex, dict) and ex.get("_plaid_error"):
        return jsonify({"error": "SANDBOX_EXCHANGE_FAILED", "details": ex["body"]}), 502
    info = ex.to_dict()
    at = info["access_token"]
    item_id = info["item_id"]

    STORE.add_access_token(user_id, at)
    STORE.upsert_item_map(item_id, at)

    # 3) Fire a transactions webhook to create/update tx
    fire = plaid_call(client.sandbox_item_fire_webhook,
                      SandboxItemFireWebhookRequest(item_id=item_id, webhook_type="TRANSACTIONS", webhook_code="DEFAULT_UPDATE"))
    if isinstance(fire, dict) and fire.get("_plaid_error"):
        # Non-fatal
        print("sandbox fire webhook warn:", fire["body"])

    return jsonify({"ok": True}), 200


@plaid_bp.get("/transactions/summary")
def transactions_summary():
    """Aggregate spend/income and category totals (same filters as /transactions)."""
    user_id   = request.args.get("user_id", "default-user")
    since     = request.args.get("since")
    until     = request.args.get("until")
    account_f = request.args.get("account_id")
    limit     = 500  # pull enough after filters

    # Reuse the /transactions logic via internal call or duplicate the filter logic.
    # Here we call the function directly for simplicity:
    with plaid_bp.test_request_context(
        f"/transactions?user_id={user_id}&limit={limit}"
        + (f"&since={since}" if since else "")
        + (f"&until={until}" if until else "")
        + (f"&account_id={account_f}" if account_f else "")
    ):
        resp = transactions()
        if isinstance(resp, tuple):
            payload, status = resp
            if status != 200:
                return resp
            data = payload.get_json()
        else:
            data = resp.get_json()

    rows = data or []

    # Compute aggregates
    spend  = sum(r["amount"] for r in rows if r["amount"] and r["amount"] > 0)
    income = sum((-r["amount"]) for r in rows if r["amount"] and r["amount"] < 0)
    count  = len(rows)

    # Top categories by total spend
    by_cat = {}
    for r in rows:
        cat = r["category"] or "Uncategorized"
        amt = r["amount"] or 0.0
        if amt > 0:  # spend only
            by_cat[cat] = by_cat.get(cat, 0.0) + amt

    top_cats = sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_cats = [{"category": k, "total": v} for k, v in top_cats]

    largest = max(rows, key=lambda r: r["amount"] or 0.0, default=None)

    return jsonify({
        "since": since, "until": until, "count": count,
        "spend": spend, "income": income,
        "largest": largest,
        "top_categories": top_cats
    }), 200

# Helpers for date windows
def _today_str() -> str:
    return date.today().isoformat()

def _first_of_month_str() -> str:
    t = date.today()
    return t.replace(day=1).isoformat()

def _start_of_week_sunday_str() -> str:
    # Monday=0..Sunday=6; go back to last Sunday
    t = date.today()
    days_to_sunday = (t.weekday() + 1) % 7
    return (t - timedelta(days=days_to_sunday)).isoformat()



@plaid_bp.get("/budget/month")
def budget_month():
    try:
        user_id = request.args.get("user_id", "default-user")
        include_pending = request.args.get("include_pending", "true").lower() in ("1","true","yes","y")

        # Date windows as real dates
        today_d = date.today()
        month_start_d = today_d.replace(day=1)
        # start-of-week (Sunday)
        days_to_sunday = (today_d.weekday() + 1) % 7
        week_start_d = today_d - timedelta(days=days_to_sunday)

        tokens = STORE.get_access_tokens(user_id)
        if not tokens:
            return jsonify({
                "status": "ok",
                "totals": {"day": 0.0, "week": 0.0, "month": 0.0},
                "rows": []
            }), 200

        rows = []
        day_total = 0.0
        week_total = 0.0
        month_total = 0.0

        def is_spend(x): return (x is not None) and (x > 0)

        for at in tokens:
            starting_cursor = STORE.get_cursor(at) or ""
            result = sync_all(at, starting_cursor)
            STORE.set_cursor(at, result["next_cursor"])

            for tx in result.get("added", []):
                # choose date; some pending may only have authorized_date
                d_dt = _as_date(tx.get("date") or tx.get("authorized_date"))
                if not d_dt:
                    continue

                # Month window
                if d_dt < month_start_d or d_dt > today_d:
                    continue

                pending = bool(tx.get("pending", False))
                if pending and not include_pending:
                    continue

                pfc = tx.get("personal_finance_category") or {}
                amt_raw = tx.get("amount")
                try:
                    amt = float(amt_raw) if amt_raw is not None else None
                except Exception:
                    amt = None

                # Build row (keep ISO string for the grid)
                row = {
                    "id": tx.get("transaction_id"),
                    "date": d_dt.isoformat(),     # keep string in output
                    "name": tx.get("name"),
                    "amount": amt,
                    "account_id": tx.get("account_id"),
                    "category": pfc.get("detailed"),
                    "pending": pending,
                }
                rows.append(row)

                # Totals on the fly
                if is_spend(amt):
                    if d_dt == today_d:
                        day_total += amt
                    if d_dt >= week_start_d:
                        week_total += amt
                    if d_dt >= month_start_d:
                        month_total += amt

        rows.sort(key=lambda r: (r["date"], r["id"] or ""), reverse=True)

        return jsonify({
            "status": "ok",
            "totals": {"day": day_total, "week": week_total, "month": month_total},
            "rows": rows
        }), 200

    except RuntimeError as e:
        body = str(e)
        if "ITEM_LOGIN_REQUIRED" in body:
            return jsonify({"relink_required": True}), 409
        if "PRODUCT_NOT_ENABLED" in body:
            return jsonify({"error": "TRANSACTIONS_NOT_ENABLED"}), 400
        print("budget_month plaid error:", body)
        return jsonify({"error": "PLAID_ERROR", "details": body}), 502
    except Exception:
        print("budget_month crash:\n", traceback.format_exc())
        return jsonify({"error": "BUDGET_MONTH_FAILED"}), 500