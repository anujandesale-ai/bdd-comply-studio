import html as html_module
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parent.parent
FEATURE_DIR = ROOT_DIR / "features"


class BDDExecutionAgent:
    def __init__(self, base_url="http://localhost:8081", features_dir=FEATURE_DIR):
        self.base_url = base_url.rstrip("/")
        self.features_dir = Path(features_dir)
        if not self.features_dir.is_absolute():
            self.features_dir = ROOT_DIR / self.features_dir
        self.features_dir.mkdir(parents=True, exist_ok=True)

    def _read_feature(self, path: Path):
        return path.read_text(encoding="utf-8").splitlines()

    def _parse_scenarios(self, lines):
        scenarios = []
        current = None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Scenario:"):
                if current:
                    scenarios.append(current)
                current = {"title": stripped[len("Scenario:"):].strip(), "lines": []}
            elif current is not None:
                current["lines"].append(stripped)

        if current:
            scenarios.append(current)
        return scenarios

    def _read_json_block(self, lines, start_index, prefix):
        line = lines[start_index].lstrip()
        payload_text = line[len(prefix):].strip()
        if ((payload_text.startswith("{") and payload_text.endswith("}")) or
            (payload_text.startswith("[") and payload_text.endswith("]"))):
            return json.loads(payload_text), start_index

        block_lines = [payload_text]
        balance = (
            payload_text.count("{") - payload_text.count("}") +
            payload_text.count("[") - payload_text.count("]")
        )
        idx = start_index
        while balance > 0 and idx + 1 < len(lines):
            idx += 1
            next_line = lines[idx].lstrip()
            block_lines.append(next_line)
            balance += (
                next_line.count("{") - next_line.count("}") +
                next_line.count("[") - next_line.count("]")
            )

        return json.loads("\n".join(block_lines)), idx

    def _parse_scenario(self, scenario):
        parsed = {
            "title": scenario["title"],
            "method": "GET",
            "url": None,
            "status": None,
            "request": None,
            "match": None,
        }
        idx = 0
        lines = scenario["lines"]
        while idx < len(lines):
            line = lines[idx]
            if line.startswith("Given url "):
                url_value = line[len("Given url "):].strip()
                if url_value.startswith("baseUrl"):
                    url_value = url_value.replace("baseUrl", self.base_url, 1)
                parsed["url"] = url_value
            elif line.startswith("And request "):
                body, end_idx = self._read_json_block(lines, idx, "And request ")
                parsed["request"] = body
                idx = end_idx
            elif line.startswith("When method "):
                parsed["method"] = line[len("When method "):].strip().upper()
            elif line.startswith("Then status "):
                parsed["status"] = int(line[len("Then status "):].strip())
            elif line.startswith("And match response == "):
                expected, end_idx = self._read_json_block(lines, idx, "And match response == ")
                parsed["match"] = {"type": "equals", "expected": expected}
                idx = end_idx
            elif line.startswith("And match response contains "):
                expected, end_idx = self._read_json_block(lines, idx, "And match response contains ")
                parsed["match"] = {"type": "contains", "expected": expected}
                idx = end_idx
            idx += 1
        return parsed

    def _execute_request(self, parsed):
        if not parsed.get("url"):
            return {"status": "error", "payload": None, "error": "Scenario URL is missing"}

        headers = {"Content-Type": "application/json"}
        body = json.dumps(parsed["request"]).encode("utf-8") if parsed["request"] is not None else None
        request = Request(parsed["url"], data=body, method=parsed["method"], headers=headers)
        try:
            with urlopen(request, timeout=10) as response:
                status = response.getcode()
                raw = response.read().decode("utf-8")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = raw
                return {"status": status, "payload": payload}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8") if exc.fp else ""
            try:
                payload = json.loads(raw)
            except Exception:
                payload = raw
            return {"status": exc.code, "payload": payload, "error": str(exc)}
        except URLError as exc:
            return {"status": "error", "payload": None, "error": str(exc)}
        except Exception as exc:  # pragma: no cover - runtime only
            return {"status": "error", "payload": None, "error": str(exc)}

    def _match_response(self, response, match):
        if match is None:
            return True, "No assertion provided"

        actual = response["payload"]
        if match["type"] == "equals":
            ok = actual == match["expected"]
            return ok, "response equals expected" if ok else f"expected {match['expected']}, got {actual}"

        if match["type"] == "contains":
            if isinstance(actual, list):
                ok = all(item in actual for item in match["expected"])
            elif isinstance(actual, dict):
                ok = all(item in actual.items() for item in match["expected"].items())
            else:
                ok = False
            return ok, "response contains expected" if ok else f"expected to contain {match['expected']}, got {actual}"

        return False, "Unknown match type"

    def execute_feature(self, path: Path):
        try:
            lines = self._read_feature(path)
        except Exception as exc:
            return [{"title": path.name, "method": "GET", "url": None, "expectedStatus": None, "request": None, "assertion": None, "httpResult": None, "passed": False, "notes": [f"Failed to read feature file: {exc}"]}]

        scenarios = self._parse_scenarios(lines)
        results = []

        for scenario in scenarios:
            parsed = self._parse_scenario(scenario)
            step_result = {
                "title": parsed["title"],
                "method": parsed["method"],
                "url": parsed["url"],
                "expectedStatus": parsed["status"],
                "request": parsed["request"],
                "assertion": parsed["match"],
                "httpResult": None,
                "passed": False,
                "notes": []
            }

            if not parsed["url"] or parsed["status"] is None:
                step_result["notes"].append("Invalid scenario definition")
                results.append(step_result)
                continue

            try:
                response = self._execute_request(parsed)
                step_result["httpResult"] = response
                step_result["fca_event"] = self._build_fca_event(parsed, response)
                status_ok = response["status"] == parsed["status"]
                if not status_ok:
                    step_result["notes"].append(f"expected status {parsed['status']}, got {response['status']}")

                match_ok, match_msg = self._match_response(response, parsed["match"])
                step_result["notes"].append(match_msg)
                step_result["passed"] = status_ok and match_ok
            except Exception as exc:
                step_result["notes"].append(f"Execution failed: {exc}")
                step_result["httpResult"] = {"status": "error", "payload": None, "error": str(exc)}
            results.append(step_result)

        return results

    def execute_all(self):
        results = []
        for feature_file in sorted(self.features_dir.glob("*.feature")):
            results.append({
                "feature": str(feature_file.name),
                "scenarios": self.execute_feature(feature_file)
            })
        return results

    def _build_fca_event(self, parsed, response):
        payload = response.get("payload")
        url = parsed.get("url") or ""
        if "/accounts" in url and parsed.get("method") == "POST":
            if isinstance(payload, dict):
                return {
                    "type": "accountCreation",
                    "accountId": payload.get("accountId"),
                    "owner": payload.get("owner"),
                    "currency": payload.get("currency"),
                    "kycStatus": "verified",
                }
        if "/customers" in url and parsed.get("method") == "POST":
            if isinstance(payload, dict):
                return {
                    "type": "customerOnboarding",
                    "customerId": payload.get("customerId"),
                    "name": payload.get("name"),
                    "email": payload.get("email"),
                    "kycStatus": "verified",
                }
        if "/loans" in url:
            return {
                "type": "loanSearch",
                "customerId": "C123",
                "product": "mortgage",
                "riskCategory": "medium",
            }
        if "/transactions" in url:
            if isinstance(payload, dict):
                amount = payload.get("amount", 0)
                return {
                    "type": "transaction",
                    "transactionId": payload.get("transactionId"),
                    "amount": amount,
                    "currency": payload.get("currency", "USD"),
                    "reviewRequired": amount > 10000,
                }
        return None

    def generate_cucumber_html_report(self, results, report_path):
        passed = 0
        total = 0
        rows = []
        for feature in results:
            feature_rows = []
            for scenario in feature["scenarios"]:
                total += 1
                if scenario["passed"]:
                    passed += 1
                status = "PASSED" if scenario["passed"] else "FAILED"
                notes = " | ".join(scenario.get("notes", []))
                feature_rows.append(
                    f"<tr><td>{html_module.escape(str(scenario['title']))}</td><td>{html_module.escape(str(scenario['method']))}</td><td>{html_module.escape(str(scenario['url']))}</td><td>{status}</td><td>{html_module.escape(notes)}</td></tr>"
                )
            rows.append(f"<h2>{html_module.escape(str(feature['feature']))}</h2><table><thead><tr><th>Scenario</th><th>Method</th><th>URL</th><th>Status</th><th>Notes</th></tr></thead><tbody>{''.join(feature_rows)}</tbody></table>")

        report_html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>BDD Execution Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f7fb; color: #1f2937; padding: 24px; }}
    h1 {{ margin-bottom: 0.25rem; }}
    h2 {{ margin-top: 1.5rem; margin-bottom: 0.5rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }}
    th, td {{ padding: 10px 12px; border: 1px solid #d1d5db; text-align: left; vertical-align: top; }}
    th {{ background: #111827; color: white; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
    .summary {{ padding: 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; margin-bottom: 24px; }}
    .passed {{ color: #047857; font-weight: 700; }}
    .failed {{ color: #b91c1c; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>BDD Execution Report</h1>
  <div class=\"summary\">
    <p>Total scenarios: <strong>{total}</strong></p>
    <p>Passed: <strong class=\"passed\">{passed}</strong></p>
    <p>Failed: <strong class=\"failed\">{total - passed}</strong></p>
  </div>
  {''.join(rows)}
</body>
</html>"""
        Path(report_path).write_text(report_html, encoding="utf-8")
        return report_path


def main():
    agent = BDDExecutionAgent()
    results = agent.execute_all()
    for feature in results:
        print(f"Feature: {feature['feature']}")
        for scenario in feature["scenarios"]:
            print(f"  Scenario: {scenario['title']}")
            print(f"    Passed: {scenario['passed']}")
            print(f"    Request: {json.dumps(scenario['request'], indent=2)}")
            print(f"    HTTP result: {json.dumps(scenario['httpResult'], indent=2)}")
            print(f"    Notes: {scenario['notes']}")
        print()

    passed = all(scn["passed"] for feature in results for scn in feature["scenarios"])
    print(f"Overall BDD execution {'passed' if passed else 'failed'}")

    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
