# agents.py
# Four sequential AI agents for the Resume Tailoring Engine.
#
# Each function is a single-responsibility wiring layer:
#   1. Create a model configured with this agent's system prompt
#   2. Build the user message from runtime inputs
#   3. Call retry_llm_call() — handles API call, JSON parsing, validation, retry
#   4. Return the validated dict to app.py
#
# No try/except here — all exceptions propagate to app.py for user-facing handling.
# No Streamlit state management here — that is app.py's responsibility.
# No prompt text here — all prompt constants live in prompts.py.
# No validation logic here — all validation lives in validators.py and utils.py.
#
# LLMParseError and LLMValidationError are imported and re-exported so that
# app.py can catch them with a single import:  from agents import LLMParseError

from utils import get_gemini_model, retry_llm_call, LLMParseError, LLMValidationError  # noqa: F401
from prompts import (
    AGENT_1_SYSTEM_PROMPT, get_agent_1_user_message,
    AGENT_2_SYSTEM_PROMPT, get_agent_2_user_message,
    AGENT_3_SYSTEM_PROMPT, get_agent_3_user_message,
    AGENT_4_SYSTEM_PROMPT, get_agent_4_user_message,
)


def run_agent_1(jd_text: str) -> dict:
    """
    Agent 1 — JD Analyzer.

    Extracts structured hiring requirements from raw job description text.

    Args:
        jd_text: Raw job description as pasted by the user.

    Returns:
        Validated jd_analysis dict. Keys guaranteed by validators.REQUIRED_KEYS["jd_analysis"]:
        role_name, company_name, experience_required, must_have_skills,
        good_to_have_skills, soft_skills, tools_mentioned, responsibilities,
        keywords_ranked.

    Raises:
        LLMParseError:      Gemini returned unparseable JSON after 2 attempts.
        LLMValidationError: Parsed JSON missing required keys after 2 attempts.
        google.api_core.exceptions.GoogleAPIError: API-level failure (rate limit, auth).
    """
    model = get_gemini_model(AGENT_1_SYSTEM_PROMPT)
    user_message = get_agent_1_user_message(jd_text)
    return retry_llm_call(model, user_message, "jd_analysis")


def run_agent_2(resume_text: str) -> dict:
    """
    Agent 2 — Resume Analyzer.

    Extracts a structured candidate profile from plain resume text.

    Args:
        resume_text: Plain text extracted from the uploaded PDF by extract_pdf_text().

    Returns:
        Validated resume_analysis dict. Keys guaranteed by validators.REQUIRED_KEYS["resume_analysis"]:
        candidate_summary, skills, tools, experience, projects, education,
        certifications, achievements, keywords_present.

    Raises:
        LLMParseError:      Gemini returned unparseable JSON after 2 attempts.
        LLMValidationError: Parsed JSON missing required keys after 2 attempts.
        google.api_core.exceptions.GoogleAPIError: API-level failure (rate limit, auth).
    """
    model = get_gemini_model(AGENT_2_SYSTEM_PROMPT)
    user_message = get_agent_2_user_message(resume_text)
    return retry_llm_call(model, user_message, "resume_analysis")


def run_agent_3(jd_analysis: dict, resume_analysis: dict) -> dict:
    """
    Agent 3 — Gap Analysis Agent.

    Cross-references JD requirements against the candidate profile and produces
    a mathematically defensible match score with gap breakdown.

    Args:
        jd_analysis:     Validated output from run_agent_1().
        resume_analysis: Validated output from run_agent_2().

    Returns:
        Validated gap_analysis dict. Keys guaranteed by validators.REQUIRED_KEYS["gap_analysis"]:
        match_score, match_score_breakdown, apply_recommendation, experience_gap,
        strength_areas, missing_skills, missing_keywords, weak_sections,
        improvement_opportunities.
        Extended constraints also guaranteed by validators.validate_gap_analysis():
        match_score ∈ [0,100], apply_recommendation ∈ {High Fit, Medium Fit, Low Fit},
        relevant_experience_score ∈ {0, 20, 40, 60, 80, 100}.

    Raises:
        LLMParseError:      Gemini returned unparseable JSON after 2 attempts.
        LLMValidationError: Parsed JSON failed key or extended validation after 2 attempts.
        google.api_core.exceptions.GoogleAPIError: API-level failure (rate limit, auth).
    """
    model = get_gemini_model(AGENT_3_SYSTEM_PROMPT)
    user_message = get_agent_3_user_message(jd_analysis, resume_analysis)
    return retry_llm_call(model, user_message, "gap_analysis")


def run_agent_4(
    jd_analysis: dict,
    resume_analysis: dict,
    gap_analysis: dict,
) -> dict:
    """
    Agent 4 — Tailoring Recommendations Agent.

    Generates specific, actionable resume tailoring recommendations using only
    evidence present in the candidate's existing resume. Never invents.

    Args:
        jd_analysis:     Validated output from run_agent_1().
        resume_analysis: Validated output from run_agent_2().
        gap_analysis:    Validated output from run_agent_3().

    Returns:
        Validated tailoring_output dict. Keys guaranteed by validators.REQUIRED_KEYS["tailoring_output"]:
        overall_tailoring_strategy, priority_actions,
        professional_summary_recommendations, skills_section_recommendations,
        experience_section_rewrites, project_section_rewrites,
        keyword_optimization_recommendations, cannot_address.

    Raises:
        LLMParseError:      Gemini returned unparseable JSON after 2 attempts.
        LLMValidationError: Parsed JSON missing required keys after 2 attempts.
        google.api_core.exceptions.GoogleAPIError: API-level failure (rate limit, auth).
    """
    model = get_gemini_model(AGENT_4_SYSTEM_PROMPT)
    user_message = get_agent_4_user_message(jd_analysis, resume_analysis, gap_analysis)
    return retry_llm_call(model, user_message, "tailoring_output")
