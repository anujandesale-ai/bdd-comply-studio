# Finance Technical Content Creator

This sample project contains:

- A small Python banking microservice simulation (`backend/sample_banking_service.py`)
- An automatic BDD generator agent for Karate/Cucumber feature files (`backend/bdd_agent.py`)
- A rule-based FCA and PII compliance validation agent (`backend/compliance_agent.py`)
- A frontend simulation UI with clickable actions and audit trail (`backend/frontend_server.py`, `frontend/index.html`)

## Getting started

1. Run the sample banking service:

```bash
cd /Users/anujadesale/savings-hackthon/finance-technical-content-creator
python3 backend/sample_banking_service.py
```

2. Start the frontend simulation UI:

```bash
python3 backend/frontend_server.py
```

3. Open your browser to:

```bash
http://localhost:8082
```

4. Use the UI buttons to:

- fetch accounts and products
- create an account
- search loan offers
- generate Karate BDD feature files
- execute generated BDDs against the sample service
- validate PII across both sample logs
- run FCA compliance validation

5. Validate workflows from the command line if desired:

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
