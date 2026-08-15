"""
Profanity filter for SPARTA's chatbot.

Covers common English and Filipino/Tagalog profanity, since students are
likely to message in English, Tagalog, or Taglish. This is intentionally
a straightforward word-list + normalization approach rather than a full
ML classifier — easy to audit, easy to extend, and fast enough to run on
every single chat message with no noticeable latency.

To add or remove terms: edit BLOCKED_TERMS below. Keep entries lowercase,
no spaces (the matcher already handles spacing/punctuation variants).
"""
import re

# Word list intentionally kept out of source comments/docstrings so it
# doesn't show up in casual code review — the filter logic itself is what
# matters for review purposes, not the specific list contents.
BLOCKED_TERMS = {
    # English
    "fuck", "shit", "bitch", "asshole", "bastard", "dick", "pussy", "cunt",
    "whore", "slut", "faggot", "nigger", "nigga", "retard", "cock", "motherfucker",
    "dumbass", "jackass", "prick", "twat",
    # Filipino / Tagalog
    "putangina", "puta", "gago", "gagi", "tangina", "tanga", "bobo", "ulol",
    "hayop", "hayup", "leche", "lintik", "pakshet", "pakyu", "tarantado",
    "kupal", "peste", "punyeta", "syet", "shet", "inutil", "walanghiya",
    "bwisit", "kingina", "putangna",
}

# Common leetspeak / separator substitutions used to dodge basic filters
_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s",
})


def _normalize(text: str) -> str:
    """Lowercase and map common leetspeak substitutions. Deliberately does
    NOT strip spacing/punctuation here — that's handled by the regex
    pattern itself (see _build_pattern), so real word boundaries between
    separate, innocent words are preserved."""
    return text.lower().translate(_LEET_MAP)


def _build_pattern():
    # Each letter in a blocked term may repeat (catches "fuuuck") and may
    # be followed by 0+ separator characters — spaces, dots, dashes,
    # asterisks, underscores — to catch spaced-out or punctuated evasion
    # like "f.u.c.k" or "f u c k" without merging together unrelated words.
    sep = r"[\s\.\-_\*]*"
    parts = []
    for term in BLOCKED_TERMS:
        expanded = sep.join(f"{re.escape(ch)}+" for ch in term)
        parts.append(expanded)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


_PATTERN = _build_pattern()


def contains_profanity(text: str) -> bool:
    """Returns True if the given text contains blocked profanity, after
    normalizing for common spacing/leetspeak evasion tricks."""
    if not text:
        return False
    normalized = _normalize(text)
    return bool(_PATTERN.search(normalized))