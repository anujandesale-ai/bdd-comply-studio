import os
import tempfile
from pathlib import Path

import streamlit as st

from backend.workflow import WorkflowOrchestrator


@st.cache_resource
def get_orchestrator() -> WorkflowOrchestrator:
    return WorkflowOrchestrator(base_url=os.getenv("SERVICE_URL", "http://localhost:8081"))


def _render_step_status(step_name: str, label: str, completed: bool, current: bool) -> None:
    # Render a more visible status badge with color and percentage
    status = "COMPLETED" if completed else "RUNNING" if current else "PENDING"
    percent = 100 if completed else 50 if current else 0
    color = "#047857" if completed else "#b45309" if current else "#6b7280"
    st.markdown(
        f"<div style='padding:8px;border-radius:8px;margin-bottom:6px;background:#ffffff;'>"
        f"<strong>{label}</strong> — <span style='color:{color};font-weight:700'>{status} ({percent}%)</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _step_is_completed(status: str | None) -> bool:
    return status in {"completed", "approved"}


def _get_step_state(last_result: dict | None, step_name: str) -> tuple[bool, bool]:
    if not last_result:
        return False, False
    step_result = last_result.get("steps", {}).get(step_name, {})
    status = step_result.get("status")
    completed = _step_is_completed(status)
    current = not completed and status in {"running", "pending", "review_pending"}
    return completed, current


def main() -> None:
    st.set_page_config(page_title="Compliance BDDs AI Studio", layout="wide")
    st.title("Compliance BDDs AI Studio")
    st.caption(
        "Upload a Swagger file, or run the workflow for all bundled specs. Review generated BDDs, execute them, validate compliance, and download reports in one guided workflow."
    )

    orchestrator = get_orchestrator()

    steps = [
        ("bdd_generation", "BDD generation"),
        ("review", "Review approval"),
        ("bdd_execution", "BDD execution"),
        ("pii_validation", "PII validation"),
        ("fca_validation", "FCA validation"),
    ]

    progress_placeholder = st.sidebar.empty()
    progress_caption = st.sidebar.empty()

    def update_progress(step_name: str, message: str, progress: float) -> None:
        percent = int(progress * 100)
        st.session_state["workflow_progress"] = percent
        st.session_state["workflow_status_text"] = f"{step_name}: {message}"
        progress_placeholder.progress(percent)
        progress_caption.caption(st.session_state["workflow_status_text"])

    with st.sidebar:
        st.header("Workflow")
        if st.button("Reset workflow", use_container_width=True, key="reset_workflow"):
            for key in ["last_result", "review_approved", "workflow_progress", "workflow_status_text", "last_bdd_source", "swagger_upload"]:
                st.session_state.pop(key, None)
            st.success("Workflow state reset.")
        last_result = st.session_state.get("last_result")
        for step_name, label in steps:
            completed, current = _get_step_state(last_result, step_name)
            icon = "✅" if completed else "⏳" if current else "○"
            st.markdown(f"**{icon} {label}**")
        st.markdown("---")
        progress_value = st.session_state.get("workflow_progress", 0)
        if last_result:
            if last_result.get("status") == "completed":
                progress_value = 100
            else:
                completed_steps = sum(1 for step_name, _ in steps if _step_is_completed(last_result.get("steps", {}).get(step_name, {}).get("status")))
                progress_value = int((completed_steps / len(steps)) * 100)
        progress_placeholder.progress(progress_value)
        progress_caption.caption(st.session_state.get("workflow_status_text", f"Workflow completion: {progress_value}%"))
        st.write("Use the controls on the right to upload a spec or run all bundled specs.")

    selected_source = st.session_state.get("bdd_source", "Upload Swagger JSON")
    if "last_bdd_source" not in st.session_state:
        st.session_state["last_bdd_source"] = selected_source
    bdd_source = st.radio(
        "Source of BDD generation",
        ["Upload Swagger JSON", "Use all specs under specs/", "Use REST controller implementation"],
        index=0,
        key="bdd_source",
    )

    if st.session_state.get("last_bdd_source") != bdd_source:
        for key in ["last_result", "review_approved", "workflow_progress", "workflow_status_text", "swagger_upload"]:
            st.session_state.pop(key, None)
        st.session_state["last_bdd_source"] = bdd_source

    uploaded_file = None
    temp_path = None
    all_specs = False
    controller_source = None

    if bdd_source == "Upload Swagger JSON":
        uploaded_file = st.file_uploader(
            "Upload OpenAPI/Swagger JSON",
            type=["json"],
            accept_multiple_files=False,
            key="swagger_upload",
        )
        if uploaded_file is None:
            st.info("Upload a Swagger/JSON file to start the workflow.")
            return
        upload_dir = Path.cwd() / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / uploaded_file.name
        dest.write_bytes(uploaded_file.getvalue())
        temp_path = str(dest)
        st.success(f"Uploaded {uploaded_file.name} for workflow processing.")
    elif bdd_source == "Use all specs under specs/":
        all_specs = True
    else:
        controller_source = str((Path(__file__).resolve().parent / "backend" / "sample_banking_service.py"))
        st.info("BDD generation will use the REST controller implementation from sample_banking_service.py.")

    create_cbs_mock = st.checkbox("Create a CBS response mock for downstream validation", value=True, key="create_cbs_mock")

    if "last_result" in st.session_state:
        st.info("A previous workflow run is available below. You can launch another run with a new upload.")

    review_approved = st.session_state.get("review_approved", False)

    if st.button("Run full workflow", key="run_full_workflow"):
        review_approved = st.session_state.get("review_approved", False)
        st.session_state["workflow_progress"] = 0
        st.session_state["workflow_status_text"] = "Starting workflow"
        with st.spinner("Generating BDDs and running the full compliance workflow..."):
            try:
                progress_box = st.empty()

                def progress_callback(step_name: str, message: str, progress: float) -> None:
                    progress_box.info(f"{step_name}: {message} ({int(progress * 100)}%)")
                    update_progress(step_name, message, progress)

                result = orchestrator.run_workflow(
                    swagger_file=temp_path,
                    review_approved=review_approved,
                    all_specs=all_specs,
                    progress_callback=progress_callback,
                    controller_source=controller_source,
                    create_cbs_mock=create_cbs_mock,
                )
            except Exception as exc:  # pragma: no cover - UI safety
                st.error(f"Workflow failed: {exc}")
                st.stop()

        st.session_state["last_result"] = result
        st.session_state["workflow_progress"] = 100 if result.get("status") == "completed" else 25
        st.session_state["workflow_status_text"] = "Workflow completed" if result.get("status") == "completed" else "Review required"
        if result.get("status") == "review_pending":
            st.info("The workflow paused for review. Tick the checkbox and click Continue workflow to proceed.")
        elif result.get("status") == "completed":
            st.success("Workflow completed successfully.")
        else:
            st.error("Workflow failed. Review the errors below.")
            for error in result.get("errors", []):
                st.write(error)

    review_approved = st.checkbox(
        "I reviewed the generated BDDs and want to continue",
        value=review_approved,
        key="review_approved",
    )

    if st.session_state.get("last_result", {}).get("status") == "review_pending" and review_approved:
        if st.button("Continue workflow", key="continue_workflow"):
            st.session_state["workflow_progress"] = 0
            st.session_state["workflow_status_text"] = "Continuing workflow"
            with st.spinner("Continuing the workflow after review..."):
                try:
                    result = orchestrator.run_workflow(
                        swagger_file=temp_path,
                        review_approved=True,
                        all_specs=all_specs,
                        progress_callback=update_progress,
                        controller_source=controller_source,
                        create_cbs_mock=create_cbs_mock,
                    )
                except Exception as exc:  # pragma: no cover - UI safety
                    st.error(f"Workflow failed while continuing: {exc}")
                    st.stop()
            st.session_state["last_result"] = result
            if result.get("status") == "completed":
                st.success("Workflow completed successfully after review.")
            else:
                st.error("Workflow did not complete after review.")

    # Show generated artifacts and downloadable reports (avoid duplicating sidebar progress)
    if "last_result" in st.session_state:
        result = st.session_state["last_result"]

        if result.get("steps", {}).get("bdd_generation") and not review_approved:
            generated_files = result["steps"]["bdd_generation"].get("generated_files", [])
            with st.expander("Review generated BDDs", expanded=True):
                for feature_path in generated_files:
                    feature_file = Path(feature_path)
                    if feature_file.exists():
                        st.subheader(feature_file.name)
                        st.code(feature_file.read_text(encoding="utf-8"), language="gherkin")

        if result.get("steps", {}).get("bdd_execution"):
            report_path = result["steps"]["bdd_execution"].get("report_path")
            if report_path and Path(report_path).exists():
                st.download_button(
                    "Download BDD execution report",
                    data=Path(report_path).read_bytes(),
                    file_name=Path(report_path).name,
                    mime="text/html",
                    key="download_bdd_report",
                )

        if result.get("steps", {}).get("pii_validation"):
            report_path = result["steps"]["pii_validation"].get("report_path")
            if report_path and Path(report_path).exists():
                st.download_button(
                    "Download PII validation report",
                    data=Path(report_path).read_bytes(),
                    file_name=Path(report_path).name,
                    mime="text/html",
                    key="download_pii_report",
                )

        if result.get("steps", {}).get("fca_validation"):
            report_path = result["steps"]["fca_validation"].get("report_path")
            if report_path and Path(report_path).exists():
                st.download_button(
                    "Download FCA validation report",
                    data=Path(report_path).read_bytes(),
                    file_name=Path(report_path).name,
                    mime="text/html",
                    key="download_fca_report",
                )


if __name__ == "__main__":
    main()
