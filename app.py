# app.py — AI Resume Tailoring Engine (V3)
# Based on appv2.py. V3 additions:
#   1. Improvement Opportunities section (gap_analysis.improvement_opportunities)
#   2. JD Understanding collapsed expander (all 9 jd_analysis fields)
#   3. Match Score Simulator collapsed expander (heuristic, not predictive model)
#   4. Keyword Optimization Recommendations section (tailoring_output.keyword_optimization_recommendations)
#   5. Experience Gap Detail expander inside Strategic Positioning Summary
#   6. Unified Resume Improvement Plan (header + chips + cards, after Pipeline)
#   7. Removed truncation in _concerns_html and _keyword_coverage_html
# All pipeline, session state, CSS, and backend behavior unchanged from appv2.py.

from dotenv import load_dotenv
import streamlit as st
import contextlib
from agents import (
    run_agent_1, run_agent_2, run_agent_3, run_agent_4,
    LLMParseError, LLMValidationError,
)
from utils import extract_pdf_text
import google.api_core.exceptions

# ── Bootstrap ──────────────────────────────────────────────────────────────
load_dotenv()

# ── Page config — first Streamlit command ──────────────────────────────────
st.set_page_config(
    page_title="AI Resume Tailoring Engine",
    page_icon="📄",
    layout="wide",
)

# ── Session state — 8 keys, unchanged ─────────────────────────────────────
_NONE_KEYS = [
    "resume_text", "jd_text", "jd_analysis",
    "resume_analysis", "gap_analysis", "tailoring_output", "uploaded_filename",
]
for _key in _NONE_KEYS:
    if _key not in st.session_state:
        st.session_state[_key] = None
st.session_state.setdefault("analysis_complete", False)


# ═══════════════════════════════════════════════════════════════════════════
# UI UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def _esc(s) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"','&quot;')

def _impact_pct(level: str) -> int:
    return {"High": 4, "Medium": 2, "Low": 1}.get(level, 1)

def _fit_colors(rec: str):
    if rec == "High Fit":
        return "badge-high", "#F0FFF4", "#00B894", "✅ Apply", "Recommended to Apply"
    elif rec == "Medium Fit":
        return "badge-medium", "#FFF8F0", "#E17055", "⚠️ Apply with Reservations", "Apply with Reservations"
    else:
        return "badge-low", "#FFF0F0", "#D63031", "❌ Consider Other Roles", "Consider Other Roles"

def _exp_indicator(severity: str):
    s = (severity or "").strip()
    if s in ("None","Low",""):
        return "✅ Experience: No Gap", "#00B894"
    elif s == "Medium":
        return "⚠️ Experience: Partial Gap", "#E17055"
    return "❌ Experience: Gap Detected", "#D63031"

def _priority_badge(level: str) -> str:
    lc = (level or "").lower()
    if lc == "high":     bg, lbl = "#D63031", "HIGH PRIORITY"
    elif lc == "medium": bg, lbl = "#E17055", "MEDIUM PRIORITY"
    else:                bg, lbl = "#636E72", "LOW PRIORITY"
    return (f'<span style="background:{bg};color:white;font-size:10px;font-weight:700;'
            f'padding:3px 10px;border-radius:10px;letter-spacing:0.5px;">{lbl}</span>')

def _est_chip(level: str) -> str:
    # Kept for potential future use; not currently called in V3 card rendering.
    pct = _impact_pct(level)
    return (f'<span style="background:#F0FFF4;color:#00B894;font-size:11px;font-weight:700;'
            f'padding:3px 10px;border-radius:10px;">↑ Est. +{pct}%</span>')

def _simulator_eligible_actions(actions: list) -> list:
    """
    Fix 2 (P03) — Allow-list filter for Match Score Simulator eligibility.

    Forward-compatible by design: action_type is an open enum (V4+ may add
    new values). An ALLOW-LIST is used rather than a block-list so that any
    future action_type NOT explicitly approved here is excluded by default,
    rather than silently included.

    Filtering order:
      1. action_type present AND in ALLOWED  -> eligible
      2. action_type present AND NOT in ALLOWED -> excluded
      3. action_type absent entirely (e.g. older cached responses) ->
         fall back to text-signal filtering on the action string
    Eligible actions are then sorted by priority ascending (1 = highest
    impact) before the caller takes the top 3 — sorting happens here so
    every caller gets a correctly-ordered list regardless of the LLM's
    original array order.
    """
    ALLOWED = {"ATS", "Match", "Evidence"}
    _exclude_signals = ["date", "typo", "correct the", "formatting", "future date"]

    eligible = []
    for a in actions or []:
        a_type = a.get("action_type")
        if a_type is not None:
            if a_type in ALLOWED:
                eligible.append(a)
            # else: present but not allow-listed -> excluded, no further check
        else:
            action_text = (a.get("action") or "").lower()
            if not any(sig in action_text for sig in _exclude_signals):
                eligible.append(a)

    # Sort ascending by priority (1 = highest impact). Items missing a
    # priority field sort last (treated as lowest priority = 999).
    eligible_sorted = sorted(eligible, key=lambda a: a.get("priority", 999))
    return eligible_sorted

def _score_aware_filter(actions: list, match_score) -> list:
    """
    Fix 3 Rule A (P11/FD01) — Score-aware filtering for Resume Improvement Plan.

    match_score >= 85 (strong match):
      Show all High-impact items. If zero High items exist, fall back to
      the single highest-priority Medium item so the section is never
      rendered empty.
    All other scores (Rule C, 31-84% and below):
      No filtering — return actions unchanged, preserving current behavior.
    """
    try:
        score = int(match_score or 0)
    except (TypeError, ValueError):
        score = 0

    if score < 85:
        return actions  # Rule C — unchanged behavior

    high_items = [
        a for a in actions
        if (a.get("estimated_match_score_impact") or {}).get("level", "Low") == "High"
    ]
    if high_items:
        return high_items

    medium_items = [
        a for a in actions
        if (a.get("estimated_match_score_impact") or {}).get("level", "Low") == "Medium"
    ]
    if medium_items:
        best_medium = min(medium_items, key=lambda a: a.get("priority", 999))
        return [best_medium]

    # No High and no Medium items exist — return actions unchanged rather
    # than producing an empty list (preserves the "never empty" guarantee
    # at the level of "don't filter away everything that exists").
    return actions

def _get_verified_chips(gap: dict) -> str:
    """Cross-reference JD must-haves with resume keywords for concise chip labels."""
    jd_a  = st.session_state.get("jd_analysis")  or {}
    res_a = st.session_state.get("resume_analysis") or {}
    must_haves   = jd_a.get("must_have_skills") or []
    good_to_have = jd_a.get("good_to_have_skills") or []
    res_pool = set(k.lower() for k in (
        (res_a.get("keywords_present") or []) +
        (res_a.get("skills") or []) +
        (res_a.get("tools") or [])
    ))
    verified = [s for s in must_haves if s.lower() in res_pool]
    verified += [s for s in good_to_have if s.lower() in res_pool and s not in verified]
    if not verified:
        for item in (gap.get("strength_areas") or [])[:6]:
            for sep in [" — ", " present", " with ", " (", " is "]:
                if sep.lower() in item.lower():
                    skill = item[:item.lower().index(sep.lower())].strip()
                    if 1 < len(skill) < 30:
                        verified.append(skill)
                    break
            else:
                if len(item) < 30:
                    verified.append(item)
    if not verified:
        return '<span style="color:#636E72;font-size:13px;font-style:italic;">Skills matched</span>'
    return "".join(
        f'<span class="skill-chip">{_esc(s[:25])}</span>'
        for s in verified[:6]
    )

def _concerns_html(gap: dict) -> str:
    """Concerns bullets — V3: ALL items, full text, no truncation (removed [:4], [:3], [:50], [:72] limits)."""
    missing = gap.get("missing_skills") or []
    weak    = gap.get("weak_sections")  or []
    html = ""
    for skill in missing:  # V3: no item limit
        clean = skill.split(" — ")[0].strip()  # V3: no text truncation
        html += (
            '<div style="display:flex;gap:8px;padding:7px 0;border-bottom:1px solid #F4F6FB;">'
            '<span style="flex-shrink:0;color:#D63031;">❌</span>'
            f'<div><span style="font-size:13px;color:#1A1A2E;font-weight:500;">Missing: </span>'
            f'<span style="font-size:13px;color:#D63031;">{_esc(clean)}</span></div>'
            '</div>'
        )
    for section in weak:  # V3: no item limit, no text truncation
        html += (
            '<div style="display:flex;gap:8px;padding:7px 0;border-bottom:1px solid #F4F6FB;">'
            '<span style="flex-shrink:0;color:#E17055;">⚠️</span>'
            f'<span style="font-size:13px;color:#636E72;line-height:1.4;word-wrap:break-word;">{_esc(section)}</span>'
            '</div>'
        )
    if not html:
        html = '<div style="font-size:13px;color:#636E72;font-style:italic;">No major concerns identified.</div>'
    return html

def _keyword_coverage_html(gap: dict) -> str:
    """ATS Keyword Coverage card body — V3: ALL missing_keywords shown (removed [:8] limit)."""
    breakdown  = gap.get("match_score_breakdown") or {}
    missing_kw = gap.get("missing_keywords") or []
    jd_a  = st.session_state.get("jd_analysis")  or {}
    res_a = st.session_state.get("resume_analysis") or {}
    all_kw   = jd_a.get("keywords_ranked") or []
    res_pool = set(k.lower() for k in (res_a.get("keywords_present") or []))
    matched_kw = [k for k in all_kw if k.lower() in res_pool]
    mc, msc = len(matched_kw), len(missing_kw)
    bars = [
        ("Must-Have Skills",  breakdown.get("must_have_skills_score", 0),    "#5B4CF5"),
        ("Good-to-Have",      breakdown.get("good_to_have_skills_score", 0), "#00B894"),
        ("Experience",        breakdown.get("relevant_experience_score", 0),  "#E17055"),
        ("Keyword Coverage",  breakdown.get("keyword_coverage_score", 0),    "#5B4CF5"),
    ]
    counts = (
        '<div style="display:flex;gap:12px;margin-bottom:16px;">'
        '<div style="flex:1;background:#F0FFF4;border-radius:8px;padding:10px;text-align:center;">'
        f'<div style="font-size:22px;font-weight:700;color:#00B894;">{mc}</div>'
        '<div style="font-size:11px;color:#636E72;margin-top:2px;">Matched Keywords</div>'
        '</div>'
        '<div style="flex:1;background:#FFF0F0;border-radius:8px;padding:10px;text-align:center;">'
        f'<div style="font-size:22px;font-weight:700;color:#D63031;">{msc}</div>'
        '<div style="font-size:11px;color:#636E72;margin-top:2px;">Missing Keywords</div>'
        '</div>'
        '</div>'
    )
    bars_html = ""
    for label, val, color in bars:
        bars_html += (
            '<div style="margin-bottom:11px;">'
            '<div style="display:flex;justify-content:space-between;margin-bottom:3px;">'
            f'<span style="font-size:12px;color:#636E72;">{label}</span>'
            f'<span style="font-size:12px;font-weight:600;color:#1A1A2E;">{val}%</span>'
            '</div>'
            '<div style="background:#E8ECF0;border-radius:4px;height:6px;">'
            f'<div style="background:{color};border-radius:4px;height:6px;width:{min(val,100)}%;"></div>'
            '</div></div>'
        )
    chips = ""
    if missing_kw:
        chip_items = "".join(
            f'<span style="display:inline-block;background:#FFF0F0;color:#D63031;'
            f'border:1px solid #FFCDD2;padding:2px 8px;border-radius:10px;'
            f'font-size:11px;margin:2px;">{_esc(k)}</span>'
            for k in missing_kw  # V3: no [:8] limit — show ALL missing keywords
        )
        chips = (
            '<div style="font-size:11px;letter-spacing:1px;text-transform:uppercase;'
            'color:#636E72;font-weight:600;margin:12px 0 6px;">Missing Keywords</div>'
            + chip_items
        )
    return counts + bars_html + chips

def _jd_list_html(items: list) -> str:
    """Render a list of strings as HTML rows for JD Understanding section. No truncation."""
    if not items:
        return '<div style="font-size:13px;color:#9B9B9B;font-style:italic;padding:4px 0;">None listed.</div>'
    return "".join(
        f'<div style="font-size:13px;color:#2D3436;padding:4px 0;border-bottom:1px solid #F4F6FB;'
        f'line-height:1.5;word-wrap:break-word;">• {_esc(item)}</div>'
        for item in items
    )


# ═══════════════════════════════════════════════════════════════════════════
# CSS INJECTION — verbatim from appv2.py, no changes
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
.stApp{background-color:#F4F6FB !important;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,"Helvetica Neue",Arial,sans-serif !important;}
#MainMenu{visibility:hidden;}footer{visibility:hidden;}header{visibility:hidden;}
.block-container{padding-top:0 !important;padding-bottom:3rem !important;max-width:1200px !important;}
.stButton>button{background-color:#5B4CF5 !important;color:#FFFFFF !important;border:none !important;border-radius:8px !important;font-weight:600 !important;font-size:15px !important;padding:0.65rem 2rem !important;width:100% !important;transition:background-color 0.2s ease !important;}
.stButton>button:hover:not(:disabled){background-color:#4A3BD4 !important;}
.stButton>button:disabled{background-color:#C5C8D6 !important;color:#888 !important;}
.card{background:#FFFFFF;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,0.08);margin-bottom:16px;color:#1A1A2E;}
.card-slim{padding:16px 24px;}
.card-green-border{border-left:4px solid #00B894;}
.card-orange-border{border-left:4px solid #E17055;}
.card-purple-border{border-left:4px solid #5B4CF5;}
.badge-high{display:inline-block;background:#00B894;color:white;padding:4px 18px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;}
.badge-medium{display:inline-block;background:#E17055;color:white;padding:4px 18px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;}
.badge-low{display:inline-block;background:#D63031;color:white;padding:4px 18px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;}
.skill-chip{display:inline-block;background:#EEF0FF;color:#5B4CF5;border:1px solid #B8B4F8;padding:3px 12px;border-radius:12px;font-size:12px;font-weight:500;margin:3px;}
.section-header{font-size:20px;font-weight:700;color:#1A1A2E;margin-bottom:4px;}
.section-sub{font-size:13px;color:#636E72;margin-bottom:20px;}
.small-caps{font-size:11px;color:#636E72;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;}
.stProgress>div>div>div>div{background-color:#5B4CF5 !important;background-image:none !important;}
[data-testid="stMetricValue"]{color:#5B4CF5 !important;font-size:28px !important;font-weight:700 !important;}
[data-testid="stMetricLabel"]{color:#636E72 !important;font-size:12px !important;}
.streamlit-expanderHeader{background:#FFFFFF !important;border-radius:8px !important;font-weight:600 !important;color:#1A1A2E !important;}
.streamlit-expanderContent{background:#FFFFFF !important;border-radius:0 0 8px 8px !important;}
[data-testid="stFileUploader"]{background:white;border-radius:8px;padding:8px;}
.stCodeBlock{border-radius:8px !important;}
[data-testid="stHorizontalBlock"]{gap:16px !important;}
hr{border:none;border-top:1px solid #E8ECF0;margin:16px 0;}
[data-testid='stCode'] pre{font-size:14px !important;line-height:1.5 !important;}[data-testid='stCode'] code{font-size:14px !important;}[data-testid='stExpander']>details{border:1px solid #E8ECF0 !important;border-radius:10px !important;overflow:hidden;margin-bottom:8px;}[data-testid='stExpander']>details>summary{background-color:#F8F9FA !important;color:#1A1A2E !important;font-weight:600 !important;font-size:14px !important;padding:12px 16px !important;}[data-testid='stExpander']>details[open]>summary{background-color:#EEF0FF !important;color:#1A1A2E !important;border-bottom:1px solid #E8ECF0 !important;}.streamlit-expanderHeader{background-color:#F8F9FA !important;color:#1A1A2E !important;font-weight:600 !important;}.streamlit-expanderHeader:hover{background-color:#EEF0FF !important;}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# HEADER BAR — verbatim from appv2.py
# ═══════════════════════════════════════════════════════════════════════════

st.markdown(
    '<div style="background:#FFFFFF;border-bottom:1px solid #E8ECF0;padding:14px 28px;margin-bottom:20px;'
    'display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:999;">'
    '<div style="font-size:18px;font-weight:700;color:#1A1A2E;">📄 AI Resume Tailoring Engine</div>'
    '<div style="font-size:12px;color:#636E72;background:#EEF0FF;padding:4px 14px;border-radius:20px;">'
    'Powered by 4 AI Agents</div>'
    '</div>',
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════════════════
# STEP PROGRESS BAR — verbatim from appv2.py
# Gate: analysis_complete == True
# Single-line HTML string concatenation (Streamlit rendering constraint).
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"]:
    step_data = [("Upload",True),("AI Analysis",True),("Career Fit",True),
                 ("Improvements",True),("Apply",False)]
    circles = ""
    for i, (label, done) in enumerate(step_data):
        if i > 0:
            circles += '<div style="flex:1;height:2px;background:#5B4CF5;margin-bottom:22px;min-width:24px;"></div>'
        if done:
            circles += (
                f'<div style="display:flex;flex-direction:column;align-items:center;min-width:64px;">'
                f'<div style="width:32px;height:32px;border-radius:50%;background:#5B4CF5;color:white;'
                f'display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;">✓</div>'
                f'<div style="font-size:11px;color:#636E72;margin-top:6px;text-align:center;">{label}</div>'
                f'</div>'
            )
        else:
            circles += (
                f'<div style="display:flex;flex-direction:column;align-items:center;min-width:64px;">'
                f'<div style="width:32px;height:32px;border-radius:50%;border:2px solid #5B4CF5;'
                f'color:#5B4CF5;display:flex;align-items:center;justify-content:center;'
                f'font-size:12px;font-weight:700;background:white;">5</div>'
                f'<div style="font-size:11px;color:#5B4CF5;margin-top:6px;text-align:center;font-weight:700;">{label}</div>'
                f'</div>'
            )
    st.markdown(
        '<div class="card card-slim" style="margin-bottom:20px;">'
        f'<div style="display:flex;align-items:center;justify-content:center;">{circles}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# INPUT AREA — verbatim from appv2.py
# Gate: always visible
# ═══════════════════════════════════════════════════════════════════════════

st.markdown(
    '<div class="card" style="padding:20px 24px 8px 24px;margin-bottom:8px;">'
    '<div class="section-header" style="margin-bottom:2px;">Step 1 — Upload your resume and paste the job description</div>'
    '<div class="section-sub">Both are required to generate your AI Career Fit Report</div>'
    '</div>',
    unsafe_allow_html=True,
)

col_pdf, col_jd = st.columns(2)

with col_pdf:
    uploaded_file = st.file_uploader(
        "Upload Resume PDF",
        type=["pdf"],
        help="Text-based PDFs only. Scanned or image PDFs are not supported in V1.",
    )
    if uploaded_file:
        size_kb  = uploaded_file.size / 1024
        size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        st.markdown(
            '<div style="background:#F0FFF4;border:1px solid #C3E6CB;border-radius:8px;'
            'padding:10px 14px;margin-top:8px;display:flex;align-items:center;gap:10px;">'
            '<span style="font-size:22px;">📄</span>'
            '<div style="flex:1;min-width:0;">'
            f'<div style="font-size:13px;font-weight:600;color:#1A1A2E;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;">{_esc(uploaded_file.name)}</div>'
            f'<div style="font-size:11px;color:#636E72;">{size_str}</div>'
            '</div>'
            '<span style="font-size:12px;color:#00B894;font-weight:700;flex-shrink:0;">✓ Ready</span>'
            '</div>',
            unsafe_allow_html=True,
        )

with col_jd:
    jd_text = st.text_area(
        "Paste Job Description",
        height=280,
        placeholder=(
            "Paste the full job description here.\n\n"
            "Include skills, responsibilities, and requirements for best results."
        ),
    )

_, col_btn, _ = st.columns([1, 2, 1])
with col_btn:
    analyze_clicked = st.button(
        "🔍  Analyze Resume",
        disabled=(uploaded_file is None or not jd_text.strip()),
        use_container_width=True,
        type="primary",
    )
    st.markdown(
        '<div style="text-align:center;padding:6px 0 2px;">'
        '<span style="font-size:12px;color:#636E72;">⚡ Average analysis time: 15–20 seconds</span>'
        '</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# PDF CHANGE DETECTION — verbatim from appv2.py
# ═══════════════════════════════════════════════════════════════════════════

if uploaded_file is not None:
    stored  = st.session_state.get("uploaded_filename")
    new_sig = f"{uploaded_file.name}:{uploaded_file.size}"
    if stored != new_sig:
        for _reset_key in ["jd_analysis","resume_analysis","gap_analysis","tailoring_output"]:
            st.session_state[_reset_key] = None
        st.session_state["analysis_complete"] = False
        st.session_state["uploaded_filename"] = new_sig
        # Fix P08: trigger an explicit controlled rerun now that all mutations
        # are complete. Without this, Streamlit's implicit auto-rerun fires at
        # the END of the current run — meaning Run A already painted the Step
        # Progress Bar and Input section before the rerun begins, causing the
        # user to see two stacked input renders. st.rerun() aborts Run A's
        # partial output immediately and restarts cleanly; Run B starts with
        # analysis_complete=False so the Progress Bar is skipped and the
        # Input section renders exactly once.
        # Nothing follows this statement inside the if-block — st.rerun()
        # raises an exception that halts script execution immediately.
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE — verbatim from appv2.py
# Exception order: ValueError → LLMParseError → LLMValidationError →
#                  ResourceExhausted → GoogleAPIError → Exception
# ═══════════════════════════════════════════════════════════════════════════

if analyze_clicked:
    if len(jd_text.strip()) < 200:
        st.warning("JD content seems incomplete. Please paste the full job description.")
        st.stop()

    try:
        st.session_state["resume_text"] = extract_pdf_text(uploaded_file)
        st.session_state["jd_text"]     = jd_text

        with st.spinner("🔍 Parsing Job Description..."):
            st.session_state["jd_analysis"] = run_agent_1(jd_text)

        with st.spinner("📄 Reading Resume..."):
            st.session_state["resume_analysis"] = run_agent_2(
                st.session_state["resume_text"]
            )

        with st.spinner("🎯 Running Gap Analysis..."):
            st.session_state["gap_analysis"] = run_agent_3(
                st.session_state["jd_analysis"],
                st.session_state["resume_analysis"],
            )

        with st.spinner("✍️ Generating Resume Recommendations..."):
            st.session_state["tailoring_output"] = run_agent_4(
                st.session_state["jd_analysis"],
                st.session_state["resume_analysis"],
                st.session_state["gap_analysis"],
            )

        st.session_state["analysis_complete"] = True
        st.success("✅ Career Fit Report ready. Scroll down to review your results.")

    except ValueError as exc:
        st.error(str(exc))
    except LLMParseError:
        st.error("Analysis failed. Please try again.")
    except LLMValidationError:
        st.error("Analysis failed. Please try again.")
    except google.api_core.exceptions.ResourceExhausted:
        st.error("Too many requests. Please wait 30 seconds and try again.")
    except google.api_core.exceptions.GoogleAPIError:
        st.error("AI processing temporarily unavailable. Please try again in a moment.")
    except Exception as exc:
        st.error("An unexpected error occurred. Please try again.")
        if st.session_state.get("DEBUG"):
            st.exception(exc)


# ═══════════════════════════════════════════════════════════════════════════
# HERO RECOMMENDATION — verbatim from appv2.py
# Gate: gap_analysis is not None
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["gap_analysis"] is not None:
    gap      = st.session_state["gap_analysis"]
    score    = gap.get("match_score", 0)
    rec      = gap.get("apply_recommendation", "Low Fit")
    strengths = gap.get("strength_areas") or []
    exp_gap  = gap.get("experience_gap") or {}
    severity = exp_gap.get("severity") or "None"

    jd_a = st.session_state["jd_analysis"] or {}
    role_name    = _esc(jd_a.get("role_name","") or "")
    company_name = _esc(jd_a.get("company_name","") or "")
    co_part = f" role at <b>{company_name}</b>" if company_name and company_name != "Unknown" else ""
    role_line = f"Analysis for <b>{role_name}</b>{co_part}" if role_name else ""

    badge_cls, action_bg, action_fg, action_text, rec_line = _fit_colors(rec)
    exp_text, exp_color = _exp_indicator(severity)
    chips_html   = _get_verified_chips(gap)
    factors_html = "".join(
        '<div style="padding:7px 0;border-bottom:1px solid #F4F6FB;color:#636E72;font-size:13px;">'
        f'→&nbsp;&nbsp;{_esc(s)}</div>'
        for s in strengths[:3]
    )
    rationale = _esc(strengths[0]) if strengths else "Strong candidate profile aligned with role requirements."
    fit_label = badge_cls.replace("badge-","").upper() + " FIT"

    if role_line:
        st.markdown(
            '<div style="padding:4px 0 16px 2px;">'
            '<div style="font-size:28px;font-weight:700;color:#1A1A2E;margin-bottom:4px;">AI Career Fit Report</div>'
            f'<div style="font-size:13px;color:#636E72;display:flex;align-items:center;gap:16px;">'
            f'<span>{role_line}</span>'
            '<span style="background:#EEF0FF;color:#5B4CF5;padding:3px 12px;border-radius:20px;'
            'font-size:11px;font-weight:600;">⚡ Powered by 4 Specialized AI Agents</span>'
            '</div></div>',
            unsafe_allow_html=True,
        )

    col_left, col_right = st.columns([4, 6])

    with col_left:
        st.markdown(
            '<div class="card" style="text-align:center;min-height:360px;'
            'display:flex;flex-direction:column;justify-content:center;padding:28px 20px;">'
            f'<div style="font-size:76px;font-weight:800;color:#5B4CF5;line-height:1;margin-bottom:12px;">'
            f'{score}<span style="font-size:32px;font-weight:600;">%</span></div>'
            f'<div style="margin-bottom:12px;"><span class="{badge_cls}">{fit_label}</span></div>'
            f'<div style="font-size:16px;color:#1A1A2E;font-weight:500;margin-bottom:20px;">{rec_line}</div>'
            '<hr>'
            '<div style="font-size:11px;color:#636E72;letter-spacing:1.5px;text-transform:uppercase;'
            'font-weight:600;margin-bottom:12px;">Verified Core Matches</div>'
            f'<div style="margin-bottom:16px;">{chips_html}</div>'
            f'<div style="font-size:13px;color:{exp_color};font-weight:600;">{exp_text}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    with col_right:
        st.markdown(
            '<div class="card" style="min-height:360px;padding:28px 24px;">'
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
            '<div style="width:32px;height:32px;border-radius:8px;background:#EEF0FF;'
            'display:flex;align-items:center;justify-content:center;font-size:16px;">🎯</div>'
            '<div><div style="font-size:17px;font-weight:700;color:#1A1A2E;">Application Recommendation</div>'
            '<div style="font-size:12px;color:#636E72;">AI-generated evidence-based perspective</div></div>'
            '</div>'
            '<div style="height:16px;"></div>'
            f'<div style="background:{action_bg};border-radius:10px;padding:18px 20px;margin-bottom:20px;">'
            f'<div style="font-size:20px;font-weight:800;color:{action_fg};margin-bottom:8px;">{action_text}</div>'
            f'<div style="font-size:13px;color:#636E72;line-height:1.5;">{rationale}</div>'
            '</div>'
            '<div style="font-size:11px;color:#636E72;letter-spacing:1.5px;text-transform:uppercase;'
            'font-weight:600;margin-bottom:10px;">Key Driving Factors</div>'
            + (factors_html or '<div style="color:#636E72;font-size:13px;">No factors available.</div>') +
            '</div>',
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGIC POSITIONING SUMMARY
# Gate: analysis_complete == True
# V3 changes: subtitle updated; experience_gap expander added below strategy list.
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"] and st.session_state["tailoring_output"] is not None:
    out      = st.session_state["tailoring_output"]
    strategy = out.get("overall_tailoring_strategy") or []
    if strategy:
        numbered = "".join(
            '<div style="display:flex;gap:14px;padding:12px 0;border-bottom:1px solid #F4F6FB;">'
            f'<div style="width:24px;height:24px;border-radius:50%;background:#EEF0FF;color:#5B4CF5;'
            f'display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0;">{i}</div>'
            f'<div style="font-size:14px;color:#1A1A2E;line-height:1.6;">{_esc(item)}</div>'
            '</div>'
            for i, item in enumerate(strategy, start=1)
        )
        st.markdown(
            '<div class="card" style="margin-top:8px;">'
            '<div class="section-header" style="margin-bottom:4px;">🗺 Strategic Positioning Summary</div>'
            # V3: subtitle updated to focus on candidacy presentation
            '<div class="section-sub">How to present your candidacy for this specific role</div>'
            + numbered +
            '</div>',
            unsafe_allow_html=True,
        )

    # V3 addition: Experience Gap Detail collapsed expander
    # Shows all four experience_gap fields (required, candidate, severity, reason).
    exp_gap = (st.session_state.get("gap_analysis") or {}).get("experience_gap") or {}
    # Fix P04: check only the four meaningful text fields, not all dict values.
    # Avoids showing empty expander when only the boolean "gap" field is present.
    if any([exp_gap.get("required"), exp_gap.get("candidate"),
            exp_gap.get("severity"), exp_gap.get("reason")]):
        with st.expander("📊 Experience Gap Detail", expanded=False):
            sev_val = str(exp_gap.get("severity") or "None")
            sev_color = {"High": "#D63031", "Medium": "#E17055", "Low": "#00B894", "None": "#00B894"}.get(sev_val, "#636E72")
            eg1, eg2, eg3 = st.columns(3)
            with eg1:
                st.markdown(
                    '<div class="card card-slim"><div class="small-caps" style="margin-bottom:6px;">Experience Required</div>'
                    f'<div style="font-size:14px;color:#1A1A2E;font-weight:600;">{_esc(str(exp_gap.get("required") or "—"))}</div></div>',
                    unsafe_allow_html=True,
                )
            with eg2:
                st.markdown(
                    '<div class="card card-slim"><div class="small-caps" style="margin-bottom:6px;">Candidate Experience</div>'
                    f'<div style="font-size:14px;color:#1A1A2E;font-weight:600;">{_esc(str(exp_gap.get("candidate") or "—"))}</div></div>',
                    unsafe_allow_html=True,
                )
            with eg3:
                st.markdown(
                    f'<div class="card card-slim"><div class="small-caps" style="margin-bottom:6px;">Severity</div>'
                    f'<div style="font-size:14px;color:{sev_color};font-weight:700;">{_esc(sev_val)}</div></div>',
                    unsafe_allow_html=True,
                )
            reason = str(exp_gap.get("reason") or "").strip()
            if reason:
                st.markdown(
                    f'<div style="font-size:13px;color:#636E72;margin-top:4px;padding:12px 16px;'
                    f'background:#F8F9FA;border-radius:8px;line-height:1.6;">{_esc(reason)}</div>',
                    unsafe_allow_html=True,
                )


# ═══════════════════════════════════════════════════════════════════════════
# MATCH SCORE SIMULATOR — NEW in V3 (supporting diagnostic, collapsed)
# Gate: analysis_complete == True
# Heuristic only: High → +4%, Medium → +2%, Low → +1%
# These are priority estimates, not model predictions.
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"] and st.session_state["tailoring_output"] is not None:
    with st.expander("📊 Match Score Simulator", expanded=False):
        _gap_sim = st.session_state["gap_analysis"] or {}
        _out_sim = st.session_state["tailoring_output"] or {}
        _base    = _gap_sim.get("match_score", 0)
        # Fix 2 (P03): allow-list filter by action_type, sorted by priority
        # ascending, before taking the top 3. See _simulator_eligible_actions().
        _eligible_actions = _simulator_eligible_actions(_out_sim.get("priority_actions") or [])
        _top3    = _eligible_actions[:3]

        # Fix P04: guard against empty or missing priority_actions
        if not _top3:
            st.caption("Insufficient recommendations to generate simulator.")
        else:
            try:
                # Heuristic only: High → +4%, Medium → +2%, Low → +1%
                # These are priority estimates, not model predictions.
                _impact_data = []
                for _a in _top3:
                    _lvl   = (_a.get("estimated_match_score_impact") or {}).get("level", "Low")
                    _pct   = _impact_pct(_lvl)
                    _label = (_a.get("action") or "")[:22].strip()
                    _impact_data.append((_label, _pct, _lvl))

                _total_gain = sum(p for _, p, _ in _impact_data)
                _projected  = min(_base + _total_gain, 99)
                _remaining  = max(100 - _base - _total_gain, 0)
                _seg_colors = ["#7B6CF8", "#00B894", "#E17055"]

                _bar_segs = (
                    f'<div style="flex:{_base};background:#5B4CF5;display:flex;align-items:center;'
                    f'justify-content:center;color:white;font-size:12px;font-weight:700;min-width:4px;">'
                    + (f"{_base}%" if _base > 8 else "") + '</div>'
                )
                _lbl_segs = (
                    f'<div style="flex:{_base};padding-top:4px;">'
                    f'<span style="font-size:11px;color:#636E72;font-weight:600;">Current: {_base}%</span></div>'
                )

                for _i, (_label, _pct, _lvl) in enumerate(_impact_data):
                    _col = _seg_colors[_i % len(_seg_colors)]
                    _bar_segs += (
                        f'<div style="flex:{_pct};background:{_col};display:flex;align-items:center;'
                        f'justify-content:center;border-left:1px solid rgba(255,255,255,0.4);'
                        f'color:white;font-size:11px;font-weight:700;min-width:4px;">'
                        + (f"+{_pct}%" if _pct > 1 else "") + '</div>'
                    )
                    _lbl_segs += (
                        f'<div style="flex:{_pct};text-align:center;padding-top:4px;">'
                        f'<div style="font-size:10px;color:#636E72;white-space:nowrap;'
                        f'overflow:hidden;text-overflow:ellipsis;max-width:90px;margin:0 auto;">{_esc(_label)}</div>'
                        f'<div style="font-size:11px;color:{_col};font-weight:700;">+{_pct}%</div>'
                        f'</div>'
                    )
                if _remaining > 0:
                    _bar_segs += f'<div style="flex:{_remaining};background:#E8ECF0;min-width:4px;"></div>'
                    _lbl_segs += f'<div style="flex:{_remaining};"></div>'
                _bar_segs += (
                    f'<div style="width:56px;background:#2D2A70;display:flex;align-items:center;'
                    f'justify-content:center;color:white;font-size:13px;font-weight:700;flex-shrink:0;">'
                    f'{_projected}%</div>'
                )

                st.markdown(
                    '<div class="card" style="margin-top:4px;">'
                    '<div class="section-header" style="margin-bottom:4px;">Match Score Simulator</div>'
                    '<div class="section-sub" style="margin-bottom:8px;">Estimated score impact of applying top recommendations</div>'
                    # Heuristic disclaimer — visible to user, per adjusted spec requirement
                    '<div style="font-size:12px;color:#E17055;font-style:italic;margin-bottom:16px;">'
                    'Estimated impact based on recommendation priority. Not a predictive model.</div>'
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
                    f'<span style="font-size:13px;color:#636E72;font-weight:600;">Current: {_base}%</span>'
                    f'<span style="font-size:13px;color:#00B894;font-weight:700;">Projected: {_projected}%</span>'
                    '</div>'
                    f'<div style="display:flex;width:100%;height:44px;border-radius:8px;overflow:hidden;margin-bottom:6px;">{_bar_segs}</div>'
                    f'<div style="display:flex;width:100%;">{_lbl_segs}</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            except Exception as _sim_err:
                st.caption(f"Simulator could not render: {_sim_err}")


# ═══════════════════════════════════════════════════════════════════════════
# THREE COLUMN ANALYSIS — from appv2.py
# Gate: gap_analysis is not None
# V3 change: _concerns_html and _keyword_coverage_html now show ALL items
#            (truncation limits removed in utility functions above).
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["gap_analysis"] is not None:
    gap       = st.session_state["gap_analysis"]
    strengths = gap.get("strength_areas") or []

    col_l, col_c, col_r = st.columns(3)

    with col_l:
        bullets = "".join(
            '<div style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid #F4F6FB;'
            'font-size:13px;color:#636E72;line-height:1.4;">'
            '<span style="color:#00B894;flex-shrink:0;">✅</span>'
            f'<span>{_esc(s)}</span>'
            '</div>'
            for s in strengths
        ) or '<div style="color:#636E72;font-size:13px;font-style:italic;">No strengths listed.</div>'
        st.markdown(
            '<div class="card card-green-border" style="min-height:280px;">'
            '<div style="font-size:15px;font-weight:700;color:#1A1A2E;margin-bottom:14px;">'
            '✅ Why You\'re a Great Fit</div>'
            + bullets +
            '</div>',
            unsafe_allow_html=True,
        )

    with col_c:
        concerns = _concerns_html(gap)
        st.markdown(
            '<div class="card card-orange-border" style="min-height:280px;">'
            '<div style="font-size:15px;font-weight:700;color:#1A1A2E;margin-bottom:14px;">'
            '⚠️ Hiring Manager Concerns</div>'
            + concerns +
            '</div>',
            unsafe_allow_html=True,
        )

    with col_r:
        kw_html = _keyword_coverage_html(gap)
        st.markdown(
            '<div class="card card-purple-border" style="min-height:280px;">'
            '<div style="font-size:15px;font-weight:700;color:#1A1A2E;margin-bottom:14px;">'
            '🔍 ATS Keyword Coverage</div>'
            + kw_html +
            '</div>',
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# IMPROVEMENT OPPORTUNITIES — NEW in V3 (core product section)
# Gate: gap_analysis is not None
# Source: gap_analysis.improvement_opportunities — ALL items, no truncation
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["gap_analysis"] is not None:
    imp_opps = (st.session_state["gap_analysis"].get("improvement_opportunities") or [])
    if imp_opps:
        imp_items = "".join(
            '<div style="display:flex;gap:14px;padding:10px 0;border-bottom:1px solid #F4F6FB;">'
            f'<div style="width:24px;height:24px;border-radius:50%;background:#FFF3E0;color:#E17055;'
            f'display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0;">{i}</div>'
            f'<div style="font-size:14px;color:#1A1A2E;line-height:1.6;word-wrap:break-word;">{_esc(item)}</div>'
            '</div>'
            for i, item in enumerate(imp_opps, start=1)
        )
        st.markdown(
            '<div class="card card-orange-border">'
            '<div class="section-header" style="margin-bottom:4px;">💡 Improvement Opportunities</div>'
            '<div class="section-sub">Specific areas where your application can be strengthened</div>'
            + imp_items +
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No additional improvement opportunities identified.")


# ═══════════════════════════════════════════════════════════════════════════
# JD UNDERSTANDING — NEW in V3 (supporting diagnostic, collapsed)
# Gate: jd_analysis is not None
# Shows all 9 fields from jd_analysis. No truncation.
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["jd_analysis"] is not None:
    with st.expander("📋 How the AI Understood This Job Description", expanded=False):
        _jd = st.session_state["jd_analysis"] or {}
        # Row 1: three summary metrics
        _jc1, _jc2, _jc3 = st.columns(3)
        with _jc1:
            st.markdown(
                '<div class="card card-slim"><div class="small-caps" style="margin-bottom:6px;">Role</div>'
                f'<div style="font-size:15px;font-weight:700;color:#1A1A2E;word-wrap:break-word;">{_esc(_jd.get("role_name") or "—")}</div></div>',
                unsafe_allow_html=True,
            )
        with _jc2:
            st.markdown(
                '<div class="card card-slim"><div class="small-caps" style="margin-bottom:6px;">Company</div>'
                f'<div style="font-size:15px;font-weight:700;color:#1A1A2E;word-wrap:break-word;">{_esc(_jd.get("company_name") or "—")}</div></div>',
                unsafe_allow_html=True,
            )
        with _jc3:
            st.markdown(
                '<div class="card card-slim"><div class="small-caps" style="margin-bottom:6px;">Experience Required</div>'
                f'<div style="font-size:15px;font-weight:700;color:#1A1A2E;word-wrap:break-word;">{_esc(_jd.get("experience_required") or "—")}</div></div>',
                unsafe_allow_html=True,
            )
        # Row 2: two columns — skills left, tools/responsibilities/keywords right
        _jd_left, _jd_right = st.columns(2)
        with _jd_left:
            st.markdown(
                '<div class="card" style="min-height:200px;">'
                '<div style="font-size:12px;font-weight:700;color:#5B4CF5;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">Must-Have Skills</div>'
                + _jd_list_html(_jd.get("must_have_skills") or []) +
                '<div style="font-size:12px;font-weight:700;color:#5B4CF5;letter-spacing:1px;text-transform:uppercase;margin:14px 0 8px;">Good-to-Have Skills</div>'
                + _jd_list_html(_jd.get("good_to_have_skills") or []) +
                '<div style="font-size:12px;font-weight:700;color:#5B4CF5;letter-spacing:1px;text-transform:uppercase;margin:14px 0 8px;">Soft Skills</div>'
                + _jd_list_html(_jd.get("soft_skills") or []) +
                '</div>',
                unsafe_allow_html=True,
            )
        with _jd_right:
            st.markdown(
                '<div class="card" style="min-height:200px;">'
                '<div style="font-size:12px;font-weight:700;color:#5B4CF5;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">Tools Mentioned</div>'
                + _jd_list_html(_jd.get("tools_mentioned") or []) +
                '<div style="font-size:12px;font-weight:700;color:#5B4CF5;letter-spacing:1px;text-transform:uppercase;margin:14px 0 8px;">Responsibilities</div>'
                + _jd_list_html(_jd.get("responsibilities") or []) +
                '<div style="font-size:12px;font-weight:700;color:#5B4CF5;letter-spacing:1px;text-transform:uppercase;margin:14px 0 8px;">Keywords Ranked</div>'
                + _jd_list_html(_jd.get("keywords_ranked") or []) +
                '</div>',
                unsafe_allow_html=True,
            )


# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS PIPELINE — verbatim from appv2.py
# Gate: analysis_complete == True
# Single-line HTML string concatenation (Streamlit rendering constraint).
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"]:
    pipe_steps = [
        ("JD Parsed",                        "#00B894", False),
        ("Resume Parsed",                    "#00B894", False),
        ("Keyword Extraction",               "#00B894", False),
        ("Gap Analysis",                     "#00B894", False),
        ("Resume Recommendations Generated", "#5B4CF5", True),
    ]
    pipe_html = ""
    for i, (label, color, bold) in enumerate(pipe_steps):
        if i > 0:
            pipe_html += (
                '<div style="flex:1;height:2px;background:#00B894;'
                'margin-bottom:22px;min-width:12px;"></div>'
            )
        fw = "font-weight:700;" if bold else ""
        pipe_html += (
            f'<div style="display:flex;flex-direction:column;align-items:center;min-width:72px;max-width:110px;">'
            f'<div style="width:34px;height:34px;border-radius:50%;background:{color};color:white;'
            f'display:flex;align-items:center;justify-content:center;font-size:15px;">✓</div>'
            f'<div style="font-size:11px;color:{color};margin-top:6px;text-align:center;{fw}">{_esc(label)}</div>'
            f'</div>'
        )
    st.markdown(
        '<div class="card card-slim" style="margin-top:8px;">'
        '<div class="small-caps" style="margin-bottom:16px;">⚙ Analysis Pipeline</div>'
        f'<div style="display:flex;align-items:center;justify-content:center;flex-wrap:nowrap;">{pipe_html}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# RESUME IMPROVEMENT PLAN — V3: unified section (header + chips + cards)
# Gate: analysis_complete == True
# V3 change: merged from two separate V2 blocks (priority chips were before
# Three Column; cards were after Pipeline). Now unified after Pipeline.
# Header renamed from "Resume Improvement Priority" to "Resume Improvement Plan".
# Shows ALL priority_actions, no truncation.
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"] and st.session_state["tailoring_output"] is not None:
    _rip_out         = st.session_state["tailoring_output"]
    _rip_match_score = (st.session_state["gap_analysis"] or {}).get("match_score", 0)
    _rip_all_actions = _rip_out.get("priority_actions") or []
    # Fix 3 Rule A (P11/FD01): score-aware filtering for strong matches (>=85).
    # Falls back to single highest-priority Medium item if no High items exist.
    # Rule C (31-84%): _score_aware_filter returns actions unchanged.
    _rip_actions = _score_aware_filter(_rip_all_actions, _rip_match_score)
    _rip_high    = sum(1 for a in _rip_actions if (a.get("estimated_match_score_impact") or {}).get("level","Low") == "High")
    _rip_med     = sum(1 for a in _rip_actions if (a.get("estimated_match_score_impact") or {}).get("level","Low") == "Medium")
    _rip_low     = sum(1 for a in _rip_actions if (a.get("estimated_match_score_impact") or {}).get("level","Low") == "Low")

    _rip_chips = (
        (f'<span style="background:#FFEBEE;color:#D63031;border:1px solid #FFCDD2;'
         f'padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;margin-right:8px;">'
         f'🔴 {_rip_high} High Impact</span>' if _rip_high else '') +
        (f'<span style="background:#FFF3E0;color:#E17055;border:1px solid #FFE0B2;'
         f'padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;margin-right:8px;">'
         f'🟡 {_rip_med} Medium Impact</span>' if _rip_med else '') +
        (f'<span style="background:#F5F5F5;color:#636E72;border:1px solid #E0E0E0;'
         f'padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;">'
         f'⚪ {_rip_low} Low Impact</span>' if _rip_low else '')
    )

    st.markdown(
        '<div style="margin-top:8px;margin-bottom:4px;">'
        '<div class="section-header">Resume Improvement Plan</div>'
        '<div class="section-sub">Ranked by expected impact on recruiter and ATS evaluation</div>'
        f'<div style="margin-bottom:8px;">{_rip_chips}</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Fix 3 Rule A: caption shown only when the strong-match filter is active.
    try:
        _rip_score_int = int(_rip_match_score or 0)
    except (TypeError, ValueError):
        _rip_score_int = 0
    if _rip_score_int >= 85:
        st.caption("Strong match detected — showing high-impact optimizations only.")

    for i in range(0, len(_rip_actions), 2):
        pair = _rip_actions[i:i+2]
        cols = st.columns(len(pair))
        for j, action in enumerate(pair):
            lvl      = (action.get("estimated_match_score_impact") or {}).get("level","Low")
            expl     = (action.get("estimated_match_score_impact") or {}).get("explanation","")
            act_full = _esc(action.get("action") or "")
            with cols[j]:
                st.markdown(
                    '<div class="card" style="position:relative;">'
                    '<div style="margin-bottom:10px;">'
                    + _priority_badge(lvl) +
                    '</div>'
                    f'<div style="font-size:15px;font-weight:700;color:#1A1A2E;margin-bottom:8px;'
                    f'line-height:1.4;word-wrap:break-word;">{act_full}</div>'
                    f'<div style="font-size:13px;color:#636E72;line-height:1.6;margin-bottom:14px;'
                    f'word-wrap:break-word;">{_esc(expl)}</div>'
                    '<div style="border-top:1px solid #F4F6FB;padding-top:10px;">'
                    '<span style="font-size:12px;color:#5B4CF5;font-weight:600;cursor:default;">'
                    '↓ View Suggested Rewrite</span>'
                    '</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )


# ═══════════════════════════════════════════════════════════════════════════
# AI RESUME REWRITES — verbatim from appv2.py
# Gate: analysis_complete == True
# Combines: experience_section_rewrites → project_section_rewrites →
#           professional_summary_recommendations → skills_section_recommendations
# st.code(suggested, language=None) for native copy-to-clipboard.
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"] and st.session_state["tailoring_output"] is not None:
    out      = st.session_state["tailoring_output"]
    exp_rw    = out.get("experience_section_rewrites")              or []
    proj_rw   = out.get("project_section_rewrites")                 or []
    sum_recs  = out.get("professional_summary_recommendations")     or []
    skill_recs = out.get("skills_section_recommendations")          or []

    all_rewrites = (
        [("Experience Rewrite", r) for r in exp_rw]   +
        [("Project Rewrite",    r) for r in proj_rw]  +
        [("Summary Rewrite",    r) for r in sum_recs]  +
        [("Skills Rewrite",     r) for r in skill_recs]
    )

    # Fix 3 Rule B (P11/FD02): domain mismatch detection.
    # match_score <= 30 AND cannot_address has 3+ items signals the role is
    # likely outside the candidate's domain — rewrites have limited ability
    # to close that gap. Section is collapsed, not hidden, for transparency.
    _rw_match_score = (st.session_state["gap_analysis"] or {}).get("match_score", 0)
    try:
        _rw_score_int = int(_rw_match_score or 0)
    except (TypeError, ValueError):
        _rw_score_int = 0
    _rw_cannot_addr_count = len(out.get("cannot_address") or [])
    _domain_mismatch = _rw_score_int <= 30 and _rw_cannot_addr_count >= 3

    if all_rewrites:
        if _domain_mismatch:
            # Fix P13: explicit vertical break before st.warning() — the
            # Resume Improvement Plan cards above carry box-shadow (8px blur)
            # and position:relative, which creates a stacking context whose
            # shadow visually bleeds into native Streamlit widgets that
            # immediately follow. 24px clears the shadow radius with margin.
            st.markdown('<div style="margin-top:24px;"></div>', unsafe_allow_html=True)
            st.warning(
                "⚠️ Major domain mismatch detected. Resume tailoring has "
                "limited ability to close this gap — see 'Gaps That Cannot "
                "Be Closed' above. Rewrites are shown below for transparency."
            )
            st.markdown(
                '<div style="margin-top:8px;">'
                '<div class="section-header">AI Resume Rewrites</div>'
                '<div class="section-sub">Copy the improved version directly into your resume</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            _rewrite_container = st.expander("View Resume Rewrites Anyway", expanded=False)
        else:
            st.markdown(
                '<div style="margin-top:8px;">'
                '<div class="section-header">AI Resume Rewrites</div>'
                '<div class="section-sub">Copy the improved version directly into your resume</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            _rewrite_container = contextlib.nullcontext()

        with _rewrite_container:
            for idx, (kind, rw) in enumerate(all_rewrites, start=1):
                original  = rw.get("original","")
                suggested = rw.get("suggested","")
                reason    = rw.get("reason","")
                expanded  = idx <= 2 and not _domain_mismatch

                with st.expander(f"📝 {kind} {idx}", expanded=expanded):
                    col_orig, col_impr = st.columns(2)
                    with col_orig:
                        orig_body = _esc(original) if original else "<em style='color:#9B9B9B;'>None present</em>"
                        st.markdown(
                            '<div style="background:#F8F9FA;border:1px solid #E8ECF0;border-radius:8px;padding:16px;height:100%;">'
                            '<div style="font-size:11px;font-weight:700;color:#9B9B9B;letter-spacing:1.2px;'
                            'text-transform:uppercase;margin-bottom:10px;">Current Resume</div>'
                            f'<div style="font-size:13px;color:#2D3436;line-height:1.7;word-wrap:break-word;">'
                            f'{orig_body}</div>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                    with col_impr:
                        st.markdown(
                            '<div style="background:#F0FFF4;border:1px solid #C3E6CB;border-radius:8px;padding:16px;height:100%;">'
                            '<div style="font-size:11px;font-weight:700;color:#00B894;letter-spacing:1.2px;'
                            'text-transform:uppercase;margin-bottom:10px;">AI Improved Version</div>'
                            f'<div style="font-size:13px;color:#2D3436;line-height:1.7;word-wrap:break-word;">'
                            f'{_esc(suggested) if suggested else "<em style=\"color:#9B9B9B;\">No suggestion available</em>"}</div>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        '<div style="font-size:11px;color:#636E72;margin-top:10px;margin-bottom:2px;">'
                        '📋 <strong>Copy improved text</strong></div>',
                        unsafe_allow_html=True,
                    )
                    st.code(suggested or "", language=None)
                    if reason:
                        st.markdown(
                            f'<div style="background:#FFFDF0;border-left:3px solid #F4D03F;'
                            f'border-radius:0 4px 4px 0;padding:10px 14px;margin-top:8px;'
                            f'font-size:13px;color:#2D3436;line-height:1.6;">'
                            f'💡 <strong style="color:#636E72;">Why this works:</strong> {_esc(reason)}</div>',
                            unsafe_allow_html=True,
                        )


# ═══════════════════════════════════════════════════════════════════════════
# KEYWORD OPTIMIZATION RECOMMENDATIONS — NEW in V3 (supporting diagnostic)
# Gate: analysis_complete == True
# Source: tailoring_output.keyword_optimization_recommendations — ALL items
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"] and st.session_state["tailoring_output"] is not None:
    _kw_recs = (st.session_state["tailoring_output"].get("keyword_optimization_recommendations") or [])
    if _kw_recs:
        kw_items = "".join(
            '<div style="display:flex;gap:14px;padding:10px 0;border-bottom:1px solid #F4F6FB;">'
            f'<div style="width:24px;height:24px;border-radius:50%;background:#EEF0FF;color:#5B4CF5;'
            f'display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0;">{i}</div>'
            f'<div style="font-size:14px;color:#1A1A2E;line-height:1.6;word-wrap:break-word;">{_esc(item)}</div>'
            '</div>'
            for i, item in enumerate(_kw_recs, start=1)
        )
        st.markdown(
            '<div class="card card-purple-border">'
            '<div class="section-header" style="margin-bottom:4px;">🔍 Keyword Optimization Recommendations</div>'
            '<div class="section-sub">ATS-targeted keyword guidance from the tailoring engine</div>'
            + kw_items +
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No keyword recommendations generated.")


# ═══════════════════════════════════════════════════════════════════════════
# UNCLOSEABLE GAPS — verbatim from appv2.py
# Gate: analysis_complete == True AND cannot_address non-empty
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state["analysis_complete"] and st.session_state["tailoring_output"] is not None:
    cannot_address = (st.session_state["tailoring_output"].get("cannot_address") or [])
    if cannot_address:
        st.markdown(
            '<div class="card" style="border-left:4px solid #E17055;margin-top:8px;">'
            '<div style="font-size:16px;font-weight:700;color:#1A1A2E;margin-bottom:4px;">'
            '⚠️ Gaps That Cannot Be Closed Through Rewording</div>'
            '<div style="font-size:13px;color:#636E72;margin-bottom:16px;">'
            'These skills cannot truthfully be added through rewording. '
            'Consider acquiring them before applying to roles that list them as requirements.</div>'
            + "".join(
                '<div style="display:flex;gap:8px;padding:8px 0;border-bottom:1px solid #F4F6FB;">'
                '<span style="flex-shrink:0;color:#E17055;font-weight:700;">—</span>'
                f'<span style="font-size:14px;color:#2D3436;line-height:1.5;word-wrap:break-word;">'
                f'{_esc(item)}</span>'
                '</div>'
                for item in cannot_address
            ) +
            '</div>',
            unsafe_allow_html=True,
        )

