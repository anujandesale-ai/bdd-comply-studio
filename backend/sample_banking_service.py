import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT_DIR / "sample_logs.txt"

API_DEFINITIONS = [
    {
        "method": "GET",
        "path": "/accounts",
        "title": "List all bank accounts",
        "description": "Returns a list of customer accounts.",
        "response_example": [
            {"accountId": "A001", "owner": "Alice", "balance": 2450.75, "currency": "USD"},
            {"accountId": "A002", "owner": "Bob", "balance": 10230.0, "currency": "USD"}
        ]
    },
    {
        "method": "GET",
        "path": "/accounts/{accountId}",
        "title": "Retrieve account details",
        "description": "Returns details for a single account.",
        "path_params": {"accountId": ["A001", "A002"]},
        "response_example": {"accountId": "A001", "owner": "Alice", "balance": 2450.75, "currency": "USD"}
    },
    {
        "method": "POST",
        "path": "/accounts",
        "title": "Create a new account",
        "description": "Creates a new bank account for a customer.",
        "request_example": {"owner": "Charlie", "currency": "USD", "initialDeposit": 500.0},
        "response_example": {"accountId": "A003", "owner": "Charlie", "balance": 500.0, "currency": "USD"}
    },
    {
        "method": "GET",
        "path": "/products",
        "title": "List banking products",
        "description": "Returns available banking products.",
        "response_example": [
            {"productId": "P001", "name": "Savings Account", "category": "Deposit"},
            {"productId": "P002", "name": "Home Loan", "category": "Loan"}
        ]
    },
    {
        "method": "GET",
        "path": "/loans",
        "title": "Search loan offers",
        "description": "Returns loan offers by type.",
        "query_params": {"type": ["personal", "mortgage"]},
        "response_example": [
            {"offerId": "L001", "type": "personal", "rate": 7.5, "termMonths": 36},
            {"offerId": "L002", "type": "mortgage", "rate": 4.25, "termMonths": 240}
        ]
    }
]

ACCOUNTS = [
    {"accountId": "A001", "owner": "Alice", "balance": 2450.75, "currency": "USD"},
    {"accountId": "A002", "owner": "Bob", "balance": 10230.0, "currency": "USD"}
]
CUSTOMERS = [
    {"customerId": "C001", "name": "Alice Johnson", "email": "alice@example.com", "phone": "+1-555-0100", "riskTier": "standard"},
    {"customerId": "C002", "name": "Bob Smith", "email": "bob@example.com", "phone": "+1-555-0101", "riskTier": "high"}
]
TRANSACTIONS = [
    {"transactionId": "T1001", "accountId": "A001", "amount": 1500.0, "currency": "USD", "reviewRequired": False},
    {"transactionId": "T1002", "accountId": "A002", "amount": 12500.0, "currency": "USD", "reviewRequired": True}
]
PRODUCTS = [
    {"productId": "P001", "name": "Savings Account", "category": "Deposit"},
    {"productId": "P002", "name": "Home Loan", "category": "Loan"}
]
LOAN_OFFERS = [
    {"offerId": "L001", "type": "personal", "rate": 7.5, "termMonths": 36},
    {"offerId": "L002", "type": "mortgage", "rate": 4.25, "termMonths": 240}
]


def send_json(handler, status, data):
    payload = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def append_log(message: str) -> None:
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} INFO {message}\n")


class BankingAPIHandler(BaseHTTPRequestHandler):
    def _parse_path(self):
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query)

    def do_GET(self):
        path, query = self._parse_path()
        if path == "/accounts":
            append_log("[GET /accounts] List accounts requested")
            send_json(self, 200, ACCOUNTS)
            return

        if path.startswith("/accounts/"):
            account_id = path.split("/", 2)[2]
            account = next((acc for acc in ACCOUNTS if acc["accountId"] == account_id), None)
            if account:
                append_log(f"[GET /accounts/{{accountId}}] Retrieved account {account_id} for owner={account['owner']}")
                send_json(self, 200, account)
            else:
                send_json(self, 404, {"error": "Account not found"})
            return

        if path == "/customers":
            append_log("[GET /customers] Listed customers with PII details email=alice@example.com phone=+1-555-0100")
            send_json(self, 200, CUSTOMERS)
            return

        if path.startswith("/customers/"):
            customer_id = path.split("/", 2)[2]
            customer = next((c for c in CUSTOMERS if c["customerId"] == customer_id), None)
            if customer:
                append_log(f"[GET /customers/{{customerId}}] Retrieved customer {customer_id} with email={customer['email']}")
                send_json(self, 200, customer)
            else:
                send_json(self, 404, {"error": "Customer not found"})
            return

        if path == "/transactions":
            append_log("[GET /transactions] Listed transactions without customer PII")
            send_json(self, 200, TRANSACTIONS)
            return

        if path == "/products":
            append_log("[GET /products] Listed products without customer PII")
            send_json(self, 200, PRODUCTS)
            return

        if path == "/loans":
            loan_type = query.get("type", [None])[0]
            if loan_type:
                append_log(f"[GET /loans] Searched loan offers for type={loan_type}")
                filtered = [offer for offer in LOAN_OFFERS if offer["type"] == loan_type]
                send_json(self, 200, filtered)
            else:
                append_log("[GET /loans] Listed loan offers")
                send_json(self, 200, LOAN_OFFERS)
            return

        send_json(self, 404, {"error": "Resource not found"})

    def do_POST(self):
        path, _ = self._parse_path()
        if path == "/accounts":
            content_length = int(self.headers.get("Content-Length", 0))
            payload = self.rfile.read(content_length)
            try:
                data = json.loads(payload.decode("utf-8"))
                account = {
                    "accountId": f"A{len(ACCOUNTS) + 1:03d}",
                    "owner": data.get("owner", "unknown"),
                    "currency": data.get("currency", "USD"),
                    "balance": float(data.get("initialDeposit", 0.0))
                }
                ACCOUNTS.append(account)
                append_log(f"[POST /accounts] Created account {account['accountId']} for owner={account['owner']} with initialDeposit={account['balance']}")
                send_json(self, 201, account)
            except json.JSONDecodeError:
                send_json(self, 400, {"error": "Invalid JSON body"})
            return

        if path == "/customers":
            content_length = int(self.headers.get("Content-Length", 0))
            payload = self.rfile.read(content_length)
            try:
                data = json.loads(payload.decode("utf-8"))
                customer = {
                    "customerId": f"C{len(CUSTOMERS) + 1:03d}",
                    "name": data.get("name", "Unknown"),
                    "email": data.get("email", "unknown@example.com"),
                    "phone": data.get("phone", "+1-555-0000"),
                    "riskTier": data.get("riskTier", "standard")
                }
                CUSTOMERS.append(customer)
                append_log(f"[POST /customers] Created customer {customer['customerId']} with email={customer['email']} phone={customer['phone']}")
                send_json(self, 201, customer)
            except json.JSONDecodeError:
                send_json(self, 400, {"error": "Invalid JSON body"})
            return

        if path == "/transactions":
            content_length = int(self.headers.get("Content-Length", 0))
            payload = self.rfile.read(content_length)
            try:
                data = json.loads(payload.decode("utf-8"))
                transaction = {
                    "transactionId": f"T{len(TRANSACTIONS) + 1:03d}",
                    "accountId": data.get("accountId", "A999"),
                    "amount": float(data.get("amount", 0)),
                    "currency": data.get("currency", "USD"),
                    "reviewRequired": float(data.get("amount", 0)) > 10000
                }
                TRANSACTIONS.append(transaction)
                append_log(f"[POST /transactions] Recorded transaction {transaction['transactionId']} amount={transaction['amount']} reviewRequired={transaction['reviewRequired']}")
                send_json(self, 201, transaction)
            except json.JSONDecodeError:
                send_json(self, 400, {"error": "Invalid JSON body"})
            return

        send_json(self, 404, {"error": "Resource not found"})

    def log_message(self, format, *args):
        return


def main():
    server_address = ("0.0.0.0", 8081)
    httpd = HTTPServer(server_address, BankingAPIHandler)
    print("Sample banking API running on http://0.0.0.0:8081")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
