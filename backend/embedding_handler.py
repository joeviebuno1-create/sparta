"""
EMBEDDING HANDLER — Gemini API
================================
Replaces sentence-transformers + torch entirely.
Uses google-genai's embed_content API, which runs in the cloud
so zero RAM is used for a local model.

Model: gemini-embedding-exp-03-07 (3072-dim, free tier friendly)
"""

import os
import numpy as np
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

_client = None
EMBEDDING_ENABLED = False

try:
    from google import genai
    _key = os.getenv("GEMINI_API_KEY", "")
    if _key:
        _client = genai.Client(api_key=_key)
        EMBEDDING_ENABLED = True
        print("✓ Gemini embedding handler loaded.")
    else:
        print("[embedding] No GEMINI_API_KEY — embeddings disabled, falling back to keyword matching.")
except ImportError as e:
    print(f"[embedding] google-genai not installed ({e}) — embeddings disabled.")
except Exception as e:
    print(f"[embedding] Could not initialize ({e}) — embeddings disabled.")


_EMBED_MODEL = "gemini-embedding-exp-03-07"

# ── In-memory cache: text → numpy array ──────────────────────────────────────
# Avoids redundant API calls for the same string
_embed_cache: dict[str, np.ndarray] = {}


def embed_text(text: str) -> Optional[np.ndarray]:
    """
    Embed a single string. Returns a numpy float32 array or None on failure.
    Results are cached in memory to avoid duplicate API calls.
    """
    if not EMBEDDING_ENABLED or not text.strip():
        return None

    key = text.strip()[:500]  # cap cache key length
    if key in _embed_cache:
        return _embed_cache[key]

    try:
        result = _client.models.embed_content(
            model=_EMBED_MODEL,
            contents=key,
        )
        vec = np.array(result.embeddings[0].values, dtype=np.float32)
        _embed_cache[key] = vec
        return vec
    except Exception as e:
        print(f"[embedding] embed_text failed: {e}")
        return None


def embed_batch(texts: List[str]) -> List[Optional[np.ndarray]]:
    """
    Embed a list of strings. Skips cache hits and only calls the API
    for new texts, then merges results back in order.
    """
    if not EMBEDDING_ENABLED:
        return [None] * len(texts)

    results: List[Optional[np.ndarray]] = [None] * len(texts)
    to_fetch: List[tuple[int, str]] = []

    for i, text in enumerate(texts):
        key = text.strip()[:500]
        if key in _embed_cache:
            results[i] = _embed_cache[key]
        else:
            to_fetch.append((i, key))

    # Fetch uncached texts one at a time (API doesn't have native batch endpoint)
    for i, key in to_fetch:
        results[i] = embed_text(key)

    return results


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Fast cosine similarity between two numpy vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def cosine_sim_matrix(query_vec: np.ndarray, doc_vecs: List[np.ndarray]) -> List[float]:
    """Compute cosine similarity between one query and many docs."""
    if not doc_vecs:
        return []
    doc_matrix = np.stack(doc_vecs)  # (N, D)
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    doc_norms = doc_matrix / (np.linalg.norm(doc_matrix, axis=1, keepdims=True) + 1e-9)
    return (doc_norms @ query_norm).tolist()


def clear_embed_cache():
    """Call this when DB records are updated so stale embeddings are removed."""
    global _embed_cache
    _embed_cache = {}
    print("[embedding] Cache cleared.")