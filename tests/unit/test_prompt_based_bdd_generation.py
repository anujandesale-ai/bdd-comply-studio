from pathlib import Path
from unittest.mock import patch

from backend.bdd_agent import BDDAgent


def test_generate_feature_uses_user_prompt_guidance(tmp_path):
    agent = BDDAgent(output_dir=str(tmp_path))
    api_info = {
        "method": "GET",
        "path": "/accounts",
        "title": "List accounts",
        "description": "Retrieve accounts",
        "request_example": None,
        "response_example": None,
        "path_params": {},
        "query_params": {},
    }

    with patch("backend.ai_agent._llm_text", return_value="Suggested scenario: Verify account listing"):
        feature_path = agent.generate_feature(
            api_info,
            controller_source=None,
            user_prompt="Generate BDDs for account listing",
        )

    content = feature_path.read_text(encoding="utf-8")
    assert "Suggested scenario: Verify account listing" in content
