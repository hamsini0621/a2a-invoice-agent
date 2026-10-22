# Safe A2A Invoice Agent — starter implementation

This project is a runnable Flask service that:
- reads structured invoice-package JSON;
- checks required invoice fields and receipt consistency;
- checks explicit approval and configured approval limits;
- returns a decision with supporting evidence;
- stores processing state in SQLite and blocks repeat processing of an already-approved invoice;
- exposes a small JSON-RPC-style A2A endpoint, an agent card, health check, and direct invoice endpoints.

## Important assignment note

The screenshot provided only shows the field `A2A interface base URL`; it does not show the full API contract. This starter uses common A2A-style paths and JSON-RPC request shapes, but the grader may require exact method names, input fields, output fields, or task states. Compare the remaining assignment instructions and adjust `/a2a/` accordingly before spending checks.

This demo does **not** initiate real payments. `APPROVED_FOR_PAYMENT` means the invoice passed the checks and is approved for a separate authorized payment system. Never connect payment execution without a real authorization mechanism, payment-provider idempotency, and reconciliation for uncertain outcomes.

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open:
- `http://127.0.0.1:8080/health`
- `http://127.0.0.1:8080/.well-known/agent-card.json`

## Test an invoice package

```bash
curl -X POST http://127.0.0.1:8080/invoice/process \
  -H "Content-Type: application/json" \
  -d '{
    "invoice": {
      "invoice_id": "INV-101",
      "supplier": "ABC Services",
      "amount": 5000,
      "currency": "INR"
    },
    "receipt": {
      "supplier": "ABC Services",
      "amount": 5000
    },
    "approval": {
      "approved": true,
      "approver": "Finance Manager",
      "limit": 10000
    },
    "payment": {
      "already_paid": false
    }
  }'
```

Repeat the same request. The second request should be blocked as a duplicate because state is stored in `invoice_state.db`.

## A2A-style JSON-RPC example

```json
{
  "jsonrpc": "2.0",
  "id": "test-1",
  "method": "message/send",
  "params": {
    "package": {
      "invoice": {
        "invoice_id": "INV-101",
        "supplier": "ABC Services",
        "amount": 5000,
        "currency": "INR"
      },
      "receipt": {"supplier": "ABC Services", "amount": 5000},
      "approval": {"approved": true, "approver": "Finance Manager", "limit": 10000},
      "payment": {"already_paid": false}
    }
  }
}
```

Send that JSON to `POST /a2a/`.

## Deploy

Deploy the project as a web service using the included Dockerfile or use a Python web service host:
- Build/install command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT app:app`

Set environment variable `APPROVAL_LIMIT` to the maximum amount allowed for this agent. The filesystem must be persistent for SQLite state; otherwise use a persistent volume or replace SQLite with a managed database. If a host has ephemeral filesystems, retries after restart may lose state.

After deployment, test `/health` and `/.well-known/agent-card.json`. Use the actual public HTTPS base URL in the assignment, ending in `/a2a/` if the checker expects the A2A endpoint itself, or use the exact base-path format specified by the assignment.
