import argparse
import json
import os
import re
from pathlib import Path

from backend import ai_agent

try:
    from backend import sample_banking_service as service
except ImportError:  # pragma: no cover - direct execution fallback
    import sample_banking_service as service

ROOT_DIR = Path(__file__).resolve().parent.parent

FEATURE_TEMPLATE = """Feature: {title}
    {description}

{scenarios}
"""

SCENARIO_TEMPLATE = """  Scenario: {scenario_title}
    Given url baseUrl{path_expression}
{request_block}    When method {method}
    Then status {status}
{assert_block}
"""


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def indent_lines(lines, prefix="    "):
    return "".join(prefix + line if line.strip() else line for line in lines)


class BDDAgent:
    def __init__(self, base_url="http://localhost:5000", output_dir="features"):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        if not self.output_dir.is_absolute():
            self.output_dir = ROOT_DIR / self.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mock_dir = ROOT_DIR / "reports"
        self.mock_dir.mkdir(parents=True, exist_ok=True)

    def _read_controller_context(self, controller_source):
        if not controller_source:
            return ""
        path = Path(controller_source)
        if not path.exists():
            return ""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return ""
        return "\n".join(lines[:220])

    def _requires_cbs_mock(self, api_info):
        path = api_info.get("path", "")
        return api_info.get("method") in {"POST", "PUT", "PATCH"} and ("/accounts" in path or "/customers" in path or "/loans" in path)

    def _build_prerequisite_notes(self, api_info, controller_source=None):
        notes = []
        if self._requires_cbs_mock(api_info):
            notes.append("Prerequisite: create a CBS mock response before validating this scenario.")
        if controller_source:
            notes.append(f"Controller source: {Path(controller_source).name}")
        if not notes:
            notes.append("Prerequisite: validate the API contract and expected downstream dependency before running the scenario.")

        prompt = (
            f"You are reviewing generated BDD scenarios for a banking API.\n"
            f"API: {api_info.get('method')} {api_info.get('path')}\n"
            f"Controller context: {self._read_controller_context(controller_source)}"
        )
        llm_note = ai_agent._llm_text(prompt, temperature=0.2, max_output_tokens=120)
        if llm_note and llm_note.lower() != "workflow summary generated locally.":
            extra_notes = [line.strip(" -") for line in llm_note.splitlines() if line.strip()][:3]
            if extra_notes:
                notes.extend(extra_notes)
        return notes[:4]

    def ensure_cbs_mock(self, api_info, output_dir=None):
        if not self._requires_cbs_mock(api_info):
            return None
        target_dir = Path(output_dir or self.mock_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        mock_payload = {
            "service": "CBS",
            "status": "accepted",
            "reference": "CBS-001",
            "message": "Mock response generated for downstream verification",
        }
        if api_info.get("path", "").startswith("/accounts"):
            mock_payload["accountStatus"] = "verified"
        elif api_info.get("path", "").startswith("/customers"):
            mock_payload["customerStatus"] = "verified"
        else:
            mock_payload["loanStatus"] = "approved"
        target_path = target_dir / f"cbs_mock_{slugify(api_info.get('path', 'api'))}.json"
        target_path.write_text(json.dumps(mock_payload, indent=2), encoding="utf-8")
        return target_path

    def _build_path_expression(self, api_info):
        path = api_info["path"]
        if "{" in path and "}" in path:
            path_expression = "/" + "/".join(
                part if not part.startswith("{") else f"{part[1:-1]}" for part in path.strip("/").split("/")
            )
            return path_expression
        return path

    def _build_request_block(self, api_info):
        if api_info.get("method") == "POST" and api_info.get("request_example") is not None:
            body = json.dumps(api_info["request_example"], indent=2)
            return f"    And request {body}\n"
        return ""

    def _build_assert_block(self, api_info):
        response = api_info.get("response_example")
        if response is None:
            return ""

        response_json = json.dumps(response, indent=2)
        if isinstance(response, dict):
            return f"    And match response == {response_json}\n"

        if isinstance(response, list):
            return f"    And match response contains {response_json}\n"

        return ""

    def _load_openapi(self, swagger_path):
        path = Path(swagger_path)
        if not path.exists():
            raise FileNotFoundError(f"Swagger file not found: {path}")
        if path.suffix.lower() != ".json":
            raise ValueError("Only JSON OpenAPI specs are supported in this version.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _extract_schema_example(self, schema):
        if not isinstance(schema, dict):
            return None
        if "example" in schema:
            return schema["example"]
        if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
            return schema["enum"][0]

        schema_type = schema.get("type")
        if schema_type == "object":
            properties = schema.get("properties", {})
            example = {}
            for key, prop_schema in properties.items():
                value = self._extract_schema_example(prop_schema)
                if value is not None:
                    example[key] = value
            return example

        if schema_type == "array":
            item_schema = schema.get("items", {})
            item_example = self._extract_schema_example(item_schema)
            return [item_example] if item_example is not None else []

        if schema_type == "string":
            fmt = schema.get("format", "")
            if fmt == "email":
                return "user@example.com"
            if fmt == "date":
                return "2025-01-01"
            return schema.get("default", "string")

        if schema_type == "integer":
            return schema.get("default", 1)
        if schema_type == "number":
            return schema.get("default", 1.0)
        if schema_type == "boolean":
            return schema.get("default", True)

        return None

    def _extract_request_example(self, request_body):
        if not isinstance(request_body, dict):
            return None
        content = request_body.get("content", {})
        json_schema = content.get("application/json") or next(
            (v for k, v in content.items() if k.endswith("+json")),
            None
        )
        if not json_schema:
            return None
        if "example" in json_schema:
            return json_schema["example"]
        if "examples" in json_schema:
            first = next(iter(json_schema["examples"].values()), {})
            if isinstance(first, dict) and "value" in first:
                return first["value"]
        return self._extract_schema_example(json_schema.get("schema", {}))

    def _extract_response_example(self, responses):
        if not isinstance(responses, dict):
            return None
        for status in ("200", "201", "default"):
            response = responses.get(status)
            if response:
                content = response.get("content", {})
                json_schema = content.get("application/json") or next(
                    (v for k, v in content.items() if k.endswith("+json")),
                    None
                )
                if json_schema:
                    if "example" in json_schema:
                        return json_schema["example"]
                    if "examples" in json_schema:
                        first = next(iter(json_schema["examples"].values()), {})
                        if isinstance(first, dict) and "value" in first:
                            return first["value"]
                    return self._extract_schema_example(json_schema.get("schema", {}))
        for response in responses.values():
            content = response.get("content", {})
            json_schema = content.get("application/json") or next(
                (v for k, v in content.items() if k.endswith("+json")),
                None
            )
            if json_schema:
                if "example" in json_schema:
                    return json_schema["example"]
                if "examples" in json_schema:
                    first = next(iter(json_schema["examples"].values()), {})
                    if isinstance(first, dict) and "value" in first:
                        return first["value"]
                return self._extract_schema_example(json_schema.get("schema", {}))
        return None

    def _collect_parameter_examples(self, parameters):
        path_params = {}
        query_params = {}
        if not isinstance(parameters, list):
            return path_params, query_params
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            name = parameter.get("name")
            if not name:
                continue
            examples = []
            if "example" in parameter:
                examples.append(parameter["example"])
            if "examples" in parameter and isinstance(parameter["examples"], dict):
                for example_def in parameter["examples"].values():
                    if isinstance(example_def, dict) and "value" in example_def:
                        examples.append(example_def["value"])
            schema = parameter.get("schema", {})
            if not examples and isinstance(schema, dict) and "enum" in schema:
                examples.extend(schema["enum"])
            if parameter.get("in") == "path" and examples:
                path_params[name] = examples
            if parameter.get("in") == "query" and examples:
                query_params[name] = examples
        return path_params, query_params

    def _info_from_operation(self, path, method, operation, path_parameters):
        api_info = {
            "method": method,
            "path": path,
            "title": operation.get("summary", f"{method} {path}"),
            "description": operation.get("description", ""),
            "request_example": self._extract_request_example(operation.get("requestBody")),
            "response_example": self._extract_response_example(operation.get("responses", {})),
            "path_params": {},
            "query_params": {}
        }
        path_params, query_params = self._collect_parameter_examples(path_parameters)
        api_info["path_params"] = path_params
        api_info["query_params"] = query_params
        return api_info

    def generate_from_openapi(self, swagger_path, controller_source=None):
        spec = self._load_openapi(swagger_path)
        generated = []
        paths = spec.get("paths", {})
        for path, path_item in paths.items():
            path_parameters = path_item.get("parameters", []) if isinstance(path_item, dict) else []
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                    continue
                if method == "parameters":
                    continue
                api_info = self._info_from_operation(path, method.upper(), operation, path_parameters + operation.get("parameters", []))
                generated.append(self.generate_feature(api_info, controller_source=controller_source))
        return generated

    def _build_scenarios(self, api_info):
        scenarios = []
        if api_info.get("method") == "GET" and api_info.get("path_params"):
            for example in next(iter(api_info["path_params"].values())):
                path_expr = api_info["path"].replace("{accountId}", example)
                scenarios.append(
                    SCENARIO_TEMPLATE.format(
                        scenario_title=f"Retrieve {api_info['title']} for {example}",
                        path_expression=path_expr,
                        method=api_info["method"].lower(),
                        status=200,
                        request_block="",
                        assert_block=self._build_assert_block(api_info)
                    )
                )
            return "\n".join(scenarios)

        if api_info.get("query_params"):
            query_key, values = next(iter(api_info["query_params"].items()))
            for example in values:
                path_expr = f"{api_info['path']}?{query_key}={example}"
                scenarios.append(
                    SCENARIO_TEMPLATE.format(
                        scenario_title=f"Query {api_info['title']} by {query_key}={example}",
                        path_expression=path_expr,
                        method=api_info["method"].lower(),
                        status=200,
                        request_block="",
                        assert_block=self._build_assert_block(api_info)
                    )
                )
            return "\n".join(scenarios)

        scenarios.append(
            SCENARIO_TEMPLATE.format(
                scenario_title=api_info["title"],
                path_expression=api_info["path"],
                method=api_info["method"].lower(),
                status=200 if api_info["method"] != "POST" else 201,
                request_block=self._build_request_block(api_info),
                assert_block=self._build_assert_block(api_info)
            )
        )
        return "\n".join(scenarios)

    def generate_feature(self, api_info, controller_source=None):
        filename = f"{slugify(api_info['method'] + ' ' + api_info['path'])}.feature"
        feature_path = self.output_dir / filename
        scenarios = self._build_scenarios(api_info)
        prerequisites = self._build_prerequisite_notes(api_info, controller_source=controller_source)
        description = api_info.get("description", "")
        if prerequisites:
            description = f"{description}\n\nPrerequisites:\n" + "\n".join(f"- {note}" for note in prerequisites)
        content = FEATURE_TEMPLATE.format(
            title=api_info["title"],
            description=description,
            scenarios=scenarios
        )
        content = content.replace("\n\n\n", "\n\n")
        feature_path.write_text(content, encoding="utf-8")
        self.ensure_cbs_mock(api_info, output_dir=self.mock_dir)
        return feature_path

    def generate_all(self, swagger_path=None, controller_source=None):
        if swagger_path:
            return self.generate_from_openapi(swagger_path, controller_source=controller_source)

        generated_files = []
        for api_info in service.API_DEFINITIONS:
            generated_files.append(self.generate_feature(api_info, controller_source=controller_source))
        return generated_files


def main():
    parser = argparse.ArgumentParser(description="Generate Karate BDD feature files for sample banking APIs.")
    parser.add_argument("command", nargs="?", default="generate", choices=["generate", "serve"], help="generate feature files or serve the sample API")
    parser.add_argument("--output-dir", default="features", help="Output directory for generated feature files")
    parser.add_argument("--base-url", default="http://localhost:5000", help="Base URL used in generated feature files")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the sample banking service on")
    parser.add_argument("--swagger", default=None, help="Path to an OpenAPI JSON file to generate BDDs from")
    args = parser.parse_args()

    if args.command == "serve":
        print(f"Starting sample banking API server on http://0.0.0.0:{args.port}")
        os.environ["PORT"] = str(args.port)
        service.main()
        return

    agent = BDDAgent(base_url=args.base_url, output_dir=args.output_dir)
    files = agent.generate_all(args.swagger)
    print(f"Generated {len(files)} Karate feature file(s) in {agent.output_dir}")
    for f in files:
        print(f"- {f}")


if __name__ == "__main__":
    main()
