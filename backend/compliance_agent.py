import argparse
import html
import json
import re
from pathlib import Path

from backend import ai_agent
from backend.prompts.llm_prompts import FCA_VALIDATION_PROMPT, PII_VALIDATION_PROMPT

PII_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "phone": r"\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"
}

SAMPLE_EVENTS = [
    {
        "type": "accountCreation",
        "accountId": "A003",
        "owner": "Charlie",
        "currency": "USD",
        "kycStatus": "verified"
    },
    {
        "type": "loanSearch",
        "customerId": "C123",
        "product": "mortgage",
        "riskCategory": "medium"
    },
    {
        "type": "transaction",
        "transactionId": "T1001",
        "amount": 15200,
        "currency": "USD",
        "reviewRequired": True
    }
]

FCA_RULES = [
    {
        "id": "FCA-1",
        "description": "Account creation events must include KYC status.",
        "check": lambda event: event.get("type") != "accountCreation" or "kycStatus" in event
    },
    {
        "id": "FCA-2",
        "description": "Loan search events must include a riskCategory.",
        "check": lambda event: event.get("type") != "loanSearch" or "riskCategory" in event
    },
    {
        "id": "FCA-3",
        "description": "High-value transactions over 10000 must be marked reviewRequired=True.",
        "check": lambda event: event.get("type") != "transaction" or event.get("amount", 0) <= 10000 or event.get("reviewRequired") is True
    }
]

DEFAULT_LOG_FILE = "sample_logs.txt"


def apply_guardrails(validation, *, kind: str = "pii"):
    issues = []
    if not validation.get("results"):
        issues.append("No validation results were produced.")
    for result in validation.get("results", []):
        if not isinstance(result, dict):
            issues.append("A validation result entry was invalid.")
            continue
        if "findings" not in result:
            issues.append("Validation result missing findings.")
        if "messages" not in result or not result.get("messages"):
            result["messages"] = ["No PII detected"] if kind == "pii" else ["No compliance issues detected"]
        if result.get("foundPii") and not result.get("findings"):
            issues.append("PII flag was true without findings.")
    return {"passed": not issues, "issues": issues}


def explain_pii_validation(validation):
    prompt = f"{PII_VALIDATION_PROMPT}\n{json.dumps(validation, indent=2)}"
    return ai_agent._llm_text(prompt, temperature=0.2, max_output_tokens=220)


def explain_fca_validation(results):
    prompt = f"{FCA_VALIDATION_PROMPT}\n{json.dumps(results, indent=2)}"
    return ai_agent._llm_text(prompt, temperature=0.2, max_output_tokens=220)


def _infer_api_label(line: str) -> str:
    if "/customers" in line:
        return "Customers API"
    if "/accounts" in line:
        return "Accounts API"
    if "/loans" in line:
        return "Loans API"
    if "/products" in line:
        return "Products API"
    if "/transactions" in line:
        return "Transactions API"
    return "Unknown API"


def scan_log_file(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    text = path.read_text(encoding="utf-8")
    findings = []
    entries = []

    for line_index, line in enumerate(text.splitlines(), start=1):
        line_findings = []
        for pii_type, pattern in PII_PATTERNS.items():
            for match in re.finditer(pattern, line):
                line_findings.append({"type": pii_type, "match": match.group(0)})
        entries.append({
            "line": line_index,
            "text": line,
            "api": _infer_api_label(line),
            "findings": line_findings,
            "passed": len(line_findings) == 0,
        })
        if line_findings:
            for item in line_findings:
                findings.append({"type": item["type"], "match": item["match"], "line": line_index, "api": _infer_api_label(line)})

    messages = []
    if findings:
        messages.append("PII detected")
        for item in findings:
            messages.append(f"- {item['type']}: {item['match']} (line {item['line']}, API {item['api']})")
    else:
        messages.append("No PII detected")

    for message in messages:
        print(message)

    api_status = {}
    for entry in entries:
        api = entry["api"]
        if api not in api_status:
            api_status[api] = True
        if not entry["passed"]:
            api_status[api] = False

    return {
        "path": str(path),
        "text": text,
        "entries": entries,
        "findings": findings,
        "apiStatus": api_status,
        "messages": messages,
        "foundPii": bool(findings)
    }


def validate_pii_logs(log_files=None):
    if log_files is None:
        log_files = [DEFAULT_LOG_FILE, "sample_logs_no_pii.txt"]

    results = []
    for log_file in log_files:
        results.append(scan_log_file(Path(log_file)))

    validation = {
        "results": results,
        "summary": {
            "totalLogs": len(results),
            "filesWithPii": sum(1 for result in results if result["foundPii"])
        }
    }
    validation["guardrails"] = apply_guardrails(validation, kind="pii")
    validation["explanation"] = explain_pii_validation(validation)
    return validation


def generate_pii_html_report(validation, report_path: Path):
    rows = []
    for result in validation["results"]:
        for entry in result["entries"]:
            status = "PASSED" if entry["passed"] else "FAILED"
            findings = ", ".join(f"{item['type']}={item['match']}" for item in entry["findings"]) or "None"
            rows.append(
                f"<tr><td>{entry['line']}</td><td>{html.escape(entry['api'])}</td><td>{html.escape(entry['text'])}</td><td>{status}</td><td>{html.escape(findings)}</td></tr>"
            )

    summary = validation["summary"]
    report_html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>PII Validation Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f7fb; color: #1f2937; padding: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
    th, td {{ padding: 10px 12px; border: 1px solid #d1d5db; vertical-align: top; }}
    th {{ background: #111827; color: #fff; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
    .summary {{ padding: 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; margin-bottom: 24px; }}
    .passed {{ color: #047857; font-weight: 700; }}
    .failed {{ color: #b91c1c; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>PII Validation Report</h1>
  <div class=\"summary\">
    <p>Total log files scanned: <strong>{summary['totalLogs']}</strong></p>
    <p>Files with PII: <strong class=\"failed\">{summary['filesWithPii']}</strong></p>
  </div>
  <table>
    <thead>
      <tr><th>Line</th><th>API</th><th>Log text</th><th>Status</th><th>PII details</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>"""
    report_path.write_text(report_html, encoding="utf-8")
    return report_path


def validate_fca_rules(events):
    results = []

    for rule in FCA_RULES:
        for event in events:
            passed = bool(rule["check"](event))
            reason = "Rule passed." if passed else "Rule failed."

            if not passed:
                if rule["id"] == "FCA-1":
                    reason = "Missing KYC status for account creation event."
                elif rule["id"] == "FCA-2":
                    reason = "Missing riskCategory for loan search event."
                elif rule["id"] == "FCA-3":
                    reason = "High-value transaction requires reviewRequired=True."
                else:
                    reason = "Rule condition did not hold."

            result = {
                "ruleId": rule["id"],
                "description": rule["description"],
                "event": event,
                "passed": passed,
                "reason": reason
            }
            results.append(result)
            print(f"Rule {result['ruleId']} for event type {event.get('type')} -> {'PASSED' if passed else 'FAILED'}: {result['reason']}")

    print("FCA validation completed. Executed {} checks.".format(len(results)))
    validation = {
        "results": results,
        "summary": {
            "totalChecks": len(results),
            "passed": sum(1 for r in results if r["passed"]),
            "failed": sum(1 for r in results if not r["passed"])
        }
    }
    validation["guardrails"] = apply_guardrails(validation, kind="fca")
    validation["explanation"] = explain_fca_validation(validation)
    return validation


def generate_fca_html_report(results, report_path: Path):
    rows = []
    for item in results["results"]:
        rows.append(
            f"<tr>"
            f"<td>{item['ruleId']}</td>"
            f"<td>{item['description']}</td>"
            f"<td>{item['event'].get('type')}</td>"
            f"<td>{'PASSED' if item['passed'] else 'FAILED'}</td>"
            f"<td>{item['reason']}</td>"
            f"<td><pre>{json.dumps(item['event'], indent=2)}</pre></td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>FCA Validation Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f7fb; color: #1f2937; padding: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
    th, td {{ padding: 10px 12px; border: 1px solid #d1d5db; vertical-align: top; }}
    th {{ background: #111827; color: #fff; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
    pre {{ background: #f8fafc; padding: 8px; border-radius: 8px; overflow: auto; }}
    .summary {{ padding: 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; margin-bottom: 24px; }}
    .passed {{ color: #047857; font-weight: 700; }}
    .failed {{ color: #b91c1c; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>FCA Validation Report</h1>
  <div class=\"summary\">
    <p>Total checks: <strong>{results['summary']['totalChecks']}</strong></p>
    <p>Passed: <strong class=\"passed\">{results['summary']['passed']}</strong></p>
    <p>Failed: <strong class=\"failed\">{results['summary']['failed']}</strong></p>
  </div>
  <table>
    <thead>
      <tr><th>Rule</th><th>Description</th><th>Event Type</th><th>Status</th><th>Reason</th><th>Event Data</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>"""
    report_path.write_text(html, encoding="utf-8")
    return report_path


def create_sample_logs(path: Path, no_pii: bool = False):
    if no_pii:
        content = "2026-06-28 10:00:00 INFO User login succeeded for customer=Alice\n"
        content += "2026-06-28 10:02:00 INFO Created account A003 for Charlie with initialDeposit=500.0\n"
        content += "2026-06-28 10:05:10 WARN Querying loan offers for customer C123\n"
        content += "2026-06-28 10:06:45 ERROR Transaction T1001 failed for account=A002 amount=12000\n"
    else:
        content = "2026-06-28 10:00:00 INFO User login succeeded for customer=Alice email=alice@example.com ssn=123-45-6789\n"
        content += "2026-06-28 10:02:00 INFO Created account A003 for Charlie with initialDeposit=500.0\n"
        content += "2026-06-28 10:05:10 WARN Querying loan offers for customer C123 phone=+1-555-123-4567\n"
        content += "2026-06-28 10:06:45 ERROR Transaction T1001 failed for account=A002 amount=12000\n"
    path.write_text(content, encoding="utf-8")
    print(f"Sample log file created at {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Run FCA and PII compliance validation for sample banking logs and events.")
    parser.add_argument("command", choices=["validate-pii", "validate-fca", "create-sample-logs"], default="validate-pii", nargs="?", help="Command to execute")
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help="Path to the log file for PII scanning")
    args = parser.parse_args()

    if args.command == "create-sample-logs":
        create_sample_logs(Path(args.log_file))
        return

    if args.command == "validate-pii":
        validate_pii_logs()
        return

    if args.command == "validate-fca":
        validate_fca_rules(SAMPLE_EVENTS)
        return


if __name__ == "__main__":
    main()
