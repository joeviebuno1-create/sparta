"""
EMBEDDING HANDLER — Gemini API
================================
Replaces sentence-transformers + torch entirely.
Uses google-genai's embed_content API (zero RAM for local model).

NOTE: contents must be passed as a LIST per SDK v1.x requirement.
Model: gemini-embedding-001 (stable, available on free tier v1beta)
"""

import os
import numpy as np
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

_client = None
EMBEDDING_ENABLED = False
_EMBED_MODEL = None

# Correct order for google-genai SDK v1.x on v1beta endpoint
_MODEL_CANDIDATES = [
    "gemini-embedding-001",       # newest stable, free tier
    "text-embedding-004",         # older stable
    "embedding-001",              # legacy fallback
]


def _detect_working_model(client) -> Optional[str]:
    """Try each candidate. contents MUST be a list for this SDK version."""
    for model in _MODEL_CANDIDATES:
        try:
            result = client.models.embed_content(
                model=model,
                contents=["test"],   # list, not bare string
            )
            if result.embeddings and result.embeddings[0].values:
                print(f"[embedding] Using model: {model}")
                return model
        except Exception as e:
            print(f"[embedding] Model '{model}' not available: {e}")
    return None


try:
    from google import genai
    _key = os.getenv("GEMINI_API_KEY", "")
    if _key:
        _client = genai.Client(api_key=_key)
        _EMBED_MODEL = _detect_working_model(_client)
        if _EMBED_MODEL:
            EMBEDDING_ENABLED = True
            print("✓ Gemini embedding handler loaded.")
        else:
            print("[embedding] No working embedding model — using keyword matching only.")
    else:
        print("[embedding] No GEMINI_API_KEY — using keyword matching only.")
except ImportError as e:
    print(f"[embedding] google-genai not installed ({e}) — using keyword matching only.")
except Exception as e:
    print(f"[embedding] Could not initialize ({e}) — using keyword matching only.")


# In-memory cache: text -> numpy array
_embed_cache: dict = {}


def embed_text(text: str) -> Optional[np.ndarray]:
    """Embed a single string. Cached in memory to avoid duplicate API calls."""
    if not EMBEDDING_ENABLED or not _EMBED_MODEL or not text.strip():
        return None

    key = text.strip()[:500]
    if key in _embed_cache:
        return _embed_cache[key]

    try:
        # contents must be a list
        result = _client.models.embed_content(
            model=_EMBED_MODEL,
            contents=[key],
        )
        vec = np.array(result.embeddings[0].values, dtype=np.float32)
        _embed_cache[key] = vec
        return vec
    except Exception as e:
        print(f"[embedding] embed_text failed: {e}")
        return None


def embed_batch(texts: List[str]) -> List[Optional[np.ndarray]]:
    """Embed a list of strings, using cache for already-seen texts."""
    if not EMBEDDING_ENABLED:
        return [None] * len(texts)

    results: List[Optional[np.ndarray]] = [None] * len(texts)
    to_fetch = []

    for i, text in enumerate(texts):
        key = text.strip()[:500]
        if key in _embed_cache:
            results[i] = _embed_cache[key]
        else:
            to_fetch.append((i, key))

    for i, key in to_fetch:
        results[i] = embed_text(key)

    return results


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def cosine_sim_matrix(query_vec: np.ndarray, doc_vecs: List[np.ndarray]) -> List[float]:
    if not doc_vecs:
        return []
    doc_matrix = np.stack(doc_vecs)
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    doc_norms = doc_matrix / (np.linalg.norm(doc_matrix, axis=1, keepdims=True) + 1e-9)
    return (doc_norms @ query_norm).tolist()


def clear_embed_cache():
    global _embed_cache
    _embed_cache = {}
    print("[embedding] Cache cleared.")