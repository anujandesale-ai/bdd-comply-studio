import difflib
import os
import subprocess
from pathlib import Path

import streamlit as st

from backend.workflow import WorkflowOrchestrator


@st.cache_resource
def get_orchestrator() -> WorkflowOrchestrator:
    return WorkflowOrchestrator(base_url=os.getenv("SERVICE_URL", "http://localhost:8081"))


def _render_step_status(step_name: str, label: str, completed: bool, current: bool) -> None:
    status = "COMPLETED" if completed else "RUNNING" if current else "PENDING"
    percent = 100 if completed else 50 if current else 0
    state_class = "completed" if completed else "current" if current else "pending"
    st.markdown(
        f"<div class='workflow-card {state_class}'>"
        f"<div class='step-line'>"
        f"<div><strong>{label}</strong></div>"
        f"<div class='step-badge {state_class}'>{status}</div>"
        f"</div>"
        f"<div class='step-progress'>{percent}%</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _step_is_completed(status: str | None) -> bool:
    return status in {"completed", "approved"}


def _safe_rerun() -> None:
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.stop()


def _get_step_state(last_result: dict | None, step_name: str, review_approved: bool = False) -> tuple[bool, bool]:
    if not last_result:
        return False, False
    step_result = last_result.get("steps", {}).get(step_name, {})
    status = step_result.get("status")
    if step_name == "review" and status in {"pending", "review_pending"} and review_approved:
        return True, False
    completed = _step_is_completed(status)
    current = not completed and status in {"running", "pending", "review_pending"}
    return completed, current


def main() -> None:
    st.set_page_config(page_title="Compliance BDDs AI Studio", layout="wide")
    st.markdown(
        '''<style>
            .workflow-card { padding: 14px 16px; border-radius: 16px; margin-bottom: 10px; box-shadow: 0 12px 30px rgba(15,23,42,0.12); border: 1px solid rgba(255,255,255,0.08); background: rgba(15,23,42,0.9); }
            .workflow-card.completed { border-color: #10b981; }
            .workflow-card.current { border-color: #f59e0b; }
            .workflow-card.pending { border-color: #6b7280; }
            .step-line { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
            .step-badge { font-size: 0.78rem; font-weight: 700; letter-spacing: 0.04em; padding: 6px 10px; border-radius: 999px; }
            .step-badge.completed { background: rgba(16,185,129,0.16); color: #a7f3d0; }
            .step-badge.current { background: rgba(245,158,11,0.16); color: #fde68a; }
            .step-badge.pending { background: rgba(107,114,128,0.16); color: #d1d5db; }
            .step-progress { margin-top: 10px; font-size: 0.92rem; color: #d1d5db; }
            .review-card { border-radius: 16px; padding: 16px; margin-bottom: 18px; background: rgba(30,41,59,0.9); border: 1px solid rgba(255,255,255,0.08); }
            .status-banner { border-radius: 14px; border: 1px solid rgba(255,255,255,0.08); padding: 16px; background: rgba(15,23,42,0.85); margin-bottom: 18px; }
            .status-text { font-size: 0.95rem; color: #e5e7eb; }
            .animated-status { animation: pulse-status 1.2s ease-in-out infinite; }
            @keyframes pulse-status { 0%, 100% { opacity: 0.85; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-1px); } }
            .stButton>button { border-radius: 14px; padding: 0.95rem 1.4rem; font-weight: 700; color: #fff; background: linear-gradient(135deg, #0ea5e9, #2563eb); border: 1px solid rgba(255,255,255,0.14); box-shadow: 0 18px 40px rgba(15,23,42,0.12); transition: transform 0.18s ease, box-shadow 0.18s ease; }
            .stButton>button:hover { transform: translateY(-1px); box-shadow: 0 20px 48px rgba(15,23,42,0.18); }
            .stButton>button:disabled { opacity: 0.6; cursor: not-allowed; box-shadow: none; }
        </style>''',
        unsafe_allow_html=True,
    )
    st.title("Compliance BDDs AI Studio")
    st.caption(
        "Upload a Swagger file, run the workflow, review generated BDDs, and export compliance reports with a polished step-by-step experience."
    )

    orchestrator = get_orchestrator()

    steps = [
        ("bdd_generation", "BDD generation"),
        ("review", "Review and approve"),
        ("bdd_execution", "BDD execution"),
        ("pii_validation", "PII validation"),
        ("fca_validation", "FCA validation"),
    ]

    progress_placeholder = st.sidebar.empty()
    progress_caption = st.sidebar.empty()

    def update_progress(step_name: str, message: str, progress: float) -> None:
        step_labels = {
            "workflow": "STEP 0",
            "bdd_generation": "STEP 1",
            "review": "STEP 2",
            "bdd_execution": "STEP 3",
            "pii_validation": "STEP 4",
            "fca_validation": "STEP 5",
        }
        friendly_step = step_labels.get(step_name, step_name.replace("_", " ").title())
        percent = int(progress * 100)
        st.session_state["workflow_progress"] = percent
        st.session_state["workflow_status_text"] = f"{friendly_step} : {message}"
        progress_placeholder.progress(percent)
        animated = step_name in {"bdd_execution", "pii_validation", "fca_validation"} and percent < 100
        status_html = (
            f"<div class='status-text animated-status'>{friendly_step} : {message}</div>"
            if animated
            else f"<div class='status-text'>{friendly_step} : {message}</div>"
        )
        progress_caption.markdown(status_html, unsafe_allow_html=True)

    with st.sidebar:
        st.header("Workflow")
        if st.button("Reset workflow", use_container_width=True, key="reset_workflow"):
            for key in [
                "last_result",
                "review_approved",
                "review_mode",
                "workflow_progress",
                "workflow_status_text",
                "last_bdd_source",
                "bdd_source",
                "swagger_upload",
            ]:
                st.session_state.pop(key, None)
            st.success("Workflow state reset.")
            _safe_rerun()
        last_result = st.session_state.get("last_result")
        review_approved = st.session_state.get("review_approved", False)
        current_phase = st.session_state.get("workflow_current_step")
        for step_name, label in steps:
            completed, current = _get_step_state(last_result, step_name, review_approved=review_approved)
            if st.session_state.get("workflow_running", False) and current_phase == step_name:
                completed = False
                current = True
            _render_step_status(step_name, label, completed, current)
        st.markdown("---")
        st.subheader("Workflow progress")
        progress_value = st.session_state.get("workflow_progress", 0)
        if last_result:
            if last_result.get("status") == "completed":
                progress_value = 100
            else:
                completed_steps = sum(1 for step_name, _ in steps if _step_is_completed(last_result.get("steps", {}).get(step_name, {}).get("status")))
                progress_value = int((completed_steps / len(steps)) * 100)
        progress_placeholder.progress(progress_value)
        progress_caption.caption(st.session_state.get("workflow_status_text", f"Workflow completion: {progress_value}%"))
        st.write("Use the controls on the right to upload a spec or run bundled specs, then review and continue the workflow.")

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

    create_cbs_mock = True

    if "last_result" in st.session_state:
        st.info("A previous workflow run is available below. Upload a new spec or run the workflow again to refresh state.")

    review_approved = st.session_state.get("review_approved", False)
    run_full_enabled = uploaded_file is not None or all_specs or controller_source is not None
    if not run_full_enabled:
        st.warning("Upload a Swagger spec or choose a source before running the workflow.")

    if st.button("Run full workflow", key="run_full_workflow", disabled=not run_full_enabled):
        st.session_state["review_approved"] = False
        st.session_state["workflow_running"] = True
        st.session_state["workflow_current_step"] = "bdd_generation"
        st.session_state["workflow_progress"] = 0
        st.session_state["workflow_status_text"] = "Starting workflow"
        with st.spinner("Generating BDDs and running the full compliance workflow..."):
            try:
                progress_box = st.empty()

                def progress_callback(step_name: str, message: str, progress: float) -> None:
                    st.session_state["workflow_current_step"] = step_name
                    message_label = {
                        "workflow": "STEP 0",
                        "bdd_generation": "STEP 1",
                        "review": "STEP 2",
                        "bdd_execution": "STEP 3",
                        "pii_validation": "STEP 4",
                        "fca_validation": "STEP 5",
                    }.get(step_name, step_name.replace("_", " ").title())
                    progress_box.info(f"{message_label} : {message}")
                    update_progress(step_name, message, progress)

                result = orchestrator.run_workflow(
                    swagger_file=temp_path,
                    review_approved=False,
                    all_specs=all_specs,
                    progress_callback=progress_callback,
                    controller_source=controller_source,
                    create_cbs_mock=create_cbs_mock,
                )
            except Exception as exc:  # pragma: no cover - UI safety
                st.error(f"Workflow failed: {exc}")
                st.stop()

        st.session_state["last_result"] = result
        st.session_state["workflow_running"] = False
        st.session_state["workflow_current_step"] = None
        st.session_state["workflow_progress"] = 100 if result.get("status") == "completed" else 25
        st.session_state["workflow_status_text"] = "Workflow completed" if result.get("status") == "completed" else "Review required"
        if result.get("status") == "review_pending":
            st.info("The workflow paused for review. Open the Review tab to approve it and continue.")
        elif result.get("status") == "completed":
            st.success("Workflow completed successfully.")
        else:
            st.error("Workflow failed. Review the errors below.")
            for error in result.get("errors", []):
                st.write(error)
        _safe_rerun()

    if st.session_state.get("workflow_status_text"):
        status_text = st.session_state["workflow_status_text"]
        progress_value = st.session_state.get("workflow_progress", 0)
        st.markdown(
            f"<div class='status-banner'><div class='status-text'><strong>{status_text}</strong> — {progress_value}% complete</div></div>",
            unsafe_allow_html=True,
        )

    workflow_tab, review_tab = st.tabs(["Workflow", "Review generated BDDs"])

    with workflow_tab:
        if st.session_state.get("workflow_status_text"):
            st.markdown(
                f"<div class='status-banner'><div class='status-text'>{st.session_state['workflow_status_text']}</div></div>",
                unsafe_allow_html=True,
            )

        if "last_result" not in st.session_state:
            st.info("Run the workflow first to generate BDDs and enable review.")
        else:
            result = st.session_state["last_result"]
            review_ready = st.session_state.get("review_approved", False) and result.get("status") == "review_pending"
            if review_ready:
                st.success("BDDs has been approved. Continue workflow below to execute the remaining stages.")
                if st.button("Continue workflow", key="continue_workflow"):
                    st.session_state["workflow_running"] = True
                    st.session_state["workflow_current_step"] = "bdd_execution"
                    st.session_state["workflow_progress"] = 0
                    st.session_state["workflow_status_text"] = "Continuing workflow after review"
                    with st.spinner("Executing BDD execution, PII validation, and FCA validation..."):
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
                            st.error(f"Workflow failed during continuation: {exc}")
                            st.stop()
                    st.session_state["last_result"] = result
                    st.session_state["workflow_running"] = False
                    st.session_state["workflow_current_step"] = None
                    st.session_state["workflow_progress"] = 100 if result.get("status") == "completed" else 25
                    st.session_state["workflow_status_text"] = "Workflow completed" if result.get("status") == "completed" else "Review required"
                    if result.get("status") == "completed":
                        st.success("Workflow completed successfully after review.")
                    else:
                        st.error("Workflow did not complete after review.")
                    _safe_rerun()

            if result.get("status") == "completed":
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
            else:
                st.info("Continue the workflow to complete BDD execution, PII validation, and FCA validation.")

    with review_tab:
        if "last_result" not in st.session_state:
            st.info("Run the workflow first to generate BDDs before reviewing them.")
        else:
            st.info("Review generated BDDs to approve and continue the workflow.")
            result = st.session_state["last_result"]
            review_mode = st.radio(
                "Review mode",
                ["In-place", "GitHub"],
                index=0,
                key="review_mode",
                help="Choose whether to review generated BDDs in the app or prepare them for a GitHub PR.",
            )

            header_col, button_col = st.columns([3, 1])
            with header_col:
                st.markdown(
                    "<div class='review-card'><strong>Review generated BDDs</strong><br />Use the button in the top-right to approve the BDDs and return to the workflow.</div>",
                    unsafe_allow_html=True,
                )
            with button_col:
                if st.button("Approve Review and return to workflow", key="approve_and_continue", use_container_width=True):
                    st.session_state["review_approved"] = True
                    st.session_state["workflow_progress"] = 0
                    st.session_state["workflow_status_text"] = "BDDs approved. Returning to Workflow tab."
                    last_result = st.session_state.get("last_result")
                    if last_result and last_result.get("steps", {}).get("review"):
                        last_result["steps"]["review"]["status"] = "completed"
                        last_result["steps"]["review"]["message"] = "User review approved. Ready to continue."
                        st.session_state["last_result"] = last_result
                    _safe_rerun()

            if result.get("steps", {}).get("bdd_generation"):
                generated_files = result["steps"]["bdd_generation"].get("generated_files", [])
                if generated_files:
                    for feature_path in generated_files:
                        feature_file = Path(feature_path)
                        if feature_file.exists():
                            st.subheader(feature_file.name)
                            if review_mode == "GitHub":
                                st.markdown("**Git diff preview:**")
                                _render_git_diff(feature_file)
                            else:
                                st.code(feature_file.read_text(encoding="utf-8"), language="gherkin")
                else:
                    st.info("No generated BDD files were returned by the workflow.")
            else:
                st.info("No generated BDD files were returned by the workflow.")

    def _git_head_content(path: Path) -> list[str] | None:
        repo_root = Path(__file__).resolve().parents[1]
        try:
            relative_path = path.relative_to(repo_root)
        except ValueError:
            return None
        try:
            result = subprocess.run(
                ["git", "show", f"HEAD:{relative_path.as_posix()}"],
                capture_output=True,
                text=True,
                cwd=repo_root,
                check=True,
            )
            return result.stdout.splitlines()
        except subprocess.CalledProcessError:
            return None

    def _render_git_diff(feature_path: Path) -> None:
        existing_lines = _git_head_content(feature_path)
        generated_lines = feature_path.read_text(encoding="utf-8").splitlines()
        if existing_lines is None:
            st.info("Git diff not available for this file. Showing generated BDD content instead.")
            st.code("\n".join(generated_lines), language="gherkin")
            return
        diff_lines = list(difflib.unified_diff(
            existing_lines,
            generated_lines,
            fromfile=f"HEAD:{feature_path.name}",
            tofile=f"WORKTREE:{feature_path.name}",
            lineterm="",
        ))
        if diff_lines:
            st.code("\n".join(diff_lines), language="text")
        else:
            st.success("Generated BDD file matches the current Git HEAD version.")



if __name__ == "__main__":
    main()
