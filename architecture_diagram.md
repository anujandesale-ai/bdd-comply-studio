# Compliance BDDs AI Studio Architecture

```mermaid
flowchart LR
    User[User / Presenter] --> UI[Streamlit UI]
    UI --> Prompt[Freeform BDD Prompt]
    UI --> Input[Swagger / OpenAPI / Controller Source]
    UI --> Review[Review & Approval Flow]

    Prompt --> Workflow[WorkflowOrchestrator]
    Input --> Workflow
    Review --> Workflow

    Workflow --> BDD[BDDAgent]
    Workflow --> Exec[BDDExecutionAgent]
    Workflow --> Compliance[ComplianceAgent]
    Workflow --> AI[AI Agent / LLM]

    BDD --> Features[Generated .feature files]
    AI --> Guidance[Prompt-guided notes and summaries]
    BDD --> Guidance

    Features --> Exec
    Exec --> ExecReport[BDD Execution Report]
    Exec --> FCAEvents[FCA Events]

    Compliance --> PIIReport[PII Validation Report]
    Compliance --> FCAReport[FCA Validation Report]

    Workflow --> FinalResult[Workflow Result / Review State]
    FinalResult --> UI
```

## Presentation note
Use this diagram to explain how the app turns a user prompt and API input into generated BDDs, reviewable artifacts, and compliance reports.
