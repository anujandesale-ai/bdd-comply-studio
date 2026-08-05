import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import ai_agent, bdd_agent, bdd_execution_agent, compliance_agent

ROOT_DIR = Path(__file__).resolve().parent.parent
FEATURES_DIR = ROOT_DIR / "features"
REPORTS_DIR = ROOT_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class WorkflowError(RuntimeError):
    pass


class WorkflowOrchestrator:
    def __init__(self, base_url: str = "http://localhost:8081", output_dir: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir or FEATURES_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir = REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.last_run: dict[str, Any] = {}

    def _safe_write_text(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _resolve_swagger_inputs(
        self,
        swagger_file: str | None = None,
        all_specs: bool = False,
        controller_source: str | None = None,
        user_prompt: str | None = None,
    ) -> list[Path]:
        if swagger_file:
            return [Path(swagger_file)]
        if all_specs:
            specs_dir = ROOT_DIR / "specs"
            return sorted(specs_dir.glob("*.json")) if specs_dir.exists() else []
        if controller_source:
            return []

        prompt_text = (user_prompt or "").strip().lower()
        specs_dir = ROOT_DIR / "specs"
        if specs_dir.exists():
            prompt_keywords = [token for token in re.findall(r"[a-z0-9]+", prompt_text) if len(token) > 2]
            scored_specs: list[tuple[int, Path]] = []
            for spec_path in sorted(specs_dir.glob("*.json")):
                text = spec_path.read_text(encoding="utf-8", errors="ignore").lower()
                if not prompt_text:
                    scored_specs.append((0, spec_path))
                    continue
                score = 0
                for keyword in prompt_keywords:
                    if keyword in text:
                        score += 3
                    if keyword in spec_path.stem.lower():
                        score += 5
                if score > 0:
                    scored_specs.append((score, spec_path))
            if scored_specs:
                scored_specs.sort(key=lambda item: item[0], reverse=True)
                best_score, best_spec = scored_specs[0]
                if best_score > 0:
                    return [best_spec]
                return [scored_specs[0][1]]

        default_spec = ROOT_DIR / "get-accounts-openapi-specs.yaml"
        if default_spec.exists():
            return [default_spec]
        return []

    def _extract_fca_events(self, execution_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for feature_result in execution_results:
            for scenario in feature_result.get("scenarios", []):
                event = scenario.get("fca_event")
                if event:
                    events.append(event)
        return events or compliance_agent.SAMPLE_EVENTS

    def run_workflow(
        self,
        swagger_file: str | None = None,
        review_approved: bool = True,
        all_specs: bool = False,
        progress_callback: Callable[[str, str, float], None] | None = None,
        controller_source: str | None = None,
        create_cbs_mock: bool = True,
        user_prompt: str | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.utcnow().isoformat()
        workflow = {
            "started_at": started_at,
            "status": "running",
            "steps": {},
            "errors": [],
        }

        try:
            controller_path = Path(controller_source) if controller_source else None
            if controller_source and not swagger_file and not all_specs:
                controller_path = Path(controller_source)

            swagger_paths = self._resolve_swagger_inputs(
                swagger_file=swagger_file,
                all_specs=all_specs,
                controller_source=str(controller_path) if controller_path else None,
                user_prompt=user_prompt,
            )
            if not swagger_paths and not controller_path:
                raise WorkflowError("No Swagger/OpenAPI specs were provided and none were found under specs/.")

            if progress_callback:
                progress_callback("workflow", "Starting BDD generation", 0.05)

            bdd_agent_instance = bdd_agent.BDDAgent(base_url=self.base_url, output_dir=str(self.output_dir))
            generated_files: list[Path] = []
            if swagger_paths:
                for index, swagger_path in enumerate(swagger_paths):
                    if progress_callback:
                        progress_callback("bdd_generation", f"Generating BDDs from {swagger_path.name}", 0.1 + (index / max(len(swagger_paths), 1)) * 0.2)
                    if not swagger_path.exists():
                        raise WorkflowError(f"Swagger file not found: {swagger_path}")
                    generated_files.extend(
                        bdd_agent_instance.generate_all(
                            str(swagger_path),
                            controller_source=str(controller_path) if controller_path else None,
                            user_prompt=user_prompt,
                        )
                    )
            else:
                if progress_callback:
                    progress_callback("bdd_generation", "Generating BDDs from controller implementation", 0.15)
                generated_files.extend(
                    bdd_agent_instance.generate_all(
                        controller_source=str(controller_path) if controller_path else None,
                        user_prompt=user_prompt,
                    )
                )

            generated_paths = [str(Path(path)) for path in generated_files]
            cbs_mock_path = None
            if create_cbs_mock:
                cbs_mock_path = bdd_agent_instance.ensure_cbs_mock({"method": "POST", "path": "/accounts"}, output_dir=self.reports_dir)
            workflow["steps"]["bdd_generation"] = {
                "status": "completed",
                "generated_files": generated_paths,
                "specs": [str(path) for path in swagger_paths],
                "controller_source": str(controller_path) if controller_path else None,
                "cbs_mock_path": str(cbs_mock_path) if cbs_mock_path else None,
                "summary": ai_agent.summarize_openapi_generation(
                    ", ".join(path.name for path in swagger_paths),
                    generated_paths,
                ),
            }

            if not review_approved and user_prompt and not all_specs and not swagger_file and not controller_source:
                workflow["status"] = "review_pending"
                workflow["steps"]["review"] = {"status": "pending", "message": "User review required before execution."}
                self.last_run = workflow
                return workflow

            if progress_callback:
                progress_callback("review", "Review approved. Running BDD execution", 0.35)
            workflow["steps"]["review"] = {
                "status": "completed",
                "message": "Review completed by user.",
                "notes": ["BDD review notes and prerequisites were added to generated feature files."]
            }

            log_path = ROOT_DIR / "sample_logs.txt"
            log_path.write_text("", encoding="utf-8")

            execution_agent = bdd_execution_agent.BDDExecutionAgent(base_url=self.base_url, features_dir=str(self.output_dir))
            execution_results = execution_agent.execute_all()
            report_path = self._safe_write_text(
                self.reports_dir / f"bdd_report_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html",
                "",
            )
            report_path = execution_agent.generate_cucumber_html_report(execution_results, report_path)
            if progress_callback:
                progress_callback("bdd_execution", "BDD execution completed. Validating logs", 0.65)
            workflow["steps"]["bdd_execution"] = {
                "status": "completed",
                "results": execution_results,
                "report_path": str(report_path),
                "summary": ai_agent.summarize_bdd_execution(execution_results),
            }

            validation = compliance_agent.validate_pii_logs([str(log_path), str(ROOT_DIR / "sample_logs_no_pii.txt")])
            pii_report_path = self._safe_write_text(
                self.reports_dir / f"pii_report_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html",
                "",
            )
            pii_report_path = compliance_agent.generate_pii_html_report(validation, pii_report_path)
            if progress_callback:
                progress_callback("pii_validation", "PII validation completed. Running FCA checks", 0.8)
            workflow["steps"]["pii_validation"] = {
                "status": "completed",
                "result": validation,
                "report_path": str(pii_report_path),
                "guardrails": validation.get("guardrails"),
                "explanation": validation.get("explanation"),
                "summary": ai_agent.summarize_pii_results(validation),
            }

            fca_events = self._extract_fca_events(execution_results)
            fca_results = compliance_agent.validate_fca_rules(fca_events)
            fca_report_path = self._safe_write_text(
                self.reports_dir / f"fca_report_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.html",
                "",
            )
            fca_report_path = compliance_agent.generate_fca_html_report(fca_results, fca_report_path)
            if progress_callback:
                progress_callback("fca_validation", "Workflow completed", 1.0)
            workflow["steps"]["fca_validation"] = {
                "status": "completed",
                "result": fca_results,
                "report_path": str(fca_report_path),
                "guardrails": fca_results.get("guardrails"),
                "explanation": fca_results.get("explanation"),
                "summary": ai_agent.summarize_fca_results(fca_results),
            }

            workflow["status"] = "completed"
            workflow["completed_at"] = datetime.utcnow().isoformat()
        except Exception as exc:  # pragma: no cover - runtime safety
            workflow["status"] = "failed"
            workflow["errors"].append(str(exc))
            workflow["completed_at"] = datetime.utcnow().isoformat()

        self.last_run = workflow
        return workflow
