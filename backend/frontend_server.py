import contextlib
import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "frontend"

try:
    from backend import ai_agent, bdd_agent, bdd_execution_agent, compliance_agent
except ImportError:
    import ai_agent, bdd_agent, bdd_execution_agent, compliance_agent

SERVICE_URL = "http://localhost:8081"
AUDIT_TRAIL = []


def capture_printed_output(func, *args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue().strip()


def proxy_service(path, method="GET", body=None, headers=None):
    headers = headers or {"Content-Type": "application/json"}
    url = f"{SERVICE_URL}{path}"
    data = body.encode("utf-8") if body is not None else None
    req = Request(url, data=data, method=method, headers=headers)
    with urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8"), resp.getcode()


def append_audit(action, status, message=""):
    item = {"action": action, "status": status, "message": message}
    AUDIT_TRAIL.insert(0, item)
    return item


class FrontendHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="text/html"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()

    def _send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_file(self, filename, content_type="text/html"):
        path = STATIC_DIR / filename
        if not path.exists():
            self._set_headers(404)
            self.wfile.write(b"Not found")
            return
        self._set_headers(200, content_type)
        self.wfile.write(path.read_bytes())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self._serve_file("index.html")
            return

        if path == "/api/audit-trail":
            self._send_json({"auditTrail": AUDIT_TRAIL})
            return

        if path == "/api/accounts":
            try:
                body, code = proxy_service("/accounts")
                append_audit("Fetch all accounts", code, body)
                self._send_json({"result": json.loads(body), "status": code})
            except (URLError, HTTPError) as exc:
                append_audit("Fetch all accounts", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path.startswith("/api/account/"):
            account_id = path.split("/", 3)[-1]
            try:
                body, code = proxy_service(f"/accounts/{account_id}")
                append_audit(f"Fetch account {account_id}", code, body)
                self._send_json({"result": json.loads(body), "status": code})
            except (URLError, HTTPError) as exc:
                append_audit(f"Fetch account {account_id}", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/products":
            try:
                body, code = proxy_service("/products")
                append_audit("Fetch products", code, body)
                self._send_json({"result": json.loads(body), "status": code})
            except (URLError, HTTPError) as exc:
                append_audit("Fetch products", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/loans":
            loan_type = query.get("type", [None])[0]
            try:
                query_string = f"?type={loan_type}" if loan_type else ""
                body, code = proxy_service(f"/loans{query_string}")
                append_audit("Search loans", code, body)
                self._send_json({"result": json.loads(body), "status": code})
            except (URLError, HTTPError) as exc:
                append_audit("Search loans", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/generate-bdd":
            swagger_path = query.get("swagger", [None])[0]
            try:
                agent = bdd_agent.BDDAgent(base_url=SERVICE_URL, output_dir="features")
                if swagger_path:
                    generated_files = [str(p) for p in agent.generate_all(swagger_path)]
                else:
                    generated_files = [str(p) for p in agent.generate_all()]
                llm_summary = ai_agent.summarize_openapi_generation(swagger_path or "default API definitions", generated_files)
                append_audit("Generate Karate BDD", 200, ", ".join(generated_files))
                self._send_json({"generated": generated_files, "status": 200, "swaggerPath": swagger_path, "llmSummary": llm_summary})
            except Exception as exc:
                append_audit("Generate Karate BDD", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/execute-bdd":
            try:
                agent = bdd_execution_agent.BDDExecutionAgent(base_url=SERVICE_URL, features_dir="features")
                results = agent.execute_all()
                report_file = STATIC_DIR / "bdd_execution_report.html"
                report_path = agent.generate_cucumber_html_report(results, report_file)
                report_url = f"/static/{report_file.name}"
                llm_summary = ai_agent.summarize_bdd_execution(results)
                append_audit("Execute BDDs", 200, f"{sum(1 for f in results for s in f['scenarios'] if s['passed'])}/{sum(len(f['scenarios']) for f in results)} scenarios passed")
                self._send_json({
                    "executionResults": results,
                    "summary": {"passed": sum(1 for f in results for s in f['scenarios'] if s['passed']), "total": sum(len(f['scenarios']) for f in results)},
                    "reportUrl": report_url,
                    "llmSummary": llm_summary,
                    "status": 200
                })
            except Exception as exc:
                append_audit("Execute BDDs", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/validate-pii":
            try:
                validation, printed = capture_printed_output(compliance_agent.validate_pii_logs)
                llm_summary = ai_agent.summarize_pii_results(validation)
                append_audit("Validate PII", 200, printed.replace("\n", " | "))
                self._send_json({"validation": validation, "printedLogs": printed, "llmSummary": llm_summary, "status": 200})
            except Exception as exc:
                append_audit("Validate PII", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/validate-fca":
            try:
                results, printed = capture_printed_output(compliance_agent.validate_fca_rules, compliance_agent.SAMPLE_EVENTS)
                llm_summary = ai_agent.summarize_fca_results(results)
                report_file = STATIC_DIR / "fca_validation_report.html"
                compliance_agent.generate_fca_html_report(results, report_file)
                report_url = f"/static/{report_file.name}"
                append_audit("Validate FCA", 200, printed.replace("\n", " | "))
                self._send_json({"fcaResults": results, "printedLogs": printed, "llmSummary": llm_summary, "fcaReportUrl": report_url, "status": 200})
            except Exception as exc:
                append_audit("Validate FCA", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/create-sample-logs":
            no_pii = query.get("no-pii", ["false"])[0].lower() in ("1", "true", "yes")
            filename = query.get("file", [compliance_agent.DEFAULT_LOG_FILE])[0]
            try:
                target_path = Path(filename)
                created_path = compliance_agent.create_sample_logs(target_path, no_pii=no_pii)
                append_audit("Create sample logs", 200, str(created_path))
                self._send_json({"file": str(created_path), "noPii": no_pii, "status": 200})
            except Exception as exc:
                append_audit("Create sample logs", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path.startswith("/static/"):
            file_path = STATIC_DIR / path.lstrip("/static/")
            if file_path.exists():
                if file_path.suffix == ".css":
                    content_type = "text/css"
                elif file_path.suffix == ".html":
                    content_type = "text/html"
                elif file_path.suffix == ".js":
                    content_type = "application/javascript"
                else:
                    content_type = "application/octet-stream"
                self._set_headers(200, content_type)
                self.wfile.write(file_path.read_bytes())
                return

        self._set_headers(404)
        self.wfile.write(b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/generate-bdd":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(body) if body else {}
                content = payload.get("content")
                swagger_filename = Path(payload.get("filename", "uploaded_openapi.json")).name
                agent = bdd_agent.BDDAgent(base_url=SERVICE_URL, output_dir="features")
                generated_files = []
                swagger_path = None

                if content:
                    target_path = ROOT_DIR / swagger_filename
                    target_path.write_text(content, encoding="utf-8")
                    generated_files = [str(p) for p in agent.generate_all(str(target_path))]
                    swagger_path = str(target_path)
                else:
                    specs_dir = ROOT_DIR / "specs"
                    if specs_dir.exists() and specs_dir.is_dir():
                        for swagger_file in sorted(specs_dir.glob("*.json")):
                            generated_files.extend(str(p) for p in agent.generate_all(str(swagger_file)))
                        swagger_path = "specs/*.json"

                    if not generated_files:
                        generated_files = [str(p) for p in agent.generate_all()]
                        swagger_path = None

                llm_summary = ai_agent.summarize_openapi_generation(swagger_path or "default API definitions", generated_files)
                append_audit("Generate Karate BDD", 200, ", ".join(generated_files))
                self._send_json({"generated": generated_files, "status": 200, "swaggerPath": swagger_path, "llmSummary": llm_summary})
            except Exception as exc:
                append_audit("Generate Karate BDD", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/create-account":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(body)
                data, code = proxy_service("/accounts", method="POST", body=json.dumps(payload))
                append_audit("Create account", code, data)
                self._send_json({"result": json.loads(data), "status": code})
            except Exception as exc:
                append_audit("Create account", "error", str(exc))
                self._send_json({"error": str(exc)}, status=500)
            return

        self._set_headers(404)
        self.wfile.write(b"Not found")


def main():
    address = ("0.0.0.0", 8082)
    httpd = HTTPServer(address, FrontendHandler)
    print("Frontend simulation UI running at http://0.0.0.0:8082")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
