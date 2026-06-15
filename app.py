# app.py
# AI Resume Tailoring Engine — Streamlit frontend + pipeline orchestrator.
# AnalyticsShiksha · V1
#
# Execution order on every Streamlit rerun:
#   1. load_dotenv()          — must precede all st. calls
#   2. st.set_page_config()   — must be first Streamlit command
#   3. Session state init     — setdefault, never overwrites live values
#   4. Helper fn definitions  — _render_* functions, no side effects
#   5. Page header
#   6. Section 1 — Inputs     — widgets set local vars: uploaded_file, jd_text
#   7. PDF change detection   — resets downstream state on new filename
#   8. Analyze button         — disabled unless both inputs present
#   9. Analyze handler        — pipeline runs only when button clicked
#  10. Section 3 — JD Analysis         (gated: jd_analysis in session_state)
#  11. Section 4 — Gap Analysis        (gated: gap_analysis in session_state)
#  12. Section 5 — Tailored Output     (gated: analysis_complete == True)

from dotenv import load_dotenv       # must be imported before st to allow early load
import streamlit as st
from agents import (
    run_agent_1, run_agent_2, run_agent_3, run_agent_4,
    LLMParseError, LLMValidationError,
)
from utils import extract_pdf_text
import google.api_core.exceptions

# ── Bootstrap — load .env before any st. call ─────────────────────────────
load_dotenv()

# ── Page config — must be the first Streamlit command ────────────────────
st.set_page_config(
    page_title="AI Resume Tailoring Engine",
    page_icon="📄",
    layout="wide",
)

# ── Session state — spec Section 5b ──────────────────────────────────────
# Use `if key not in` pattern: setdefault leaves live values untouched on reruns.
_NONE_KEYS = [
    "resume_text",
    "jd_text",
    "jd_analysis",
    "resume_analysis",
    "gap_analysis",
    "tailoring_output",
    "uploaded_filename",
]
for _key in _NONE_KEYS:
    if _key not in st.session_state:
        st.session_state[_key] = None

st.session_state.setdefault("analysis_complete", False)


# ═══════════════════════════════════════════════════════════════════════════
# Helper render functions
# Each reads from st.session_state and returns None.
# Private by convention (underscore prefix) — not called outside this file.
# ═══════════════════════════════════════════════════════════════════════════

def _render_bullet_list(items: list, empty_msg: str = "None listed.") -> None:
    """Render a list of strings as markdown bullet points."""
    if not items:
        st.caption(empty_msg)
        return
    for item in items:
        st.markdown(f"- {item}")


def _impact_badge(level: str) -> str:
    """Return an emoji badge for a priority action impact level."""
    return {"High": "🔴 High", "Medium": "🟡 Medium", "Low": "🟢 Low"}.get(level, level)


def _render_jd_analysis() -> None:
    """Section 3 — JD Analysis. Renders from st.session_state['jd_analysis']."""
    jd = st.session_state["jd_analysis"]

    st.subheader("📋 JD Analysis")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Role**")
        st.write(jd.get("role_name") or "—")
    with col2:
        st.markdown("**Company**")
        st.write(jd.get("company_name") or "—")
    with col3:
        st.markdown("**Experience Required**")
        st.write(jd.get("experience_required") or "—")

    st.markdown("")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Must-Have Skills**")
        _render_bullet_list(jd.get("must_have_skills", []))

        st.markdown("**Good-to-Have Skills**")
        _render_bullet_list(jd.get("good_to_have_skills", []))

        st.markdown("**Soft Skills**")
        _render_bullet_list(jd.get("soft_skills", []))

    with col_right:
        st.markdown("**Tools Mentioned**")
        _render_bullet_list(jd.get("tools_mentioned", []))

        st.markdown("**Top Keywords (ranked)**")
        _render_bullet_list(jd.get("keywords_ranked", []))

    st.divider()


def _render_gap_analysis() -> None:
    """Section 4 — Gap Analysis. Renders from st.session_state['gap_analysis']."""
    gap = st.session_state["gap_analysis"]

    st.subheader("🎯 Gap Analysis")

    # ── Match score ──────────────────────────────────────────────────────
    score = gap.get("match_score", 0)
    rec   = gap.get("apply_recommendation", "")

    col_score, col_rec = st.columns([1, 2])
    with col_score:
        st.metric("Match Score", f"{score}%")
        st.progress(score / 100)
    with col_rec:
        st.markdown("**Apply Recommendation**")
        if rec == "High Fit":
            st.success(f"✅ {rec}")
        elif rec == "Medium Fit":
            st.warning(f"⚠️ {rec}")
        else:
            st.error(f"❌ {rec}")

    # ── Score breakdown ───────────────────────────────────────────────────
    breakdown = gap.get("match_score_breakdown", {})
    if breakdown:
        with st.expander("Score breakdown", expanded=False):
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Must-Have Skills",    f"{breakdown.get('must_have_skills_score', 0)}%")
            b2.metric("Good-to-Have Skills", f"{breakdown.get('good_to_have_skills_score', 0)}%")
            b3.metric("Experience",          f"{breakdown.get('relevant_experience_score', 0)}%")
            b4.metric("Keyword Coverage",    f"{breakdown.get('keyword_coverage_score', 0)}%")

    # ── Experience gap ────────────────────────────────────────────────────
    exp_gap = gap.get("experience_gap", {})
    if exp_gap:
        with st.expander("Experience gap", expanded=True):
            eg1, eg2, eg3 = st.columns(3)
            eg1.markdown(f"**Required:** {exp_gap.get('required', '—')}")
            eg2.markdown(f"**Candidate:** {exp_gap.get('candidate', '—')}")
            severity = exp_gap.get("severity", "None")
            eg3.markdown(f"**Severity:** {severity}")
            reason = exp_gap.get("reason", "")
            if reason:
                st.caption(reason)

    st.markdown("")

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**💪 Strength Areas**")
        _render_bullet_list(gap.get("strength_areas", []))

        st.markdown("**⚠️ Missing Skills**")
        _render_bullet_list(gap.get("missing_skills", []), empty_msg="No missing must-have skills.")

        st.markdown("**🔍 Missing Keywords**")
        _render_bullet_list(gap.get("missing_keywords", []), empty_msg="No missing keywords.")

    with col_r:
        st.markdown("**📉 Weak Sections**")
        _render_bullet_list(gap.get("weak_sections", []))

        st.markdown("**💡 Improvement Opportunities**")
        _render_bullet_list(gap.get("improvement_opportunities", []))

    st.divider()


def _render_tailoring_output() -> None:
    """Section 5 — Tailored Recommendations. Renders from st.session_state['tailoring_output']."""
    out = st.session_state["tailoring_output"]

    st.subheader("✍️ Tailored Resume Recommendations")

    # ── Overall strategy ─────────────────────────────────────────────────
    st.markdown("### Overall Tailoring Strategy")
    _render_bullet_list(out.get("overall_tailoring_strategy", []))
    st.markdown("")

    # ── Priority actions ─────────────────────────────────────────────────
    st.markdown("### Priority Actions")
    priority_actions = out.get("priority_actions", [])
    if not priority_actions:
        st.caption("No priority actions returned.")
    for item in priority_actions:
        priority_num = item.get("priority", "?")
        action_text  = item.get("action", "")
        impact       = item.get("estimated_match_score_impact", {})
        level        = impact.get("level", "")
        explanation  = impact.get("explanation", "")

        with st.container():
            col_num, col_action, col_impact = st.columns([1, 8, 2])
            with col_num:
                st.markdown(f"**#{priority_num}**")
            with col_action:
                st.markdown(action_text)
            with col_impact:
                st.markdown(f"**{_impact_badge(level)}**")
            if explanation:
                st.caption(f"↳ {explanation}")
        st.markdown("---")

    # ── Professional summary ─────────────────────────────────────────────
    st.markdown("### Professional Summary")
    for rec in out.get("professional_summary_recommendations", []):
        original  = rec.get("original", "")
        suggested = rec.get("suggested", "")
        reason    = rec.get("reason", "")

        st.markdown("**Original:**")
        st.markdown(f"> {original}" if original else "> *(none present)*")
        st.markdown("**Suggested** *(click to copy):*")
        st.code(suggested, language=None)
        if reason:
            st.caption(f"💡 {reason}")
        st.markdown("")

    # ── Skills section ───────────────────────────────────────────────────
    st.markdown("### Skills Section")
    for rec in out.get("skills_section_recommendations", []):
        original  = rec.get("original", "")
        suggested = rec.get("suggested", "")
        reason    = rec.get("reason", "")

        st.markdown("**Current order:**")
        st.markdown(f"> {original}")
        st.markdown("**Recommended order** *(click to copy):*")
        st.code(suggested, language=None)
        if reason:
            st.caption(f"💡 {reason}")
        st.markdown("")

    # ── Experience rewrites ───────────────────────────────────────────────
    exp_rewrites = out.get("experience_section_rewrites", [])
    if exp_rewrites:
        st.markdown("### Experience Section Rewrites")
        for i, rewrite in enumerate(exp_rewrites, start=1):
            original  = rewrite.get("original", "")
            suggested = rewrite.get("suggested", "")
            reason    = rewrite.get("reason", "")

            with st.expander(f"Rewrite {i}", expanded=True):
                st.markdown("**Original:**")
                st.markdown(f"> {original}")
                st.markdown("**Suggested** *(click to copy):*")
                st.code(suggested, language=None)
                if reason:
                    st.caption(f"💡 {reason}")

    # ── Project rewrites ─────────────────────────────────────────────────
    proj_rewrites = out.get("project_section_rewrites", [])
    if proj_rewrites:
        st.markdown("### Project Section Rewrites")
        for i, rewrite in enumerate(proj_rewrites, start=1):
            original  = rewrite.get("original", "")
            suggested = rewrite.get("suggested", "")
            reason    = rewrite.get("reason", "")

            with st.expander(f"Rewrite {i}", expanded=True):
                st.markdown("**Original:**")
                st.markdown(f"> {original}")
                st.markdown("**Suggested** *(click to copy):*")
                st.code(suggested, language=None)
                if reason:
                    st.caption(f"💡 {reason}")

    # ── Keyword guidance ─────────────────────────────────────────────────
    keyword_recs = out.get("keyword_optimization_recommendations", [])
    if keyword_recs:
        st.markdown("### Keyword Optimization")
        _render_bullet_list(keyword_recs)

    # ── Cannot address — spec requires st.warning() ──────────────────────
    cannot_address = out.get("cannot_address", [])
    if cannot_address:
        st.markdown("### Gaps That Cannot Be Closed Through Rewording")
        warning_text = "\n".join(f"- {item}" for item in cannot_address)
        st.warning(warning_text)


# ═══════════════════════════════════════════════════════════════════════════
# Page header
# ═══════════════════════════════════════════════════════════════════════════

st.title("📄 AI Resume Tailoring Engine")
st.caption("AnalyticsShiksha · V1 · Powered by Gemini 2.5 Flash")
st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Inputs
# ═══════════════════════════════════════════════════════════════════════════

st.subheader("1. Upload Your Resume & Paste the Job Description")

col_pdf, col_jd = st.columns(2)

with col_pdf:
    uploaded_file = st.file_uploader(
        "Upload Resume PDF",
        type=["pdf"],
        help="Text-based PDFs only. Scanned or image PDFs are not supported in V1.",
    )
    if uploaded_file:
        st.caption(f"📎 {uploaded_file.name}")

with col_jd:
    jd_text = st.text_area(
        "Paste Job Description",
        height=300,
        placeholder=(
            "Paste the full job description here.\n\n"
            "Include the skills, responsibilities, and requirements sections "
            "for best results."
        ),
    )

# ── Centered Analyze button ───────────────────────────────────────────────
_, col_btn, _ = st.columns([2, 2, 2])
with col_btn:
    analyze_clicked = st.button(
        "🔍 Analyze Resume",
        disabled=(uploaded_file is None or not jd_text.strip()),
        use_container_width=True,
        type="primary",
    )

# ═══════════════════════════════════════════════════════════════════════════
# PDF change detection
# Reset downstream state only when a new file is uploaded (filename changed).
# Does NOT reset on every rerun — that would wipe results on every scroll.
# ═══════════════════════════════════════════════════════════════════════════

if uploaded_file is not None:
    # Build a signature from name + size so that a modified resume saved
    # under the same filename (e.g. Resume.pdf) still triggers a reset.
    stored  = st.session_state.get("uploaded_filename")
    new_sig = f"{uploaded_file.name}:{uploaded_file.size}"
    if stored != new_sig:
        for _reset_key in ["jd_analysis", "resume_analysis", "gap_analysis", "tailoring_output"]:
            st.session_state[_reset_key] = None
        st.session_state["analysis_complete"] = False
        st.session_state["uploaded_filename"] = new_sig

# ═══════════════════════════════════════════════════════════════════════════
# Analyze button handler — pipeline execution + error handling
# ═══════════════════════════════════════════════════════════════════════════

if analyze_clicked:

    # ── Pre-flight: JD length guard (spec §9) ────────────────────────────
    # Checked before PDF extraction — fast fail, no API calls consumed.
    if len(jd_text.strip()) < 200:
        st.warning(
            "JD content seems incomplete. Please paste the full job description."
        )
        st.stop()

    # ── Pipeline ─────────────────────────────────────────────────────────
    # Exceptions propagate from agents.py and utils.py.
    # Caught in order: most specific → most general.
    # ValueError: from extract_pdf_text (password / scanned / corrupt PDF).
    # LLMParseError / LLMValidationError: from retry_llm_call in utils.py.
    # ResourceExhausted: subclass of GoogleAPIError — must be caught first.
    # GoogleAPIError: all other Gemini API failures.
    try:
        # ── Step 1: PDF extraction — no spinner (local, fast) ────────────
        st.session_state["resume_text"] = extract_pdf_text(uploaded_file)
        st.session_state["jd_text"]     = jd_text

        # ── Step 2: Agent 1 — JD Analyzer ────────────────────────────────
        with st.spinner("Extracting JD requirements..."):
            st.session_state["jd_analysis"] = run_agent_1(jd_text)

        # ── Step 3: Agent 2 — Resume Analyzer ────────────────────────────
        with st.spinner("Reading your resume..."):
            st.session_state["resume_analysis"] = run_agent_2(
                st.session_state["resume_text"]
            )

        # ── Step 4: Agent 3 — Gap Analysis ───────────────────────────────
        with st.spinner("Running gap analysis..."):
            st.session_state["gap_analysis"] = run_agent_3(
                st.session_state["jd_analysis"],
                st.session_state["resume_analysis"],
            )

        # ── Step 5: Agent 4 — Tailoring Recommendations ──────────────────
        with st.spinner("Generating tailoring recommendations..."):
            st.session_state["tailoring_output"] = run_agent_4(
                st.session_state["jd_analysis"],
                st.session_state["resume_analysis"],
                st.session_state["gap_analysis"],
            )

        # ── Step 6: Mark complete ─────────────────────────────────────────
        st.session_state["analysis_complete"] = True
        st.success("✅ Analysis complete. Scroll down to see your results.")

    except ValueError as exc:
        # PDF extraction failures — shows the exact spec-defined message.
        st.error(str(exc))

    except LLMParseError:
        st.error("Analysis failed. Please try again.")

    except LLMValidationError:
        st.error("Analysis failed. Please try again.")

    except google.api_core.exceptions.ResourceExhausted:
        # Caught before GoogleAPIError — ResourceExhausted is a subclass of it.
        st.error("Too many requests. Please wait 30 seconds and try again.")

    except google.api_core.exceptions.GoogleAPIError:
        st.error("AI processing temporarily unavailable. Please try again in a moment.")

    except Exception as exc:
        # Safety net — catches KeyError, TypeError, AttributeError, etc.
        # Prevents raw Python tracebacks from surfacing to the user.
        st.error("An unexpected error occurred. Please try again.")
        if st.session_state.get("DEBUG"):
            st.exception(exc)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — JD Analysis
# Gated: renders as soon as Agent 1 result is in session_state.
# Survives independently — visible even if later agents fail.
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["jd_analysis"] is not None:
    _render_jd_analysis()

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — Gap Analysis
# Gated: renders as soon as Agent 3 result is in session_state.
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["gap_analysis"] is not None:
    _render_gap_analysis()

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — Tailored Recommendations
# Gated: requires analysis_complete == True (all 4 agents succeeded).
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"] and st.session_state["tailoring_output"] is not None:
    _render_tailoring_output()
