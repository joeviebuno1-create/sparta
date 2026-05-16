"""
EMBEDDING HANDLER — Sentence Transformers (CPU-only)
=====================================================
Replaces Gemini embedding API entirely.
Uses all-MiniLM-L6-v2 — lightweight, fast on CPU, zero API cost.

Install (requirements.txt):
    --extra-index-url https://download.pytorch.org/whl/cpu
    torch==2.2.2+cpu
    sentence-transformers==2.7.0
"""

import numpy as np
from typing import List, Optional
from collections import OrderedDict

EMBEDDING_ENABLED = False
_model = None

try:
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    EMBEDDING_ENABLED = True
    print("✓ Sentence-transformers embedding handler loaded (all-MiniLM-L6-v2).")
except ImportError as e:
    print(f"[embedding] sentence-transformers not installed ({e}) — using keyword matching only.")
except Exception as e:
    print(f"[embedding] Could not load model ({e}) — using keyword matching only.")


# ── LRU embedding cache — capped at 300 entries ───────────────────────────────
class _EmbedLRU:
    def __init__(self, n=300):
        self._c = OrderedDict()
        self._n = n

    def get(self, k):
        if k not in self._c:
            return None
        self._c.move_to_end(k)
        return self._c[k]

    def set(self, k, v):
        if k in self._c:
            self._c.move_to_end(k)
        elif len(self._c) >= self._n:
            self._c.popitem(last=False)
        self._c[k] = v

    def clear(self):
        self._c.clear()

    def __len__(self):
        return len(self._c)

    def __contains__(self, k):
        return k in self._c


_embed_cache = _EmbedLRU(300)


def embed_text(text: str) -> Optional[np.ndarray]:
    """Embed a single string. Cached in memory to avoid duplicate calls."""
    if not EMBEDDING_ENABLED or not _model or not text.strip():
        return None

    key = text.strip()[:500]
    cached = _embed_cache.get(key)
    if cached is not None:
        return cached

    try:
        vec = _model.encode(key, convert_to_numpy=True, normalize_embeddings=True)
        vec = vec.astype(np.float32)
        _embed_cache.set(key, vec)
        return vec
    except Exception as e:
        print(f"[embedding] embed_text failed: {e}")
        return None


def embed_batch(texts: List[str]) -> List[Optional[np.ndarray]]:
    """Embed a list of strings, using cache for already-seen texts."""
    if not EMBEDDING_ENABLED or not _model:
        return [None] * len(texts)

    results: List[Optional[np.ndarray]] = [None] * len(texts)
    to_fetch_indices = []
    to_fetch_texts = []

    for i, text in enumerate(texts):
        key = text.strip()[:500]
        cached = _embed_cache.get(key)
        if cached is not None:
            results[i] = cached
        else:
            to_fetch_indices.append(i)
            to_fetch_texts.append(key)

    if to_fetch_texts:
        try:
            vecs = _model.encode(
                to_fetch_texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                batch_size=32,
            )
            for i, (idx, key) in enumerate(zip(to_fetch_indices, to_fetch_texts)):
                vec = vecs[i].astype(np.float32)
                _embed_cache.set(key, vec)
                results[idx] = vec
        except Exception as e:
            print(f"[embedding] embed_batch failed: {e}")

    return results


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Since we use normalize_embeddings=True, dot product == cosine similarity."""
    return float(np.dot(a, b))


def cosine_sim_matrix(query_vec: np.ndarray, doc_vecs: List[np.ndarray]) -> List[float]:
    if not doc_vecs:
        return []
    doc_matrix = np.stack(doc_vecs)
    # Vectors are already normalized — dot product is cosine similarity
    return (doc_matrix @ query_vec).tolist()


def clear_embed_cache():
    _embed_cache.clear()
    print("[embedding] Cache cleared.")