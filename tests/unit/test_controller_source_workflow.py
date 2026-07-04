from pathlib import Path

from backend.workflow import WorkflowOrchestrator


def test_controller_source_workflow_does_not_require_swagger(tmp_path):
    root_dir = Path(__file__).resolve().parents[2]
    orchestrator = WorkflowOrchestrator(
        base_url="http://localhost:8081",
        output_dir=str(tmp_path / "features"),
    )

    result = orchestrator.run_workflow(
        swagger_file=None,
        review_approved=False,
        all_specs=False,
        controller_source=str(root_dir / "backend" / "sample_banking_service.py"),
        create_cbs_mock=False,
    )

    assert result["status"] == "review_pending"
    assert result["steps"]["bdd_generation"]["status"] == "completed"
    assert result["steps"]["review"]["status"] == "pending"
