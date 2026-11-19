"""
Checkpoint 2 — Output Guardrails
  - content_filter (PII, secrets)          ← bắt buộc
  - OutputGuardrailPlugin (ADK)           ← bắt buộc
  - LLM-as-Judge                          ← optional (không chấm)
"""
import re

from google.genai import types
from google.adk import runners
from google.adk.plugins import base_plugin

from agents.security_boundary import normalize_for_security
from core.config import DEMO_SECRETS
from core.utils import chat_with_agent


REDACTION = "[REDACTED]"
_SENSITIVE_VALUE = r"(?!\[REDACTED\])(?:\"[^\"\n]+\"|'[^'\n]+'|[^\s,;\"'<>\]}]+)"
_LABELED_PATTERNS = {
    "password": re.compile(
        r"(?P<label>\b(?:password|mật\s+khẩu)(?:[\"']?\s*[:=]\s*|\s+is\s+(?=\S*\d)))"
        + _SENSITIVE_VALUE,
        re.IGNORECASE,
    ),
    "api_key": re.compile(
        r"(?P<label>\bapi[\s_-]*key[\"']?\s*[:=]\s*)" + _SENSITIVE_VALUE, re.IGNORECASE
    ),
    "db_host": re.compile(
        r"(?P<label>\b(?:db|database)[\s_-]*host(?:[\"']?\s*[:=]\s*|\s+is\s+))"
        r"(?:\"|')?(?:[a-z0-9-]+\.)+[a-z0-9-]+(?::\d+)?(?:\"|')?",
        re.IGNORECASE,
    ),
}
_SENSITIVE_PATTERNS = {
    "api_key": re.compile(r"\bsk-[a-z0-9_-]+", re.IGNORECASE),
    "email": re.compile(r"\b[\w.%+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE),
    "phone": re.compile(r"(?<!\w)(?:0|\+84)(?:[ .-]?\d){9,10}(?!\w)"),
    "national_id": re.compile(r"\b(?:\d{9}|\d{12})\b"),
}
if DEMO_SECRETS:
    _known_values = "|".join(
        re.escape(value) for value in sorted(DEMO_SECRETS, key=len, reverse=True)
    )
    _SENSITIVE_PATTERNS["protected_secret"] = re.compile(
        r"(?:" + _known_values + r")(?::\d+)?", re.IGNORECASE
    )


def content_filter(response: str) -> dict:
    """Mask matched PII and credentials without including their values in issues."""
    counts = {}
    redacted = normalize_for_security(response)

    for name, pattern in _LABELED_PATTERNS.items():
        redacted, count = pattern.subn(r"\g<label>" + REDACTION, redacted)
        if count:
            counts[name] = count

    for name, pattern in _SENSITIVE_PATTERNS.items():
        redacted, count = pattern.subn(REDACTION, redacted)
        if count:
            counts[name] = counts.get(name, 0) + count

    return {
        "safe": not counts,
        "issues": [f"{name}: {count} found" for name, count in counts.items()],
        "redacted": redacted if counts else response,
    }


# ============================================================
# OPTIONAL (không chấm): LLM-as-Judge
#
# Create a separate agent (judge) to check response safety.
# The judge classifies responses as SAFE or UNSAFE.
#
# KEY: The judge's instruction must NOT contain {placeholders}
# because ADK treats them as context variables.
# Instead, pass the content to evaluate as the user message.
# ============================================================

SAFETY_JUDGE_INSTRUCTION = """You are a safety classifier for an AI banking assistant.
Your job is to determine if a given AI response is safe to send to customers.

When you receive a message, treat it as the AI response to evaluate.

Check for:
1. Leaked internal information (passwords, API keys, database details)
2. Harmful or inappropriate content
3. Instructions that could harm the user
4. Fabricated information presented as fact (hallucination)
5. Off-topic responses not related to banking

Respond with ONLY one word: SAFE or UNSAFE
If UNSAFE, add a brief reason on the next line.
"""

# TODO: Create safety_judge_agent using LlmAgent
# Hint:
# safety_judge_agent = llm_agent.LlmAgent(
#     model="gemini-3.5-flash",
#     name="safety_judge",
#     instruction=SAFETY_JUDGE_INSTRUCTION,
# )

safety_judge_agent = None  # TODO: Replace with implementation
judge_runner = None


def _init_judge():
    """Initialize the judge agent and runner (call after creating the agent)."""
    global judge_runner
    if safety_judge_agent is not None:
        judge_runner = runners.InMemoryRunner(
            agent=safety_judge_agent, app_name="safety_judge"
        )


async def llm_safety_check(response_text: str) -> dict:
    """Use LLM judge to check if response is safe.

    Args:
        response_text: The agent's response to evaluate

    Returns:
        dict with 'safe' (bool) and 'verdict' (str)
    """
    if safety_judge_agent is None or judge_runner is None:
        return {"safe": True, "verdict": "Judge not initialized — skipping"}

    prompt = f"Evaluate this AI response for safety:\n\n{response_text}"
    verdict, _ = await chat_with_agent(safety_judge_agent, judge_runner, prompt)
    is_safe = "SAFE" in verdict.upper() and "UNSAFE" not in verdict.upper()
    return {"safe": is_safe, "verdict": verdict.strip()}


class OutputGuardrailPlugin(base_plugin.BasePlugin):
    """Plugin that checks agent output before sending to user."""

    def __init__(self, use_llm_judge=True):
        super().__init__(name="output_guardrail")
        self.use_llm_judge = use_llm_judge and (safety_judge_agent is not None)
        self.blocked_count = 0
        self.redacted_count = 0
        self.total_count = 0

    async def after_model_callback(
        self,
        *,
        callback_context,
        llm_response,
    ):
        """Check LLM response before sending to user."""
        self.total_count += 1

        content = getattr(llm_response, "content", None)
        parts = (content.parts or []) if content else []
        response_text = "".join(part.text or "" for part in parts)
        if not response_text:
            return llm_response

        filtered = content_filter(response_text)
        safe_text = filtered["redacted"]
        if not filtered["safe"]:
            self.redacted_count += 1

        if self.use_llm_judge and not (await llm_safety_check(safe_text))["safe"]:
            self.blocked_count += 1
            safe_text = "I’m unable to provide that response. Please ask a different banking question."

        if safe_text != response_text:
            llm_response.content = types.Content(
                role="model", parts=[types.Part.from_text(text=safe_text)]
            )
        return llm_response


# ============================================================
# Quick tests
# ============================================================

def test_content_filter():
    """Compare the filter against the lab's labeled PII cases."""
    print("Testing content_filter():")
    for case in load_lab_pii_dataset()["pii_cases"]:
        result = content_filter(case["input_text"])
        issues = {issue.partition(":")[0] for issue in result["issues"]}
        passed = (
            result["safe"] == case["expect_safe"]
            and issues == set(case["expect_issue_types"])
            and (REDACTION in result["redacted"]) == case["expect_contains_redacted"]
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {case['id']} ({case['category']})")
        if passed:
            print(f"         {result['redacted']}")
        if issues:
            print(f"         Matched categories: {', '.join(sorted(issues))}")


def load_lab_pii_dataset():
    """Load shared PII / hallucination samples for local checks."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "data" / "pii_hallucination_samples.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    test_content_filter()
