import json
import logging
import os
import re

from backend.prompts.llm_prompts import (
    BDD_GENERATION_PROMPT,
    BDD_REVIEW_PROMPT,
    FCA_VALIDATION_PROMPT,
    PII_VALIDATION_PROMPT,
)

try:
    import openai
except ImportError:  # pragma: no cover - optional dependency
    openai = None

try:  # pragma: no cover - optional dependency
    import google.generativeai as genai
except ImportError:  # pragma: no cover - optional dependency
    genai = None

logger = logging.getLogger(__name__)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GENAI_MODEL = os.getenv("GENAI_MODEL", "models/text-bison-001")
GENAI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")

if OPENAI_API_KEY and openai is not None:
    try:
        openai.api_key = OPENAI_API_KEY
        logger.info("Using OpenAI LLM model: %s", OPENAI_MODEL)
    except Exception as exc:  # pragma: no cover - runtime only
        logger.warning("OpenAI configuration failed: %s", exc)

if GENAI_API_KEY and genai is not None:
    try:
        genai.configure(api_key=GENAI_API_KEY)
    except Exception as exc:  # pragma: no cover - runtime only
        logger.warning("Gemini configuration failed: %s", exc)


def _guardrail_text(text: str, *, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return fallback
    if len(cleaned) > 1400:
        return cleaned[:1397] + "..."
    return cleaned


def _fallback_text(prompt: str, *, context: str = "") -> str:
    if "PII" in prompt.upper():
        return _guardrail_text("PII validation completed using local rules because no LLM service is available.", fallback="PII validation completed using local rules because no LLM service is available.")
    if "FCA" in prompt.upper():
        return _guardrail_text("FCA validation completed using local rules because no LLM service is available.", fallback="FCA validation completed using local rules because no LLM service is available.")
    if "BDD" in prompt.upper() or "TEST" in prompt.upper():
        return _guardrail_text("BDD execution completed using deterministic local analysis because no LLM service is available.", fallback="BDD execution completed using deterministic local analysis because no LLM service is available.")
    return _guardrail_text(f"Workflow summary generated locally. {context}".strip(), fallback="Workflow summary generated locally.")


def _openai_text(prompt: str, temperature: float = 0.2, max_output_tokens: int = 256) -> str:
    if openai is None:
        return "OpenAI client library is not installed. Install the openai package to use OPENAI_API_KEY."
    if not OPENAI_API_KEY:
        return "OPENAI_API_KEY not configured. Set OPENAI_API_KEY to enable OpenAI summaries."

    try:
        response = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_output_tokens,
        )
        content = response.choices[0].message.content.strip()
        logger.debug("OpenAI response received: %d characters", len(content))
        return _guardrail_text(content, fallback=_fallback_text(prompt, context="OpenAI response was empty."))
    except Exception as exc:  # pragma: no cover - runtime only
        logger.warning("OpenAI call failed: %s", exc)
        return _fallback_text(prompt, context="OpenAI request failed.")


def _gemini_text(prompt: str, temperature: float = 0.2, max_output_tokens: int = 256) -> str:
    if not GENAI_API_KEY or genai is None:
        return "Gemini API key not configured or the SDK is unavailable."

    try:
        response = genai.generate_text(
            model=GENAI_MODEL,
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if hasattr(response, "text"):
            return _guardrail_text(response.text.strip(), fallback=_fallback_text(prompt, context="Gemini response was empty."))
        if hasattr(response, "output"):
            return _guardrail_text(str(response.output).strip(), fallback=_fallback_text(prompt, context="Gemini response was empty."))
        return _guardrail_text(str(response).strip(), fallback=_fallback_text(prompt, context="Gemini response was empty."))
    except Exception as exc:  # pragma: no cover - runtime only
        logger.warning("Gemini call failed: %s", exc)
        return _fallback_text(prompt, context="Gemini request failed.")


def _llm_text(prompt: str, temperature: float = 0.2, max_output_tokens: int = 256) -> str:
    if OPENAI_API_KEY:
        logger.info("Using OpenAI LLM for text generation")
        return _openai_text(prompt, temperature=temperature, max_output_tokens=max_output_tokens)
    if GENAI_API_KEY and genai is not None:
        logger.info("Using Gemini LLM for text generation")
        return _gemini_text(prompt, temperature=temperature, max_output_tokens=max_output_tokens)
    logger.info("No external LLM configured; using deterministic fallback")
    return _fallback_text(prompt)


def summarize_openapi_generation(swagger_path: str, generated_files: list[str]) -> str:
    prompt = (
        f"{BDD_GENERATION_PROMPT}\n"
        f"The user provided an OpenAPI file path: {swagger_path}. "
        f"The generator created {len(generated_files)} feature files: {', '.join(generated_files)}. "
        "Summarize the endpoints covered, what was generated, and the recommended next step."
    )
    return _llm_text(prompt, temperature=0.2, max_output_tokens=200)


def summarize_bdd_execution(results: list[dict]) -> str:
    total = sum(len(feature["scenarios"]) for feature in results)
    passed = sum(1 for feature in results for scenario in feature["scenarios"] if scenario["passed"])
    failed = total - passed
    prompt = (
        f"{BDD_REVIEW_PROMPT}\n"
        f"BDD execution produced {len(results)} feature files, {total} scenarios, {passed} passes and {failed} failures. "
        "List the failed scenario titles, their feature file, and the main failure reason. "
        "If all passed, congratulate the user."
    )

    summary = _llm_text(prompt, temperature=0.2, max_output_tokens=220)
    return f"BDD execution: {passed}/{total} scenarios passed.\n{summary}"


def summarize_pii_results(validation: dict) -> str:
    prompt = (
        f"{PII_VALIDATION_PROMPT}\n"
        f"Results: {json.dumps(validation, indent=2)}"
    )
    return _llm_text(prompt, temperature=0.2, max_output_tokens=220)


def summarize_fca_results(fca_results: dict) -> str:
    prompt = (
        f"{FCA_VALIDATION_PROMPT}\n"
        f"Results: {json.dumps(fca_results, indent=2)}"
    )
    return _llm_text(prompt, temperature=0.2, max_output_tokens=260)
