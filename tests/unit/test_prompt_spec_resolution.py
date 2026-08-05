from pathlib import Path

from backend.workflow import WorkflowOrchestrator

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_resolve_swagger_inputs_uses_prompt_to_find_matching_spec(tmp_path):
    orchestrator = WorkflowOrchestrator(output_dir=str(tmp_path))

    resolved = orchestrator._resolve_swagger_inputs(user_prompt="Generate BDDs for customer onboarding")

    assert resolved
    assert any(path.name == "customer-onboarding.json" for path in resolved)
