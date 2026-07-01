# Changelog — ResumeIQ
**AI Resume Tailoring Engine · AnalyticsShiksha · Built by Jatin Nair**

All notable changes to this project are documented here.
Format: `Added` · `Fixed` · `Changed` · `Deferred`

---

## v3.3-stable — V3.3C · July 2026

Final stable release of the V3.3 evaluation and stabilisation cycle.

### Fixed
- **P14 — Qualifier matching instability (architectural):** Agent 3 was instructed to check the `tools` field in resume JSON but failed to locate it reliably under token pressure — the field was buried in a large nested JSON object. Fix: surfaced `CANDIDATE TOOLS` and `CANDIDATE SKILLS` as explicit flat-list fields in `get_agent_3_user_message()`. Updated the QUALIFIER CATEGORY MATCHING RULE and few-shot example to reference these fields by name. JIRA now consistently matches "Ticketing System Proficiency" via qualifier example match across regression runs.
- **P15 — Agent 4 JSON truncation:** On verbose resume + JD combinations, Agent 4's large output occasionally exceeded token limits. Gemini returned a truncated response starting with ` ```json ` but no closing fence — `_FENCE_RE` requires a closing fence and silently passed the raw backtick string to `json.loads`, failing at char 0. Fix: pre-pass in `parse_llm_json()` strips the opening fence line before the regex runs; Pass 3 brace extraction then recovers the partial JSON. `max_output_tokens` also raised from 8192 to 16384.
- **P08 — Input section double render:** When a new file was uploaded after a completed analysis, Streamlit's implicit auto-rerun (triggered by `session_state` mutation mid-script) caused Run A's partial output to paint alongside Run B's clean render. Fix: `st.rerun()` added as the final statement inside the `if stored != new_sig:` block — aborts Run A's partial output immediately; Run B renders the input section exactly once.
- **P13 — Rule B warning box visual overlap:** The domain-mismatch `st.warning()` block immediately followed a custom HTML card with `box-shadow: 0 2px 8px` — the shadow bled over the warning box background. Fix: 24px spacer div inserted before `st.warning()`.

### Changed
- `max_output_tokens` raised from 8192 → 16384 in `utils.py`
- `get_agent_3_user_message()` now appends `CANDIDATE TOOLS` and `CANDIDATE SKILLS` as explicit flat lists after the resume JSON block

---

## V3.3B · July 2026

Display-layer UX refinements. No prompt changes.

### Added
- **Score-aware rewrite display (P11/FD01):** If `match_score >= 85`, Resume Improvement Plan shows High-impact items only with a "Strong match detected" caption. If zero High items exist, falls back to the single highest-priority Medium item — section is never empty.
- **Domain mismatch collapse (FD02):** If `match_score <= 30` and `cannot_address` has 3+ items, AI Resume Rewrites are collapsed inside `st.expander("View Resume Rewrites Anyway")` with a warning above. Preserves transparency without presenting rewrites as the primary path forward.
- **Simulator allow-list filter (P03):** Match Score Simulator now filters `priority_actions` by `action_type`. Only `ATS`, `Match`, and `Evidence` types are eligible for simulator display. `Structure`, `Credibility`, and any future unlisted types are excluded. Allow-list design — new action types are excluded by default until explicitly approved.

### Fixed
- Simulator no longer surfaces admin/formatting fixes (e.g. date corrections) as top-ranked simulator segments

---

## V3.3A · July 2026

Prompt refinements extending the qualifier matching foundation from V3.2/V3.3.

### Added
- **PRECEDENCE RULE (Agent 3):** Once a qualifier-derived must-have is matched via category label or qualifier example, all related examples are treated as satisfied — no double-penalisation. JIRA match → Zendesk no longer appears in `missing_keywords`.
- **EVIDENCE DENSITY RULE (Agent 4):** Rewrites must preserve all quantified metrics and business outcomes. If a rewrite cannot retain the number, the bullet is left unchanged and the keyword is recommended elsewhere.
- **`action_type` field (Agent 4):** Each `priority_action` now includes an optional `action_type` string (`ATS`, `Match`, `Evidence`, `Positioning`, `Structure`). Open enum — additional values can be added in future versions. Enables display-layer simulator filtering in V3.3B.
- **`few_shot_example_qualifier_matching` (Agent 3):** Complete worked example demonstrating JIRA → "Ticketing System Proficiency" qualifier match path, with annotation explaining why Zendesk is excluded from `missing_keywords` despite being absent.

---

## V3.3 / V3.3C Prompt Layer · June–July 2026

Foundation release for the qualifier matching architecture. Three targeted prompt changes.

### Fixed
- **P06/P09 — Qualifier extraction + JIRA regression:** Agent 1 was extracting "databases such as Snowflake, Redshift" as separate must-have skills. Fix: QUALIFIER RULE added to Agent 1 — qualifier examples are extracted into `qualifier_examples` dict (additive field, backward compatible), not promoted to `must_have_skills`. Agent 3 QUALIFIER CATEGORY MATCHING RULE added — checks category label OR any listed qualifier example for a full match.
- **P05 — Borderline hallucination in keyword recommendations:** Agent 4 was recommending candidates "imply" skills not in their resume ("link X to Y to suggest Z"). Fix: KEYWORD RECOMMENDATION INFERENCE GATE added to Agent 4 `<strict_constraints>` — prohibits implication language (`imply`, `suggest`, `link to`, `while not explicitly`). Includes negative few-shot example.
- **Qualifier label wording drift (P14 precursor):** CANONICAL LABEL RULE added to Agent 1 — category labels must use the JD's exact noun phrase, not the prompt's example wording. Few-shot example updated to use "systems" (matching real JD wording) not "tools."

### Added
- `qualifier_examples` field in Agent 1 output schema — dict mapping category label → list of qualifier example tools. Additive field, not added to `REQUIRED_KEYS`, backward compatible.

---

## V3.2 · June 2026

Targeted prompt and utility fixes addressing patterns discovered during golden dataset evaluation.

### Fixed
- **P04 — Simulator and Experience Gap Detail not rendering:** Added null-check guards in `app.py`. Simulator falls back to caption if `priority_actions` is empty. Experience Gap Detail expander only renders if at least one of `required`, `candidate`, `severity`, or `reason` is non-empty.
- **P07 — Agent 2 JSON parse failure on verbose resumes:** `max_output_tokens` raised from default to 8192 in `utils.py`.
- **P06 (partial) — "Such as" examples extracted as hard requirements:** QUALIFIER RULE foundation added. Full fix completed in V3.3.

---

## V3.1 · June 2026

Display layer restored. Regression from V2 diagnosed and fixed.

### Fixed
- **V2 regression (display layer):** V2 silently dropped `improvement_opportunities`, `keyword_optimization_recommendations`, and full `jd_analysis` display. Truncation added to `weak_sections[:3]` and `missing_skills[:4]`. Diagnosed by diffing all 5 backend files — `prompts.py`, `agents.py`, `validators.py`, `utils.py` were byte-for-byte identical between V1 and V2. Only `app.py` differed. No prompt changes required.
- **V3 Product Specification written:** Field Accountability principle — every backend output field must be rendered prominently, accessible via expander, or intentionally omitted with a documented reason.

### Added
- Improvement Opportunities section
- Keyword Optimization section
- JD Understanding expander (collapsed by default)
- Match Score Simulator expander (collapsed, heuristic disclaimer shown)
- Experience Gap Detail expander
- Unified Resume Improvement Plan section
- All truncation limits removed

---

## V2 · June 2026

Major UI redesign. Unintentionally introduced display-layer regression later diagnosed in V3.1.

### Added
- SaaS-style hero match score card
- 3-column analysis layout
- Before/after rewrite cards
- Pipeline step indicator
- Session state persistence across pipeline stages

### Changed
- Full UI rebuilt from V1's functional-but-minimal layout

### Regression introduced (discovered in V3.1)
- `improvement_opportunities` field silently not rendered
- `keyword_optimization_recommendations` field silently not rendered
- `jd_analysis` display removed
- `weak_sections` truncated to 3 items
- `missing_skills` truncated to 4 items
- Backend confirmed unchanged — regression was display layer only

---

## V1 · June 2026

Initial build. Working product, minimal UI.

### Added
- 4-agent sequential pipeline: JD Analyzer → Resume Analyzer → Gap Analyzer → Tailoring Agent
- Weighted scoring model: must-haves 60%, good-to-haves 20%, experience 15%, keywords 5%
- Discrete experience bands: 0 / 20 / 40 / 60 / 80 / 100
- Project contribution lift rule
- Inference gate blocking 4 hallucination patterns in Agent 4
- `cannot_address` field — gaps that cannot be truthfully closed through rewording
- All agents return structured JSON only
- `temperature=0` for all agents
- pypdf for text extraction
- Custom 3-pass JSON parser with retry logic

---

*ResumeIQ · AnalyticsShiksha · Built by Jatin Nair*
