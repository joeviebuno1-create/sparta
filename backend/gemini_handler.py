"""
GEMINI HANDLER — DISABLED (Pure RAG Mode)
==========================================
Gemini has been removed to fix Railway OOM issues.
The Gemini SDK alone consumed ~150MB of persistent RAM via gRPC connections,
pushing the app over Railway's 512MB limit when combined with sentence-transformers.

All functions return None so rag_chatbot.py falls back to its own
built-in template-based response generator — which works well for
structured DB data (people, locations, history, organizations).

FAQ PDF queries are handled directly by faq_retriever.py which returns
the best matching chunk as plain text.

To re-enable Gemini in future: restore gemini_handler_backup.py
"""

from typing import List, Tuple, Any, Optional

GEMINI_ENABLED = False

print("[gemini] Gemini disabled — running in pure RAG mode.")


def _context_blocks_to_text(context: List[Tuple[Any, float]], intent: str) -> str:
    """
    Kept for import compatibility with rag_chatbot.py.
    Converts DB model objects to plain text for context display.
    """
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


def generate_with_gemini(
    user_query: str,
    context: List[Tuple[Any, float]],
    intent: str,
    lang: str = "en",
) -> Optional[str]:
    """Disabled — returns None so rag_chatbot uses its template generator."""
    return None


def answer_from_faq_docs(
    user_query: str,
    faq_context_text: str,
    lang: str = "en",
) -> Optional[str]:
    """Disabled — returns None so rag_chatbot uses FAQ chunks directly."""
    return None