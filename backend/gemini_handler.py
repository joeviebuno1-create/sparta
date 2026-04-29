"""
GEMINI 2.5 FLASH HANDLER FOR SPARTA
=====================================
Uses the NEW `google-genai` SDK (replaces deprecated `google-generativeai`).

Install:
    pip install google-genai

- Calls Gemini only with context already retrieved from your NeonDB
- Never answers from Gemini's own training data
- Supports both English and Tagalog responses
- Falls back gracefully if GEMINI_API_KEY is not set
"""

import os
from typing import List, Tuple, Any, Optional
from dotenv import load_dotenv

load_dotenv()

GEMINI_ENABLED = False
_client = None
genai_types = None

try:
    from google import genai
    from google.genai import types as _genai_types
    genai_types = _genai_types

    _key = os.getenv("GEMINI_API_KEY", "")
    if _key:
        print(f"[gemini] Key starts with: {_key[:10]}...")
        _client = genai.Client(api_key=_key)
        GEMINI_ENABLED = True
        print("✓ Gemini 2.5 Flash handler loaded (google-genai SDK).")
    else:
        print("[gemini] No GEMINI_API_KEY found — Gemini disabled.")

except ImportError as _e:
    print(f"[gemini] google-genai not installed ({_e}) — Gemini disabled.")
except Exception as _e:
    print(f"[gemini] Could not load google-genai ({type(_e).__name__}: {_e}) — Gemini disabled.")


_SYSTEM_EN = """You are SPARTA, the official AI assistant for Batangas State University (BSU) Lipa Campus.

STRICT RULES:
1. Answer ONLY from the <context> block provided.
2. If context lacks the answer, say: "I'm sorry, I don't have that information in my database right now. Please contact the BSU Lipa Campus admin office for assistance."
3. Never use your own training data or make up facts.
4. Be concise, friendly, and professional.
5. Use simple markdown (bold, bullets) when listing items.
6. Never mention "context", "database", "RAG", or "Gemini".
7. Answer in English."""

_SYSTEM_TL = """Ikaw si SPARTA, ang opisyal na AI assistant ng Batangas State University (BSU) Lipa Campus.

MAHIGPIT NA MGA PANUNTUNAN:
1. Sumagot LAMANG mula sa <context> block na ibinigay.
2. Kung hindi sapat ang context: "Paumanhin, wala pa akong ganoong impormasyon sa aking database. Makipag-ugnayan sa tanggapan ng BSU Lipa Campus admin para sa tulong."
3. Huwag gumamit ng sariling kaalaman o gumawa ng mga katotohanan.
4. Maging malinaw, magalang, at propesyonal.
5. Gamitin ang simpleng markdown kapag naglilista.
6. Huwag banggitin ang "context", "database", "RAG", o "Gemini".
7. Sumagot sa Filipino/Tagalog."""


def _context_blocks_to_text(context: List[Tuple[Any, float]], intent: str) -> str:
    if not context:
        return ""
    lines = []
    for doc, score in context:
        cls = doc.__class__.__name__
        if cls == "Authority":
            lines.append(
                f"PERSON: {doc.name} | POSITION: {doc.position} | DEPARTMENT: {doc.department}"
                + (f" | EMAIL: {doc.email}" if getattr(doc, 'email', None) else "")
                + (f" | PHONE: {doc.phone}" if getattr(doc, 'phone', None) else "")
                + (f" | OFFICE: {doc.office_location}" if getattr(doc, 'office_location', None) else "")
                + (f" | BIO: {doc.bio[:500]}" if getattr(doc, 'bio', None) else "")
            )
        elif cls == "RoomLocation":
            lines.append(
                f"LOCATION: {doc.name} | BUILDING: {doc.building} | FLOOR: {doc.floor}"
                + (f" | DESCRIPTION: {doc.description}" if getattr(doc, 'description', None) else "")
            )
        elif cls == "History":
            lines.append(f"HISTORY [{doc.year}]: {doc.title} — {doc.description}")
        elif cls == "Announcement":
            lines.append(f"ANNOUNCEMENT: {doc.title} | DATE: {getattr(doc, 'date_posted', 'N/A')} | {doc.content}")
        elif cls == "Organization":
            words = doc.name.split()
            acronym = ''.join(w[0].upper() for w in words if w)
            acronym_str = f" ({acronym})" if acronym and acronym != doc.name.upper() else ""
            member_lines = ""
            if hasattr(doc, 'members') and doc.members:
                member_lines = " | MEMBERS: " + "; ".join(
                    f"{m.name} [{m.position}]" for m in doc.members
                )
            lines.append(
                f"ORGANIZATION: {doc.name}{acronym_str}"
                + (f" | DESCRIPTION: {doc.description}" if getattr(doc, 'description', None) else "")
                + member_lines
            )
        else:
            lines.append(str(doc))
    return "\n".join(lines)


# Errors that are worth retrying (Gemini server-side / transient)
_RETRYABLE_CODES = {429, 500, 503, 504}
_RETRYABLE_PHRASES = ("unavailable", "resource exhausted", "overloaded",
                      "quota", "rate limit", "try again", "internal error")

def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception looks like a transient Gemini error."""
    msg = str(exc).lower()
    # HTTP status code present in message (e.g. "503 UNAVAILABLE")
    for code in _RETRYABLE_CODES:
        if str(code) in msg:
            return True
    return any(phrase in msg for phrase in _RETRYABLE_PHRASES)


def _call_gemini(system_prompt: str, user_message: str,
                 max_retries: int = 3, base_delay: float = 1.5) -> Optional[str]:
    """Core Gemini API call with exponential-backoff retry for transient errors."""
    global _client, genai_types
    if not GEMINI_ENABLED or _client is None:
        return None

    import time as _time

    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.2,
        max_output_tokens=512,
        top_p=0.8,
        safety_settings=[
            genai_types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_ONLY_HIGH"
            ),
            genai_types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_ONLY_HIGH"
            ),
            genai_types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_ONLY_HIGH"
            ),
            genai_types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_ONLY_HIGH"
            ),
        ],
    )

    for attempt in range(1, max_retries + 1):
        try:
            # Hard timeout via threading so a hung Gemini call never blocks forever
            import threading
            result_box = [None]
            error_box  = [None]

            def _call():
                try:
                    r = _client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=user_message,
                        config=config,
                    )
                    result_box[0] = r.text.strip() if r.text else None
                except Exception as e:
                    error_box[0] = e

            t = threading.Thread(target=_call, daemon=True)
            t.start()
            t.join(timeout=8)  # max 8 seconds per attempt

            if t.is_alive():
                # Gemini hung — treat as transient, retry or give up
                print(f"[gemini] Timeout on attempt {attempt}/{max_retries}")
                if attempt < max_retries:
                    _time.sleep(base_delay)
                    continue
                return None

            if error_box[0] is not None:
                raise error_box[0]

            return result_box[0] if result_box[0] else None

        except Exception as exc:
            if _is_retryable(exc) and attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))  # 1.5s, 3s …
                print(f"[gemini] Transient error (attempt {attempt}/{max_retries}), "
                      f"retrying in {delay:.1f}s: {exc}")
                _time.sleep(delay)
            else:
                # Non-retryable, or all retries exhausted — fall back to RAG
                print(f"[gemini] generate_content failed after {attempt} attempt(s): {exc}")
                return None


def generate_with_gemini(
    user_query: str,
    context: List[Tuple[Any, float]],
    intent: str,
    lang: str = "en",
) -> Optional[str]:
    """Generate response from structured DB context."""
    if not GEMINI_ENABLED or not context:
        return None
    context_text = _context_blocks_to_text(context, intent)
    if not context_text.strip():
        return None
    if len(context_text) > 12_000:
        context_text = context_text[:12_000] + "\n[...context truncated...]"
    system_prompt = _SYSTEM_TL if lang == "tl" else _SYSTEM_EN
    user_message = (
        f"<lang>{lang}</lang>\n"
        f"<context>\n{context_text}\n</context>\n\n"
        f"User question: {user_query}"
    )
    return _call_gemini(system_prompt, user_message)


def answer_from_faq_docs(
    user_query: str,
    faq_context_text: str,
    lang: str = "en",
) -> Optional[str]:
    """Answer using plain text from uploaded PDF FAQ documents."""
    if not GEMINI_ENABLED or not faq_context_text.strip():
        return None
    if len(faq_context_text) > 12_000:
        faq_context_text = faq_context_text[:12_000] + "\n[...truncated...]"
    system_prompt = _SYSTEM_TL if lang == "tl" else _SYSTEM_EN
    user_message = (
        f"<lang>{lang}</lang>\n"
        f"<context>\n{faq_context_text}\n</context>\n\n"
        f"User question: {user_query}"
    )
    return _call_gemini(system_prompt, user_message)