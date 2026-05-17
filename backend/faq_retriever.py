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


_HEADER_NOISE = re.compile(
    r'^(frequently\s+asked\s+questions?|faq|batangas\s+state\s+university'
    r'|don\s+claro|the\s+national\s+engineering|page\s+\d+|\d+\s*of\s*\d+)',
    re.IGNORECASE
)

def _clean_chunk(text: str) -> str:
    """Remove PDF header/footer noise lines from a chunk."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip short header-like lines (page titles, doc titles)
        if len(stripped) < 60 and _HEADER_NOISE.match(stripped):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned).strip()


def _is_qa_chunk(text: str) -> bool:
    """Return True if chunk contains a Q&A pattern — higher quality for retrieval."""
    return bool(re.search(r'^\s*Q\s*:', text, re.MULTILINE) or
                re.search(r'^\s*Q\s*\d*[:\.]', text, re.MULTILINE))


def _score_chunk(query_words: set, chunk_words: set, chunk_text: str = "", original_query: str = "") -> float:
    """Score pre-computed chunk word set against query words."""
    if not query_words or not chunk_words:
        return 0.0
    matches = query_words & chunk_words
    if not matches:
        return 0.0
    base    = len(matches) / len(query_words)
    density = len(matches) / max(len(chunk_words), 1)
    score   = base * 0.7 + density * 0.3
    # Boost Q&A formatted chunks — they are more likely to be accurate answers
    if chunk_text and _is_qa_chunk(chunk_text):
        score *= 1.3
    # FIX: Exact phrase match bonus — if the query phrase appears verbatim in the
    # chunk, it's a very strong signal. Boost significantly.
    if original_query and len(original_query) >= 6:
        if original_query.lower() in chunk_text.lower():
            score *= 1.8
        else:
            # Partial phrase: check 3+ word sub-phrases
            words = original_query.lower().split()
            for i in range(len(words) - 2):
                phrase = ' '.join(words[i:i+3])
                if phrase in chunk_text.lower():
                    score *= 1.25
                    break
    return score


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """Split text into overlapping sentence-aware chunks. Memory-efficient."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    text_len = len(text)
    chunks = []
    start = 0

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            search_start = max(end - 150, start)
            break_search = text[search_start:end]
            for sep in ['\n\n', '.\n', '. ', '\n']:
                idx = break_search.rfind(sep)
                if idx != -1:
                    end = search_start + idx + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        next_start = end - overlap
        if next_start <= start:
            next_start = end  # prevent infinite loop
        start = next_start

        if start >= text_len:
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
    # Release old cache BEFORE building new one — prevents 2× RAM spike
    _chunk_cache = {}
    import gc; gc.collect()
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

        # Cap at 50KB per document — enough for a full FAQ PDF
        # Larger PDFs should be split into multiple FAQ documents in admin
        MAX_TEXT = 50_000
        if len(text) > MAX_TEXT:
            print(f"[faq_cache] '{doc.title}' truncated {len(text)} -> {MAX_TEXT} chars")
            text = text[:MAX_TEXT]

        raw_chunks = _chunk_text(text, chunk_size=800, overlap=100)
        processed = []
        for chunk in raw_chunks:
            cleaned = _clean_chunk(chunk)
            if len(cleaned) < 30:  # skip near-empty chunks after cleaning
                continue
            processed.append({
                "text":  cleaned,
                "words": _content_words(cleaned),
                "is_qa": _is_qa_chunk(cleaned),
            })
        del raw_chunks

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
    top_k: int = 3,
    min_score: float = 0.22,   # FIX: raised from 0.15 — reduces low-quality chunk returns
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
        chunks = doc_data["chunks"]
        for chunk in chunks:
            # FIX: Pass original query for exact phrase match bonus
            score = _score_chunk(query_words, chunk["words"], chunk["text"], query)
            if score >= min_score:
                scored.append((score, chunk["text"]))

    if not scored:
        print(f"[faq_retriever] No matches found for: {query!r}")
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [text for _, text in scored[:top_k]]
    print(f"[faq_retriever] Returning {len(top_chunks)} chunks (best score: {scored[0][0]:.3f})")

    # Join chunks, remove duplicate lines across chunks
    seen_lines = set()
    final_lines = []
    for chunk in top_chunks:
        for line in chunk.split('\n'):
            stripped = line.strip()
            if stripped and stripped not in seen_lines:
                seen_lines.add(stripped)
                final_lines.append(line)
        final_lines.append('')  # blank line between chunks

    result = '\n'.join(final_lines).strip()
    if len(result) > 6_000:
        result = result[:6_000] + "\n[...truncated...]"
    return result