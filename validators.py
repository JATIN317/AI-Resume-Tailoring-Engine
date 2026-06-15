# validators.py
# JSON validation layer for all 4 agents.
# Source of truth: Technical Specification v1.4, Appendix A (per-agent implementation notes).
#
# Two public functions:
#   validate_output(parsed_json, agent_name)  → (bool, list[str])
#   validate_gap_analysis(gap)                → (bool, str)
#
# Both are pure functions: no imports, no LLM calls, no side effects.
# Called by utils.retry_llm_call() after every JSON parse attempt.

# ---------------------------------------------------------------------------
# Required keys per agent
# Source: Appendix A implementation notes (authoritative over Section 9 summary).
# ---------------------------------------------------------------------------

REQUIRED_KEYS: dict[str, list[str]] = {
    # Appendix A1 — JD Analyzer
    "jd_analysis": [
        "role_name",
        "company_name",
        "experience_required",
        "must_have_skills",
        "good_to_have_skills",
        "soft_skills",
        "tools_mentioned",
        "responsibilities",
        "keywords_ranked",
    ],
    # Appendix A2 — Resume Analyzer
    "resume_analysis": [
        "candidate_summary",
        "skills",
        "tools",
        "experience",
        "projects",
        "education",
        "certifications",
        "achievements",
        "keywords_present",
    ],
    # Appendix A3 — Gap Analysis Agent
    "gap_analysis": [
        "match_score",
        "match_score_breakdown",
        "apply_recommendation",
        "experience_gap",
        "strength_areas",
        "missing_skills",
        "missing_keywords",
        "weak_sections",
        "improvement_opportunities",
    ],
    # Appendix A4 — Tailoring Recommendations Agent
    "tailoring_output": [
        "overall_tailoring_strategy",
        "priority_actions",
        "professional_summary_recommendations",
        "skills_section_recommendations",
        "experience_section_rewrites",
        "project_section_rewrites",
        "keyword_optimization_recommendations",
        "cannot_address",
    ],
}

# ---------------------------------------------------------------------------
# Agent 3 — additional constraint constants
# ---------------------------------------------------------------------------

# Spec Section 7: apply_recommendation must be exactly one of these strings.
VALID_APPLY_RECOMMENDATIONS: frozenset[str] = frozenset({
    "High Fit",
    "Medium Fit",
    "Low Fit",
})

# Spec Section 5 / Appendix A3: relevant_experience_score must be a discrete band.
VALID_EXPERIENCE_SCORE_BANDS: frozenset[int] = frozenset({0, 20, 40, 60, 80, 100})

# Spec Section 5: breakdown sub-score keys to validate.
BREAKDOWN_SCORE_KEYS: list[str] = [
    "must_have_skills_score",
    "good_to_have_skills_score",
    "relevant_experience_score",
    "keyword_coverage_score",
]


# ---------------------------------------------------------------------------
# Generic key-presence validation (all 4 agents)
# ---------------------------------------------------------------------------

def validate_output(parsed_json: dict, agent_name: str) -> tuple[bool, list[str]]:
    """
    Check that all required top-level keys are present in the parsed JSON.

    Args:
        parsed_json: The dict returned by json.loads() on the LLM response.
        agent_name:  One of: "jd_analysis", "resume_analysis",
                     "gap_analysis", "tailoring_output".

    Returns:
        (True,  [])                    — all required keys present
        (False, ["key1", "key2", ...]) — list of missing keys

    Raises:
        KeyError if agent_name is not in REQUIRED_KEYS (programming error, not user error).
    """
    required = REQUIRED_KEYS[agent_name]
    missing = [k for k in required if k not in parsed_json]
    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# Agent 3 — extended validation (score bounds + enum constraints)
# Called after validate_output() passes for gap_analysis.
# ---------------------------------------------------------------------------

def validate_gap_analysis(gap: dict) -> tuple[bool, str]:
    """
    Validate Agent 3 output beyond key presence.

    Checks (in order):
    1. match_score is an integer in [0, 100]
    2. All four match_score_breakdown sub-scores are integers in [0, 100]
    3. relevant_experience_score is one of: 0, 20, 40, 60, 80, 100
    4. apply_recommendation is exactly one of: High Fit | Medium Fit | Low Fit

    Args:
        gap: The parsed gap_analysis dict (already key-validated).

    Returns:
        (True,  "valid")        — all constraints satisfied
        (False, error_message)  — first failing constraint with a human-readable reason
    """
    # 1. match_score — must be int, range 0–100
    score = gap.get("match_score", None)
    if not isinstance(score, int):
        return False, (
            f"match_score must be an integer, got {type(score).__name__}: {score!r}"
        )
    if not (0 <= score <= 100):
        return False, (
            f"match_score {score} is out of bounds — must be between 0 and 100"
        )

    # 2. match_score_breakdown — all four sub-scores must be int, 0–100
    breakdown = gap.get("match_score_breakdown", {})
    if not isinstance(breakdown, dict):
        return False, "match_score_breakdown must be a dict"

    for key in BREAKDOWN_SCORE_KEYS:
        val = breakdown.get(key, None)
        if not isinstance(val, int):
            return False, (
                f"match_score_breakdown.{key} must be an integer, "
                f"got {type(val).__name__}: {val!r}"
            )
        if not (0 <= val <= 100):
            return False, (
                f"match_score_breakdown.{key} value {val} is out of bounds (0–100)"
            )

    # 3. relevant_experience_score — must be a discrete band value
    exp_score = breakdown.get("relevant_experience_score")
    if exp_score not in VALID_EXPERIENCE_SCORE_BANDS:
        return False, (
            f"relevant_experience_score {exp_score!r} is invalid. "
            f"Must be one of: {sorted(VALID_EXPERIENCE_SCORE_BANDS)}"
        )

    # 4. apply_recommendation — must be exact string match
    rec = gap.get("apply_recommendation", "")
    if rec not in VALID_APPLY_RECOMMENDATIONS:
        return False, (
            f"apply_recommendation {rec!r} is invalid. "
            f"Must be exactly one of: {sorted(VALID_APPLY_RECOMMENDATIONS)}"
        )

    return True, "valid"
