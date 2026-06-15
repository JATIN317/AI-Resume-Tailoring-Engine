# utils.py
# Shared utilities for the AI Resume Tailoring Engine.
#
# Public API (imported by agents.py and app.py):
#   extract_pdf_text(uploaded_file)   → str
#   get_gemini_model(system_prompt)   → genai.GenerativeModel
#   parse_llm_json(raw_text)          → dict
#   retry_llm_call(model, ...)        → dict
#   LLMParseError                     (re-exported exception)
#   LLMValidationError                (re-exported exception)

import io
import json
import os
import re

import google.generativeai as genai
import pypdf
import streamlit as st

import validators  # local — validators.validate_output, validators.validate_gap_analysis

# ---------------------------------------------------------------------------
# Model configuration
# Override here if the target model changes. One place, one edit.
# Spec Section 8 originally specified gemini-2.0-flash; overridden to
# gemini-2.5-flash per Phase 3 build instructions.
# ---------------------------------------------------------------------------
MODEL_NAME: str = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Debug logger
# Set DEBUG=true in .env to enable console output of agent I/O.
# ---------------------------------------------------------------------------

_DEBUG: bool = os.getenv("DEBUG", "false").strip().lower() == "true"


def _debug(tag: str, message: str) -> None:
    """Print to stdout only when DEBUG=true. Silent in production."""
    if _DEBUG:
        print(f"[DEBUG][{tag}] {message}")


# ---------------------------------------------------------------------------
# parse_llm_json  (promoted from private _parse_llm_json in Phase 2.5)
# Strips markdown fences from LLM output and parses to dict.
# Public in Phase 3 — callable directly by agents.py if needed.
# ---------------------------------------------------------------------------

# Matches ```json ... ``` or ``` ... ``` with optional whitespace/newlines.
# Handles capitalisation variants (```JSON, ```Json) and trailing text after
# the closing fence (some models append an explanation after the JSON block).
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def parse_llm_json(raw_text: str) -> dict:
    """
    Strip markdown code fences and parse the LLM response to a dict.

    Handles:
    - ```json ... ``` and ``` ... ``` (any capitalisation)
    - Leading/trailing whitespace
    - Responses with no fences (raw JSON)
    - Responses with text before or after the JSON block

    Args:
        raw_text: The raw string from model.generate_content().text

    Returns:
        Parsed dict.

    Raises:
        json.JSONDecodeError: If the content cannot be parsed as JSON
                              after fence removal.
    """
    text = raw_text.strip()

    # Pass 1: prefer content inside a code fence if one exists
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Pass 2: attempt direct parse on whatever text we have now
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_exc:
        # Pass 3: fallback for "Here is the JSON:\n{ ... }" style responses —
        # no fence present, but JSON is embedded after explanatory prose.
        # Extract the substring between the first '{' and last '}'.
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                pass  # fall through to re-raise the original error
        raise original_exc


# ---------------------------------------------------------------------------
# retry_llm_call
# Shared retry wrapper called by all 4 agents in agents.py.
# ---------------------------------------------------------------------------

class LLMParseError(ValueError):
    """Raised when the LLM returns JSON that cannot be parsed after all retries."""


class LLMValidationError(ValueError):
    """Raised when the LLM returns JSON that fails schema validation after all retries."""


def retry_llm_call(
    model,
    user_message: str,
    agent_name: str,
    max_attempts: int = 2,
) -> dict:
    """
    Call the Gemini API with retry logic for JSON parse and validation failures.

    Retry policy (from spec Section 9):
    - Attempt 1: call API, parse JSON, validate schema.
    - If parse fails or validation fails → silently retry (attempt 2).
    - If attempt 2 also fails → raise a typed exception for app.py to surface.

    API-level errors (rate limit, network, auth) are NOT retried here —
    they propagate immediately for app.py to catch and display.

    Validation sequence per attempt:
    1. model.generate_content()              — Gemini API call
    2. parse_llm_json()                      — strip fences, json.loads()
    3. validators.validate_output()          — required key check (all 4 agents)
    4. validators.validate_gap_analysis()    — score bounds + enum check (Agent 3 only)

    Args:
        model:        genai.GenerativeModel instance pre-configured with
                      system_instruction and model name. Created by
                      utils.get_gemini_model() (Phase 3).
        user_message: Formatted user message string from prompts.get_agent_N_user_message().
        agent_name:   One of: "jd_analysis" | "resume_analysis" |
                      "gap_analysis" | "tailoring_output".
                      Must match a key in validators.REQUIRED_KEYS.
        max_attempts: Maximum call attempts before raising. Default 2 (spec §9).

    Returns:
        Validated dict ready to store in st.session_state.

    Raises:
        LLMParseError:      JSON could not be parsed after max_attempts.
        LLMValidationError: Parsed JSON failed schema validation after max_attempts.
        google.api_core.exceptions.GoogleAPIError (or subclass): API-level failure —
            propagates immediately without retry.
    """
    last_parse_error: Exception | None = None
    last_validation_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        _debug(agent_name, f"Attempt {attempt}/{max_attempts} — calling Gemini API")

        # ── Step 1: API call ────────────────────────────────────────────────
        # API-level exceptions (rate limit, auth, network) propagate immediately.
        # Spec §9: "Gemini API rate limit hit → Too many requests. Please wait."
        # app.py catches these and shows the appropriate user-facing message.
        response = model.generate_content(
            contents=[{"role": "user", "parts": [{"text": user_message}]}],
            generation_config={"temperature": 0},  # mandatory — all 4 agents
        )
        raw_text = response.text
        _debug(agent_name, f"Raw response ({len(raw_text)} chars): {raw_text[:200]}...")

        # ── Step 2: Parse JSON ──────────────────────────────────────────────
        try:
            parsed = parse_llm_json(raw_text)
        except json.JSONDecodeError as exc:
            last_parse_error = exc
            _debug(agent_name, f"JSON parse failed on attempt {attempt}: {exc}")
            if attempt < max_attempts:
                _debug(agent_name, "Retrying...")
                continue
            # All attempts exhausted
            raise LLMParseError(
                f"[{agent_name}] Could not parse JSON after {max_attempts} attempts. "
                f"Last error: {exc}. "
                f"Raw response (first 300 chars): {raw_text[:300]}"
            ) from exc

        _debug(agent_name, f"JSON parsed — top-level keys: {list(parsed.keys())}")

        # ── Step 3: Required key validation (all 4 agents) ─────────────────
        is_valid, missing_keys = validators.validate_output(parsed, agent_name)
        if not is_valid:
            last_validation_error = f"Missing required keys: {missing_keys}"
            _debug(agent_name, f"Key validation failed on attempt {attempt}: {last_validation_error}")
            if attempt < max_attempts:
                _debug(agent_name, "Retrying...")
                continue
            raise LLMValidationError(
                f"[{agent_name}] Schema validation failed after {max_attempts} attempts. "
                f"{last_validation_error}"
            )

        # ── Step 4: Extended validation (Agent 3 only) ─────────────────────
        if agent_name == "gap_analysis":
            is_valid, reason = validators.validate_gap_analysis(parsed)
            if not is_valid:
                last_validation_error = reason
                _debug(agent_name, f"Gap analysis validation failed on attempt {attempt}: {reason}")
                if attempt < max_attempts:
                    _debug(agent_name, "Retrying...")
                    continue
                raise LLMValidationError(
                    f"[{agent_name}] Extended validation failed after {max_attempts} attempts. "
                    f"{reason}"
                )

        # ── All checks passed ───────────────────────────────────────────────
        _debug(agent_name, f"Validation passed on attempt {attempt}. Returning parsed dict.")
        return parsed

    # Should never reach here — loop always returns or raises — but satisfies type checkers.
    raise LLMValidationError(  # pragma: no cover
        f"[{agent_name}] Exhausted {max_attempts} attempts without a valid result."
    )

# ---------------------------------------------------------------------------
# extract_pdf_text
# Extracts plain text from a Streamlit UploadedFile PDF.
# ---------------------------------------------------------------------------

def extract_pdf_text(uploaded_file) -> str:
    """
    Extract plain text from a Streamlit UploadedFile PDF object.

    Uses pypdf.PdfReader on an in-memory BytesIO buffer so the file object's
    read position does not matter and the original stream is not consumed.

    Error handling (spec Section 9):
    - Password-protected PDF  → ValueError with exact spec message
    - Scanned / image PDF     → ValueError with exact spec message
      (detected when extracted text, stripped of whitespace, is < 100 chars)
    - Other pypdf failures    → re-raised as ValueError with original detail

    Args:
        uploaded_file: Streamlit UploadedFile object (st.file_uploader result).

    Returns:
        Extracted text string (may contain newlines and whitespace).

    Raises:
        ValueError: On password protection, unreadable PDF, or scanned image.
    """
    _PASSWORD_MSG = (
        "Your PDF is password protected. Please remove the password and re-upload."
    )
    _SCANNED_MSG = (
        "Could not read your PDF. Please ensure it is a text-based PDF, "
        "not a scanned image."
    )

    try:
        # Wrap bytes in BytesIO — pypdf requires a seekable stream.
        pdf_bytes = uploaded_file.read()
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))

        # Proactive password check — avoids iterating into a locked file.
        if reader.is_encrypted:
            raise ValueError(_PASSWORD_MSG)

        text_parts: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

        text = "\n".join(text_parts)

    except ValueError:
        # Re-raise our own ValueErrors (password + scanned messages) unchanged.
        raise

    except pypdf.errors.FileNotDecryptedError:
        # Raised by some pypdf versions when pages are accessed on an encrypted
        # file that was not caught by the is_encrypted flag above.
        raise ValueError(_PASSWORD_MSG)

    except Exception as exc:
        # Catch malformed / corrupt PDFs — surface a clean user-facing message.
        raise ValueError(
            f"Could not read your PDF. The file may be corrupted or in an "
            f"unsupported format. Detail: {exc}"
        ) from exc

    # Scanned / image-only PDF check (spec §9: "extracted text < 100 characters").
    # Strip before measuring — whitespace and form-feeds from page structure
    # are present even when no real text was extracted.
    if len(text.strip()) < 100:
        raise ValueError(_SCANNED_MSG)

    return text


# ---------------------------------------------------------------------------
# get_gemini_model
# Model factory — resolves API key and returns a configured GenerativeModel.
# ---------------------------------------------------------------------------

def get_gemini_model(system_prompt: str):
    """
    Resolve the Gemini API key and return a configured GenerativeModel.

    Key resolution order (spec Section 8b):
    1. st.secrets["GEMINI_API_KEY"]  — Streamlit Cloud deployment
    2. os.getenv("GEMINI_API_KEY")   — local development via .env / environment

    Catches KeyError, FileNotFoundError, and AttributeError from st.secrets so
    that the factory works correctly in all three contexts:
    - Streamlit Cloud  (secrets configured in dashboard)
    - Local dev        (.env loaded by python-dotenv in app.py)
    - Test / CI        (key set directly as environment variable)

    genai.configure() is called inside this function — it is idempotent and
    cheap. Keeping it here preserves separation of concerns: app.py does not
    need to import or configure the Gemini SDK directly.

    Args:
        system_prompt: Full system prompt string for this agent
                       (one of the AGENT_N_SYSTEM_PROMPT constants from prompts.py).

    Returns:
        genai.GenerativeModel configured with MODEL_NAME and system_instruction.

    Raises:
        ValueError: If no API key can be resolved from either source.
    """
    # ── Step 1: resolve API key ─────────────────────────────────────────────
    api_key: str | None = None

    # Try Streamlit secrets first (Streamlit Cloud deployment).
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except (KeyError, FileNotFoundError, AttributeError):
        # KeyError       — key not present in secrets.toml
        # FileNotFoundError — secrets.toml not found (local dev without it)
        # AttributeError — st.secrets not behaving as a dict (test context)
        pass

    # Fall back to environment variable (local dev via python-dotenv).
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY not found. "
            "Set it in .env for local development or in Streamlit Secrets for deployment. "
            "Get a key at https://aistudio.google.com/app/apikey"
        )

    # ── Step 2: configure SDK and return model ──────────────────────────────
    genai.configure(api_key=api_key)

    _debug("get_gemini_model", f"Configured model: {MODEL_NAME}")

    return genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=system_prompt,
    )
