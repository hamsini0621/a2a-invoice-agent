import json
import os
import sqlite3
import hashlib
from datetime import datetime, timezone
from flask import Flask, request, jsonify

APP_NAME = "Safe Invoice Agent"
DB_PATH = os.environ.get("DB_PATH", "invoice_state.db")
APPROVAL_LIMIT = float(os.environ.get("APPROVAL_LIMIT", "10000"))
app = Flask(__name__)

def now():
    return datetime.now(timezone.utc).isoformat()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_key TEXT PRIMARY KEY,
            invoice_id TEXT NOT NULL,
            supplier TEXT,
            amount REAL,
            currency TEXT,
            status TEXT NOT NULL,
            decision TEXT NOT NULL,
            evidence TEXT NOT NULL,
            receipt TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            idempotency_key TEXT PRIMARY KEY,
            invoice_key TEXT NOT NULL,
            action TEXT NOT NULL,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

def stable_invoice_key(invoice):
    # Prefer supplier + invoice number; amount alone is never enough to call something a duplicate.
    invoice_id = str(invoice.get("invoice_id") or invoice.get("invoice_number") or "").strip()
    supplier = str(invoice.get("supplier") or invoice.get("vendor") or "").strip().casefold()
    if not invoice_id or not supplier:
        return None
    return hashlib.sha256(f"{supplier}|{invoice_id}".encode("utf-8")).hexdigest()

def classify(package):
    """Rule-based safety gate. An LLM may extract fields, but must not override these rules."""
    invoice = package.get("invoice") or package.get("document") or {}
    receipt = package.get("receipt")
    approval = package.get("approval") or {}
    payment = package.get("payment") or {}
    evidence = []

    invoice_id = str(invoice.get("invoice_id") or invoice.get("invoice_number") or "").strip()
    supplier = str(invoice.get("supplier") or invoice.get("vendor") or "").strip()
    amount = invoice.get("amount", invoice.get("total"))
    currency = str(invoice.get("currency") or "").strip().upper()

    if invoice_id:
        evidence.append(f"Invoice identifier provided: {invoice_id}")
    else:
        evidence.append("Invoice identifier is missing.")
    if supplier:
        evidence.append(f"Supplier provided: {supplier}")
    else:
        evidence.append("Supplier is missing.")
    if amount is not None:
        try:
            amount = float(amount)
            if amount > 0:
                evidence.append(f"Invoice total is {amount:.2f} {currency or '(currency unspecified)'}")
            else:
                evidence.append("Invoice amount must be greater than zero.")
        except (TypeError, ValueError):
            amount = None
            evidence.append("Invoice amount is not numeric.")
    else:
        evidence.append("Invoice amount is missing.")
    if not currency:
        evidence.append("Currency is missing.")

    key = stable_invoice_key(invoice)
    if not invoice_id or not supplier or amount is None or amount <= 0 or not currency:
        return {
            "decision": "HUMAN_REVIEW",
            "action": "HOLD",
            "reason": "Required invoice fields are missing or invalid.",
            "evidence": evidence,
            "invoice_key": key,
            "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}
        }

    if not receipt:
        evidence.append("No receipt or proof of goods/services was supplied.")
        return {"decision": "HUMAN_REVIEW", "action": "HOLD",
                "reason": "Receipt evidence is missing.", "evidence": evidence,
                "invoice_key": key, "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}}

    receipt_amount = receipt.get("amount") if isinstance(receipt, dict) else None
    receipt_supplier = receipt.get("supplier") if isinstance(receipt, dict) else None
    if receipt_amount is None or receipt_supplier is None:
        evidence.append("Receipt must include supplier and amount for matching.")
        return {"decision": "HUMAN_REVIEW", "action": "HOLD",
                "reason": "Receipt cannot be matched reliably.", "evidence": evidence,
                "invoice_key": key, "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}}

    try:
        receipt_amount = float(receipt_amount)
    except (TypeError, ValueError):
        receipt_amount = None

    if receipt_supplier.strip().casefold() != supplier.casefold() or receipt_amount is None or abs(receipt_amount - amount) > 0.01:
        evidence.append("Receipt supplier/amount does not match invoice.")
        return {"decision": "HUMAN_REVIEW", "action": "HOLD",
                "reason": "Invoice and receipt mismatch.", "evidence": evidence,
                "invoice_key": key, "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}}

    evidence.append("Receipt supplier and amount match the invoice.")
    approved = approval.get("approved") is True
    approver = str(approval.get("approver") or "").strip()
    approved_limit = approval.get("limit", APPROVAL_LIMIT)
    try:
        approved_limit = float(approved_limit)
    except (TypeError, ValueError):
        approved_limit = APPROVAL_LIMIT

    if amount > min(APPROVAL_LIMIT, approved_limit):
        evidence.append(f"Amount exceeds permitted approval limit ({min(APPROVAL_LIMIT, approved_limit):.2f}).")
        return {"decision": "HUMAN_REVIEW", "action": "HOLD",
                "reason": "Invoice exceeds the configured approval limit.", "evidence": evidence,
                "invoice_key": key, "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}}

    if not approved or not approver:
        evidence.append("Explicit approval and approver identity are not both present.")
        return {"decision": "HUMAN_REVIEW", "action": "HOLD",
                "reason": "Required approval is missing.", "evidence": evidence,
                "invoice_key": key, "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}}

    evidence.append(f"Approval recorded for this invoice by {approver}.")
    if payment.get("already_paid") is True:
        evidence.append("Payment record says this invoice has already been paid.")
        return {"decision": "DUPLICATE_BLOCKED", "action": "DO_NOT_PAY",
                "reason": "Invoice is already marked paid.", "evidence": evidence,
                "invoice_key": key, "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}}

    return {"decision": "APPROVED_FOR_PAYMENT", "action": "RECORD_APPROVED",
            "reason": "Required fields, receipt match, approval, and limit checks passed. No external payment is initiated by this demo.",
            "evidence": evidence, "invoice_key": key,
            "invoice": {"invoice_id": invoice_id, "supplier": supplier, "amount": amount, "currency": currency}}

def process_package(package):
    if not isinstance(package, dict):
        return {"ok": False, "error": "Package must be a JSON object."}, 400

    result = classify(package)
    inv = result["invoice"]
    key = result.get("invoice_key")
    if not key:
        return {"ok": True, **result, "state": "not_saved",
                "note": "Invoice ID and supplier are required to save a durable idempotency key."}, 200

    with db() as conn:
        existing = conn.execute("SELECT * FROM invoices WHERE invoice_key=?", (key,)).fetchone()
        if existing:
            # Any prior processing record blocks automatic repetition, especially payment-like actions.
            old_status = existing["status"]
            if old_status in ("APPROVED_FOR_PAYMENT", "PAID", "PAYMENT_PENDING"):
                return {"ok": True, "decision": "DUPLICATE_BLOCKED", "action": "DO_NOT_PAY",
                        "reason": "This invoice has already been processed; retry will not repeat an action.",
                        "evidence": [f"Stored record found for invoice {existing['invoice_id']} with status {old_status}."],
                        "state": "existing_record", "invoice_id": existing["invoice_id"]}, 200

        status = result["decision"]
        receipt_json = json.dumps(package.get("receipt"), ensure_ascii=False)
        values = (key, str(inv["invoice_id"]), inv["supplier"], inv["amount"], inv["currency"],
                  status, result["decision"], json.dumps(result["evidence"], ensure_ascii=False),
                  receipt_json, now(), now())
        conn.execute("""
        INSERT INTO invoices(invoice_key, invoice_id, supplier, amount, currency, status, decision, evidence, receipt, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(invoice_key) DO UPDATE SET
          status=excluded.status, decision=excluded.decision, evidence=excluded.evidence,
          receipt=excluded.receipt, updated_at=excluded.updated_at
        """, values)

    return {"ok": True, **result, "state": "saved"}, 200

@app.get("/")
def index():
    return jsonify({"name": APP_NAME, "status": "ok", "protocol": "A2A-compatible starter",
                    "agent_card": "/.well-known/agent-card.json", "endpoint": "/a2a/"})

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/.well-known/agent-card.json")
def agent_card():
    base = request.url_root.rstrip("/")
    return jsonify({
        "name": APP_NAME,
        "description": "Evidence-based invoice decision agent with approval-limit and retry safeguards.",
        "url": base + "/a2a/",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": [{
            "id": "invoice_decision",
            "name": "Invoice decision and safe processing",
            "description": "Reviews invoice package, cites evidence, checks approval, and persists processing state.",
            "tags": ["invoice", "accounts-payable", "safety"]
        }]
    })

@app.post("/a2a/")
def a2a():
    """Small JSON-RPC-style A2A adapter. Adapt method names/schema to the course's exact API contract."""
    payload = request.get_json(silent=True) or {}
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if payload.get("jsonrpc") not in (None, "2.0"):
        return jsonify({"jsonrpc": "2.0", "id": rpc_id,
                        "error": {"code": -32600, "message": "Invalid JSON-RPC version"}}), 400

    if method in ("message/send", "tasks/send", "invoice/process"):
        # Accept direct packages and A2A message parts containing structured data.
        package = params.get("package") or params.get("invoice_package") or params.get("input")
        message = params.get("message")
        if package is None and isinstance(message, dict):
            # Some A2A clients place the input package inside a data part.
            if isinstance(message.get("data"), dict):
                package = message["data"]
            else:
                parts = message.get("parts") or []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if part.get("kind") == "data" and isinstance(part.get("data"), dict):
                        package = part["data"]
                        break
                    if part.get("kind") == "text" and isinstance(part.get("text"), str):
                        # Text is accepted only when it contains a JSON object; do not guess
                        # financial values from free-form natural language.
                        try:
                            candidate = json.loads(part["text"])
                            if isinstance(candidate, dict):
                                package = candidate
                                break
                        except json.JSONDecodeError:
                            pass
        if package is None:
            package = params
        result, status = process_package(package)
        if status >= 400:
            response = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": result["error"]}}
        else:
            response = {"jsonrpc": "2.0", "id": rpc_id, "result": {
                "kind": "message",
                "status": {"state": "completed"},
                "artifacts": [{"name": "invoice_decision", "parts": [{"kind": "data", "data": result}]}]
            }}
        return jsonify(response), status

    if method in ("tasks/get", "invoice/status"):
        invoice_id = str(params.get("invoice_id") or "")
        with db() as conn:
            row = conn.execute("SELECT invoice_id,supplier,amount,currency,status,decision,evidence,created_at,updated_at FROM invoices WHERE invoice_id=? ORDER BY updated_at DESC LIMIT 1", (invoice_id,)).fetchone()
        if not row:
            result = {"found": False, "invoice_id": invoice_id}
        else:
            result = dict(row)
            result["evidence"] = json.loads(result["evidence"])
            result["found"] = True
        return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    return jsonify({"jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32601, "message": f"Unsupported method: {method}"}}), 400

@app.post("/invoice/process")
def invoice_process():
    result, status = process_package(request.get_json(silent=True))
    return jsonify(result), status

@app.get("/invoice/status/<invoice_id>")
def invoice_status(invoice_id):
    with db() as conn:
        row = conn.execute("SELECT invoice_id,supplier,amount,currency,status,decision,evidence,created_at,updated_at FROM invoices WHERE invoice_id=? ORDER BY updated_at DESC LIMIT 1", (invoice_id,)).fetchone()
    if not row:
        return jsonify({"found": False, "invoice_id": invoice_id}), 404
    result = dict(row)
    result["evidence"] = json.loads(result["evidence"])
    result["found"] = True
    return jsonify(result)

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
