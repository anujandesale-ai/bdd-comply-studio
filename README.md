# Finance Technical Content Creator

This sample project contains:

- A small Python banking microservice simulation (`backend/sample_banking_service.py`)
- An automatic BDD generator agent for Karate/Cucumber feature files (`backend/bdd_agent.py`)
- A rule-based FCA and PII compliance validation agent (`backend/compliance_agent.py`)
- A frontend simulation UI with clickable actions and audit trail (`backend/frontend_server.py`, `frontend/index.html`)

## Getting started

### 1. Activate the virtual environment

From the project root:

```bash
cd /Users/anujadesale/Documents/agentic-ai/capstone-projects/bdd-comply-studio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the backend service

```bash
python3 backend/sample_banking_service.py
```

This runs the sample banking API on port 8081.

### 3. Start the Streamlit frontend

In a second terminal, with the same virtual environment activated:

```bash
cd /Users/anujadesale/Documents/agentic-ai/capstone-projects/bdd-comply-studio
source .venv/bin/activate
python3 -m streamlit run frontend/streamlit_app.py --server.headless true --server.port 8502
```

Then open:

```bash
http://localhost:8502
```

### 4. Use the UI to run the workflow

- Upload a Swagger/JSON spec or use the bundled specs
- Run the full workflow
- Review generated BDDs and approve them
- Continue the workflow to generate reports

### 5. Optional: run validation commands directly

```bash
python3 backend/bdd_agent.py generate
python3 backend/bdd_execution_agent.py
python3 backend/compliance_agent.py validate-pii
python3 backend/compliance_agent.py validate-fca
```

The generated BDD files are written to `features/`.

## Notes

- This project uses only Python standard library modules.
- The generated BDD files are compatible with Karate syntax and describe common banking API flows.
