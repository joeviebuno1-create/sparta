"""
FAQ DOCUMENT RETRIEVER (Optimized)
====================================
Key performance fix: chunks are pre-computed and cached in memory on first
load. Subsequent requests skip chunking entirely and only do fast set-based
scoring — making FAQ retrieval ~10-50x faster for large PDFs.

Cache is invalidated when:
- A document is added, updated, toggled, or deleted (via invalidate_faq_cache)
- The server restarts
"""

from typing import List, Tuple, Dict
from sqlalchemy.orm import Session
import models
import re
import time

# ── In-memory chunk cache ─────────────────────────────────────────────────────
_chunk_cache: Dict[int, dict] = {}
_cache_dirty = True


def invalidate_faq_cache():
    """Call this from main.py whenever a FAQDocument is added/updated/deleted."""
    global _cache_dirty
    _cache_dirty = True
    print("[faq_cache] Cache invalidated — will reload on next request.")


# ── Stop words ────────────────────────────────────────────────────────────────
_STOP_WORDS = {
    'the', 'is', 'are', 'was', 'were', 'a', 'an', 'and', 'or', 'of',
    'to', 'in', 'for', 'on', 'at', 'by', 'with', 'this', 'that', 'it',
    'be', 'as', 'from', 'but', 'not', 'what', 'how', 'who', 'where',
    'when', 'which', 'do', 'does', 'did', 'can', 'could', 'will', 'would',
    'should', 'have', 'has', 'had', 'may', 'might', 'i', 'you', 'we',
    'they', 'he', 'she', 'me', 'him', 'her', 'us', 'them', 'my', 'your',
    'please', 'tell', 'give', 'show', 'about', 'get', 'ng', 'sa', 'ang',
    'na', 'mga', 'po', 'ako', 'mo', 'ka', 'ko', 'nag', 'ano', 'sino',
}


# ── Text helpers ──────────────────────────────────────────────────────────────

def _content_words(text: str) -> set:
    """Extract meaningful words, removing stop words and short tokens."""
    words = re.sub(r'[^\w\s]', '', text.lower()).split()
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


def _score_chunk(query_words: set, chunk_words: set) -> float:
    """Score pre-computed chunk word set against query words."""
    if not query_words or not chunk_words:
        return 0.0
    matches = query_words & chunk_words
    if not matches:
        return 0.0
    base    = len(matches) / len(query_words)
    density = len(matches) / max(len(chunk_words), 1)
    return base * 0.7 + density * 0.3


def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """Split text into overlapping sentence-aware chunks."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            break_search = text[max(end - 200, start):end]
            for sep in ['\n\n', '.\n', '. ', '\n']:
                idx = break_search.rfind(sep)
                if idx != -1:
                    end = max(end - 200, start) + idx + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap
        if start <= 0 or start >= text_len:
            break

    return chunks


# ── Cache loader ──────────────────────────────────────────────────────────────

def _load_cache(db: Session):
    """
    Load all active FAQ docs from DB, chunk them, pre-compute word sets.
    Called once on first request, then only after invalidation.
    """
    global _chunk_cache, _cache_dirty

    t0 = time.time()
    try:
        docs = (
            db.query(models.FAQDocument)
            .filter(models.FAQDocument.is_active == True)
            .all()
        )
    except Exception as exc:
        print(f"[faq_cache] DB error while loading: {exc}")
        return

    new_cache = {}
    total_chunks = 0

    for doc in docs:
        text = doc.extracted_text or ""
        if not text.strip():
            continue

        raw_chunks = _chunk_text(text, chunk_size=1500, overlap=200)
        processed = [
            {"text": chunk, "words": _content_words(chunk)}
            for chunk in raw_chunks
        ]
        new_cache[doc.id] = {
            "title":     doc.title,
            "chunks":    processed,
            "loaded_at": time.time(),
        }
        total_chunks += len(processed)
        print(f"[faq_cache] Cached '{doc.title}': {len(processed)} chunks")

    _chunk_cache = new_cache
    _cache_dirty = False
    elapsed = round(time.time() - t0, 2)
    print(f"[faq_cache] Ready — {len(new_cache)} docs, {total_chunks} chunks in {elapsed}s")


# ── Public API ────────────────────────────────────────────────────────────────

def retrieve_faq_context(
    db: Session,
    query: str,
    top_k: int = 5,
    min_score: float = 0.10,
) -> str:
    """
    Search cached FAQ chunks for the query and return top-k as context string.
    First call loads and caches all docs (one-time cost).
    All subsequent calls use in-memory cache — very fast.
    """
    global _cache_dirty

    if _cache_dirty:
        _load_cache(db)

    if not _chunk_cache:
        print("[faq_retriever] No active FAQ documents in cache.")
        return ""

    query_words = _content_words(query)
    if not query_words:
        return ""

    scored: List[Tuple[float, str]] = []

    for doc_id, doc_data in _chunk_cache.items():
        title  = doc_data["title"]
        chunks = doc_data["chunks"]
        for chunk in chunks:
            score = _score_chunk(query_words, chunk["words"])
            if score >= min_score:
                scored.append((score, f"[{title}]\n{chunk['text']}"))

    if not scored:
        print(f"[faq_retriever] No matches found for: {query!r}")
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [text for _, text in scored[:top_k]]
    print(f"[faq_retriever] Returning {len(top_chunks)} chunks (best score: {scored[0][0]:.3f})")
    return "\n\n---\n\n".join(top_chunks)