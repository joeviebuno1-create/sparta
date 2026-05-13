"""
ENHANCED DATABASE-RAG CHATBOT FOR SPARTHA - MAXIMUM ACCURACY
==============================================================
Major improvements:
1. Multi-stage intent detection with weighted scoring
2. Query preprocessing and normalization
3. Fuzzy matching for better name/location recognition
4. Semantic + keyword hybrid retrieval
5. Context-aware response generation with templates
6. Confidence calibration and uncertainty handling
7. Better entity extraction with NLP techniques
8. Response quality validation
"""

import re
from typing import List, Dict, Tuple, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
import models
from datetime import datetime
import json
import numpy as np
from difflib import SequenceMatcher

# Sentence-transformers embedding (CPU-only, no Gemini API needed)
from embedding_handler import (
    embed_text, embed_batch, cosine_sim_matrix,
    EMBEDDING_ENABLED, clear_embed_cache
)

# ── Pure RAG mode — Gemini disabled to prevent Railway OOM ───────────────────
# gemini_handler stubs return None; rag_chatbot falls back to template responses
from gemini_handler import generate_with_gemini, answer_from_faq_docs, _context_blocks_to_text, GEMINI_ENABLED
from faq_retriever import retrieve_faq_context


# ─── College / department constants (module-level so always available) ─────────

COLLEGE_MAP = {
    'CET':  ['CET', 'engineering technology', 'college of engineering technology'],
    'CICS': ['CICS', 'informatics', 'computing sciences', 'college of informatics'],
    'CAS':  ['CAS', 'arts and sciences', 'college of arts and sciences'],
    'CABE': ['CABE', 'accountancy', 'business', 'economics',
             'college of accountancy business and economics'],
    'CTE':  ['CTE', 'teacher education', 'college of teacher education'],
}

# Maps any mention → canonical code
COLLEGE_ALIASES = {
    # CET
    'cet': 'CET',
    'engineering technology': 'CET',
    'engineering': 'CET',
    'college of engineering technology': 'CET',
    # CICS
    'cics': 'CICS',
    'informatics': 'CICS',
    'computing sciences': 'CICS',
    'computer science': 'CICS',
    'computing': 'CICS',
    'informatics and computing sciences': 'CICS',
    'informatics and computing': 'CICS',
    'college of informatics and computing sciences': 'CICS',
    'ict': 'CICS',
    'information and communications technology': 'CICS',
    'information technology': 'CICS',
    'it department': 'CICS',
    # CAS
    'cas': 'CAS',
    'arts and sciences': 'CAS',
    'arts': 'CAS',
    'sciences': 'CAS',
    'college of arts and sciences': 'CAS',
    # CABE
    'cabe': 'CABE',
    'accountancy': 'CABE',
    'business': 'CABE',
    'economics': 'CABE',
    'accountancy business and economics': 'CABE',
    'college of accountancy business and economics': 'CABE',
    # CTE
    'cte': 'CTE',
    'teacher education': 'CTE',
    'education': 'CTE',
    'college of teacher education': 'CTE',
}


def resolve_college(text: str) -> Optional[str]:
    """Resolve any college text to its canonical 3-4 letter code."""
    tl = text.lower().strip()
    if tl in COLLEGE_ALIASES:
        return COLLEGE_ALIASES[tl]
    # Try longest-match partial lookup
    best = None
    best_len = 0
    for alias, code in COLLEGE_ALIASES.items():
        if alias in tl and len(alias) > best_len:
            best = code
            best_len = len(alias)
    return best


def extract_college_from_query(original_query: str) -> Tuple[List[str], List[str]]:
    """
    Extract college codes and search keywords from the ORIGINAL (un-normalized) query.
    Returns (dept_codes, dept_keywords) e.g. (['CET'], ['CET', 'engineering technology', ...])

    Works for:
      - "who is the dean of CET"
      - "who is the dean of cet"
      - "sino ang dean ng CET"
      - "CET dean"
      - "dean of engineering technology"
      - "who is the dean of College of Engineering Technology"
      - "dean of CICS"
      - "CABE dean"
    """
    q = original_query  # preserve original case for abbreviation matching
    ql = original_query.lower().strip()

    codes = []
    keywords = []

    def add_code(code: str):
        if code and code not in codes:
            codes.append(code)
            for kw in COLLEGE_MAP.get(code, []):
                if kw not in keywords:
                    keywords.append(kw)

    # ── Priority 1: exact abbreviation (case-insensitive word boundary) ───────
    m = re.search(r'\b(CET|CICS|CAS|CABE|CTE|ICT)\b', q, re.IGNORECASE)
    if m:
        raw = m.group(1).upper()
        if raw == 'ICT':
            # "ICT" alone could mean the CICS college OR an ICT Services/unit position.
            # If the query contains position/service context words, treat it as a
            # position keyword (NOT a college filter) so the dept filter doesn't
            # wrongly exclude people like the Head of ICT Services.
            _ict_position_ctx = ['services', 'planning', 'development', 'unit',
                                  'office', 'division', 'center', 'head of ict',
                                  'director of ict', 'chief of ict',
                                  'head', 'director', 'chief']
            _is_position_ctx = any(w in ql for w in _ict_position_ctx)
            if not _is_position_ctx:
                add_code('CICS')
            # else: skip college mapping — let the role filter find the person
        else:
            add_code(raw)

    # ── Priority 2: Filipino "ng <abbrev>" e.g. "dean ng CET" ─────────────────
    if not codes:
        m = re.search(r'\bng\s+(CET|CICS|CAS|CABE|CTE|ICT)\b', q, re.IGNORECASE)
        if m:
            raw = m.group(1).upper()
            if raw == 'ICT':
                _ict_position_ctx = ['services', 'planning', 'development', 'unit',
                                      'office', 'division', 'center', 'head', 'director', 'chief']
                if not any(w in ql for w in _ict_position_ctx):
                    add_code('CICS')
            else:
                add_code(raw)

    # ── Priority 3: "of <abbrev>" e.g. "dean of CET" ──────────────────────────
    if not codes:
        m = re.search(r'\bof\s+(CET|CICS|CAS|CABE|CTE|ICT)\b', q, re.IGNORECASE)
        if m:
            raw = m.group(1).upper()
            if raw == 'ICT':
                _ict_position_ctx = ['services', 'planning', 'development', 'unit',
                                      'office', 'division', 'center', 'head', 'director', 'chief']
                if not any(w in ql for w in _ict_position_ctx):
                    add_code('CICS')
            else:
                add_code(raw)

    # ── Priority 4: Full college name patterns ─────────────────────────────────
    if not codes:
        full_patterns = [
            r'college of (engineering technology)',
            r'college of (informatics and computing sciences)',
            r'college of (arts and sciences)',
            r'college of (accountancy[,\s]+business[,\s]+and\s+economics)',
            r'college of (teacher education)',
            r'\bof (engineering technology)\b',
            r'\bof (informatics and computing sciences)\b',
            r'\bof (arts and sciences)\b',
            r'\bof (accountancy[,\s]+business[,\s]+and\s+economics)\b',
            r'\bof (teacher education)\b',
            r'\bof (informatics)\b',
            r'\bof (computing sciences)\b',
            r'\bof (accountancy)\b',
            r'\bof (business)\b',
            r'\bof (economics)\b',
            r'\bof (arts)\b',
            r'\bof (sciences)\b',
            r'\bof (engineering)\b',
        ]
        for pat in full_patterns:
            m = re.search(pat, ql)
            if m:
                code = resolve_college(m.group(1))
                if code:
                    add_code(code)
                break

    # ── Priority 5: Standalone keywords (last resort, longest match first) ─────
    if not codes:
        keyword_checks = [
            # Multi-word first (more specific)
            ('engineering technology',              'CET'),
            ('informatics and computing sciences',  'CICS'),
            ('arts and sciences',                   'CAS'),
            ('teacher education',                   'CTE'),
            ('computing sciences',                  'CICS'),
            ('informatics and computing',           'CICS'),
            # Single-word
            ('informatics',                         'CICS'),
            ('computing',                           'CICS'),
            ('accountancy',                         'CABE'),
            ('economics',                           'CABE'),
            ('engineering',                         'CET'),
        ]
        for kw, code in keyword_checks:
            if kw in ql:
                add_code(code)
                break

    return codes, keywords



# ─── Language Detection ────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """Returns 'tl' for Filipino/Tagalog, 'en' for English."""
    markers = [
        'sino', 'saan', 'ano', 'paano', 'kailan', 'bakit',
        'ang', 'ng', 'sa', 'na', 'ay', 'mga', 'po', 'ho', 'ba',
        'yung', 'doon', 'dito', 'pwede', 'puwede', 'gusto', 'kailangan',
        'gusali', 'silid', 'aklatan', 'opisina', 'dekano',
        'kasaysayan', 'anunsyo', 'organisasyon',
    ]
    t = text.lower()
    count = sum(1 for w in t.split() if w in markers)
    strong = ['sino ang', 'saan ang', 'ano ang', 'sino na', ' po ', ' ba ']
    return 'tl' if (count >= 2 or any(m in t for m in strong)) else 'en'

class EnhancedDatabaseRAG:
    """
    Enhanced Database Retrieval Augmented Generation System
    Optimized for maximum accuracy and natural responses
    """

    def __init__(self, embedding_model=None):
        # embedding_model param kept for API compatibility but no longer used
        self.use_embeddings = EMBEDDING_ENABLED
        self.context_window_size = 5

        # ── Pre-computed doc embedding cache ──────────────────────────────────
        # key: (table, doc_id) → np.ndarray
        # Populated once at startup via warm_up_cache(), never re-computed per query
        self._embedding_cache: Dict[tuple, Any] = {}
        self._cache_ready = False

        if self.use_embeddings:
            print("✓ Sentence-transformers semantic search enabled.")

        self.intent_config = {
            'authority_query': {
                'keywords': ['who is', 'dean', 'head', 'director', 'president', 'contact',
                             'email', 'phone', 'authority', 'faculty', 'staff',
                             'chairman', 'administrator', 'vp', 'vice president', 'coordinator',
                             'chief', 'officer', 'manager', 'supervisor', 'professor', 'instructor',
                             'chairperson', 'provost', 'chancellor', 'rector', 'registrar',
                             'official', 'officials', 'personnel', 'all officials',
                             'university officials', 'all university officials',
                             'sino', 'sino ang', 'mga opisyal', 'lahat ng opisyal'],
                'question_words': ['who', 'whose', 'whom', 'sino'],
                'retrieval_strategy': 'exact_match_preferred',
                'max_results': 20,
                'similarity_threshold': 0.25
            },
            'location_query': {
                'keywords': ['where', 'location', 'room', 'building', 'floor', 'find',
                             'directions', 'navigate', 'how to get', 'map', 'situated',
                             'located', 'place', 'area', 'facility', 'venue', 'hall',
                             'laboratory', 'lab', 'classroom', 'auditorium', 'gym', 'saan',
                             'library', 'lib', 'lrc', 'learning resource center',
                             'canteen', 'cafeteria', 'clinic', 'chapel', 'registrar',
                             'cashier', 'gymnasium', 'office', 'campus',
                             "dean's office", 'deans office', 'dean office',
                             'vmb', 'gzb', 'ob room', 'valerio malabanan',
                             'gonzales', 'teresa solis', 'tsb'],
                'question_words': ['where', 'which building', 'what floor', 'saan'],
                'retrieval_strategy': 'spatial_aware',
                'max_results': 5,
                'similarity_threshold': 0.25
            },
            'history_query': {
                'keywords': ['history', 'when', 'founded', 'established', 'year', 'past',
                             'historical', 'timeline', 'milestone', 'origin', 'began',
                             'started', 'created', 'inception', 'background', 'heritage',
                             'legacy', 'tradition', 'evolution',
                             # Tagalog / Filipino
                             'kasaysayan', 'naitatag', 'itinatag', 'nagsimula', 'taon',
                             'nagtatag', 'pagkakatatag', 'nakaraan', 'milestones',
                             'major milestone', 'major milestones', 'achievements',
                             'republic act', 'batas'],
                'question_words': ['when', 'what year', 'how long', 'ano ang', 'kailan'],
                'retrieval_strategy': 'temporal_ordered',
                'max_results': 5,
                'similarity_threshold': 0.28
            },
            'announcement_query': {
                'keywords': ['announcement', 'news', 'latest', 'update', 'event',
                             'happening', 'schedule', "what's new", 'recent', 'upcoming',
                             'today', 'tomorrow', 'this week', 'current', 'ongoing',
                             'notice', 'bulletin', 'memo', 'circular'],
                'question_words': ['what', 'when', "what's"],
                'retrieval_strategy': 'recency_weighted',
                'max_results': 5,
                'similarity_threshold': 0.25
            },
            'general_info': {
                'keywords': ['vision', 'mission', 'core values', 'tagline', 'motto',
                             'tuition', 'free tuition', 'scholarship', 'fees', 'payment',
                             'enrollment', 'admission', 'apply', 'application', 'requirement',
                             'program', 'course', 'degree', 'curriculum', 'subject',
                             'dormitory', 'dorm', 'housing', 'accommodation',
                             'contact', 'website', 'email', 'social media', 'facebook',
                             'office hours', 'schedule', 'calendar',
                             'about bsu', 'about batangas state', 'what is bsu',
                             'patriotism', 'service', 'integrity', 'resilience', 'faith',
                             'bat', 'admission test', 'entrance exam'],
                'question_words': ['what', 'how', 'when', 'is', 'are', 'does'],
                'retrieval_strategy': 'faq_search',
                'max_results': 3,
                'similarity_threshold': 0.15
            },
            'organization_query': {
                'keywords': ['organization', 'org chart', 'structure', 'department',
                             'members', 'team', 'student org', 'club', 'list of org',
                             'show org', 'all org', 'organizations', 'student organizations',
                             'society', 'association', 'council', 'committee', 'group',
                             'student groups', 'clubs', 'orgs', 'student clubs'],
                'question_words': ['what', 'which', 'show me', 'list', 'show'],
                'retrieval_strategy': 'hierarchical',
                'max_results': 50,  # Increased to show all organizations
                'similarity_threshold': 0.15  # Lower threshold to catch more queries
            },
            'navigation_query': {
                'keywords': ['how to get', 'route', 'path', 'directions from', 'navigate to',
                             'walk to', 'go to', 'reach', 'access', 'way to'],
                'question_words': ['how', 'how do i', "what's the way"],
                'retrieval_strategy': 'pathfinding',
                'max_results': 1,
                'similarity_threshold': 0.30
            }
        }

        self.query_normalizations = {
            r'\b(whats|what\'s|wats|wat)\b': 'what is',
            r'\b(whos|who\'s|hus|hu)\b': 'who is',
            r'\b(hows|how\'s)\b': 'how is',
            r'\b(wheres|where\'s|wer|whr)\b': 'where is',
            r'\btell me about\b': 'what is',
            r'\bshow me\b': 'what are',
            r'\bgive me\b': 'what are',
            r'\bcan you\b': '',
            r'\bplease\b': '',
            r'\bpls\b': '',
            r'\bplez\b': '',
            r'\bi want to know\b': 'what is',
            r'\bi would like to know\b': 'what is',
            r'\bdo you know\b': 'what is',
            # Common typos for where
            r'\bwhere iz\b': 'where is',
            r'\bwhere are the\b': 'where is the',
            r'\bwer is\b': 'where is',
            r'\bwhere da\b': 'where is',
            # Common typos for library
            r'\blibary\b': 'library',
            r'\blibrary\b': 'library',
            r'\blibrery\b': 'library',
            r'\blibrey\b': 'library',
            r'\blibray\b': 'library',
            r'\blibrry\b': 'library',
            # Common typos for organization
            r'\borganizaton\b': 'organization',
            r'\borganisation\b': 'organization',
            r'\borganzation\b': 'organization',
            r'\borg\b': 'organization',
            # Common typos for announcement
            r'\banouncement\b': 'announcement',
            r'\bannoucement\b': 'announcement',
            # Space handling — collapse multiple spaces
            r'\s+': ' ',
            # Tagalog / Filipino
            r'\bsino ang\b': 'who is',
            r'\bsino na ang\b': 'who is',
            r'\bsino si\b': 'who is',
            r'\bsaan ang\b': 'where is',
            r'\bano ang\b': 'what is',
            r'\bipaalam\b': 'tell me about',
            r'\bkung sino\b': 'who is',
            r'\bkung saan\b': 'where is',
            # History-specific Tagalog
            r'\bkasaysayan\b': 'history',
            r'\bnaitatag\b': 'founded',
            r'\bitinatag\b': 'founded',
            r'\bnagtatag\b': 'established',
            r'\bnagsimula\b': 'started',
            r'\bpagkakatatag\b': 'founding',
            r'\bnakaraan\b': 'history',
            r'\bmajor milestone\b': 'milestone',
            r'\bmajor milestones\b': 'milestones',
            r'\bkailan\b': 'when',
            r'\bng bsu\b': 'of bsu',
            # Honorific normalizations
            r"\bma'am\b": 'maam',
            r'\bma am\b': 'maam',
        }

    def warm_up_cache(self, db: Session) -> None:
        """
        Lazy embedding — embeddings are computed on first query, not at startup.
        This avoids making 100+ API calls during boot which blocks the server.
        """
        # Skip pre-computation — embeddings are cached on first use per query
        self._cache_ready = True
        print("[cache] Lazy embedding enabled — will embed on first query.")

    def invalidate_cache(self, table_name: str, doc_id: int = None) -> None:
        """
        Call this after any admin add/edit/delete so the cache stays fresh.
        Pass doc_id to remove one entry, or omit to clear the whole table.
        """
        if doc_id is not None:
            self._embedding_cache.pop((table_name, doc_id), None)
        else:
            keys = [k for k in self._embedding_cache if k[0] == table_name]
            for k in keys:
                del self._embedding_cache[k]
        # Also clear the Gemini embedding text cache for affected docs
        clear_embed_cache()

    def normalize_query(self, query: str) -> str:
        query = query.strip()
        query_lower = query.lower()
        for pattern, replacement in self.query_normalizations.items():
            query_lower = re.sub(pattern, replacement, query_lower)
        query_lower = ' '.join(query_lower.split())
        return query_lower

    def fuzzy_match_score(self, str1: str, str2: str) -> float:
        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()

    def expand_query(self, query: str) -> List[str]:
        query_variations = [query]
        query_lower = query.lower()
        expansions = {
            'dean': ['dean', 'college dean', 'head of college', 'college head'],
            'head': ['head', 'director', 'chief', 'leader', 'head of'],
            'contact': ['contact', 'email', 'phone', 'reach', 'get in touch'],
            'where': ['where', 'location', 'situated', 'find', 'located'],
            'room': ['room', 'classroom', 'office', 'space', 'hall'],
            'latest': ['latest', 'recent', 'new', 'current', 'upcoming'],
            'org': ['organization', 'org', 'club', 'group', 'society'],
            'list': ['list', 'show', 'display', 'enumerate', 'all'],
            'building': ['building', 'hall', 'structure', 'facility'],
            'library': ['library', 'lib', 'learning resource center', 'lrc'],
        }
        for term, synonyms in expansions.items():
            if term in query_lower:
                for synonym in synonyms:
                    if synonym != term:
                        expanded = query_lower.replace(term, synonym)
                        if expanded != query_lower:
                            query_variations.append(expanded)
        return list(set(query_variations))[:4]

    def detect_intent(self, query: str) -> Tuple[str, float]:
        query_normalized = self.normalize_query(query)
        query_lower = query_normalized.lower()
        intent_scores = {}

        for intent_name, config in self.intent_config.items():
            score = 0
            keyword_matches = 0

            for qword in config.get('question_words', []):
                if query_lower.startswith(qword):
                    score += 20
                    break

            words = query_lower.split()
            for keyword in config['keywords']:
                if keyword in query_lower:
                    if query_lower.startswith(keyword):
                        weight = 15
                    elif keyword in words[:3]:
                        weight = 12
                    elif ' ' + keyword + ' ' in ' ' + query_lower + ' ':
                        weight = 10
                    elif keyword in words:
                        weight = 8
                    else:
                        weight = 5
                    score += weight
                    keyword_matches += 1

            for keyword in config['keywords']:
                if len(keyword) > 4:
                    for word in words:
                        if len(word) > 3:
                            fuzzy_score = self.fuzzy_match_score(keyword, word)
                            if 0.8 < fuzzy_score < 1.0:
                                score += 6 * fuzzy_score

            if keyword_matches > 0:
                base_score = score / max(len(config['keywords']), 10)
                match_boost = 1 + (keyword_matches * 0.15)
                intent_scores[intent_name] = base_score * match_boost

        if intent_scores:
            best_intent = max(intent_scores, key=intent_scores.get)
            max_score = intent_scores[best_intent]
            confidence = min(max_score / 20, 1.0)
            if max_score > 25:
                confidence = min(confidence * 1.2, 1.0)

            # ── Location question word hard override ──────────────────────────
            # "Where is the Cashier Office?" must always be location_query even
            # though "cashier" and "office" also appear in authority_query keywords.
            # Also catches "college of X dean's office" queries.
            _LOC_STARTERS = ('where', 'saan', 'nasa saan', 'how to get to',
                             'how do i get to', 'paano pumunta', 'direction to',
                             'directions to', 'locate', 'find the')
            _LOC_PHRASES = ("dean's office", "deans office", "dean office",
                            "chancellor's office", "registrar's office",
                            "cashier's office", "admin office")
            # Building code + number pattern: "vmb 401", "gzb 302", "ob 101"
            _BUILDING_CODES = ('vmb', 'gzb', 'ob', 'tsb', 'valerio', 'gonzales',
                               'room', 'floor', 'building')
            if best_intent != 'location_query':
                ql = query_lower.strip()
                if (any(ql.startswith(s) for s in _LOC_STARTERS) or
                        any(p in ql for p in _LOC_PHRASES) or
                        (any(b in ql for b in _BUILDING_CODES) and
                         bool(re.search(r'\d+', ql)))):
                    best_intent = 'location_query'
                    confidence = min(confidence * 1.1, 1.0)

            return best_intent, confidence

        return 'general_info', 0.25

    def is_list_query(self, query: str) -> bool:
        query_lower = self.normalize_query(query)

        strong_list_indicators = [
            'list all', 'show all', 'give me all', 'display all',
            'all the', 'all of the', 'complete list', 'full list',
            'enumerate', 'list of', 'what are all', 'show me all',
            'all student', 'all organizations', 'all orgs',
            'all officials', 'all university officials', 'all authorities',
            'all faculty', 'all staff', 'all administrators',
            'who are all', 'show all officials', 'list all officials'
        ]
        for indicator in strong_list_indicators:
            if indicator in query_lower:
                return True

        singular_patterns = [
            r'\bwho is the\b',
            r'\bwhat is the\b',
            r'\bwhere is the\b',
        ]
        for pattern in singular_patterns:
            if re.search(pattern, query_lower):
                return False

        plural_patterns = [
            r'\bwho are\b',
            r'\bwhat are\b',
            r'\ball\s+\w+s\b',
            r'\bshow.*organizations\b',
            r'\blist.*organizations\b',
        ]
        for pattern in plural_patterns:
            if re.search(pattern, query_lower):
                return True

        if re.search(r'\b(what|which)\s+\w+s\b', query_lower):
            return True

        return False

    def extract_entities(self, original_query: str) -> Dict[str, List[str]]:
        """
        Extract entities always from the ORIGINAL query (not normalized).
        College detection uses the module-level extract_college_from_query()
        which handles all abbreviation/full-name/Tagalog patterns.
        """
        entities = {
            'person_names': [],
            'first_names': [],
            'departments': [],
            'dept_keywords': [],
            'locations': [],
            'time_references': [],
            'room_numbers': [],
            'specific_role': None
        }

        query_lower = original_query.lower().strip()

        # ── 1. Role extraction (specific before generic) ──────────────────────
        role_priority = [
            # Most specific first to avoid partial matches
            ('associate dean',  ['associate dean', 'assoc dean', 'asst dean', 'assistant dean']),
            ('vice president',  ['vice president', 'vp', 'vice-president']),
            ('president',       ['university president', 'campus president', 'president']),
            ('dean',            ['dean']),
            ('director',        ['director']),
            ('head',            ['department head', 'dept head', 'department chair', 'head']),
            ('chairman',        ['chairman', 'chairperson', 'chair']),
            ('coordinator',     ['coordinator']),
            ('registrar',       ['registrar']),
            ('chancellor',      ['chancellor']),
            ('provost',         ['provost']),
        ]
        for role, patterns in role_priority:
            for pat in patterns:
                if pat in query_lower:
                    entities['specific_role'] = role
                    break
            if entities['specific_role']:
                break

        # ── 2. College / department (use dedicated extractor on ORIGINAL query) ─
        dept_codes, dept_keywords = extract_college_from_query(original_query)
        entities['departments'] = dept_codes
        entities['dept_keywords'] = dept_keywords

        # ── 3. Person name extraction ─────────────────────────────────────────────────────
        # Words that are never person names
        skip_words = {
            'Dean', 'President', 'Director', 'Head', 'Vice', 'Associate',
            'College', 'University', 'Department', 'Who', 'What', 'Where',
            'Show', 'Tell', 'Find', 'How', 'Give', 'List', 'The', 'Of',
            'Cet', 'Cics', 'Cas', 'Cabe', 'Cte', 'Bsu', 'Lipa',
            'Registrar', 'Chancellor', 'Provost', 'Coordinator', 'Chairman',
            'Chairperson', 'Chair', 'Engineering', 'Technology', 'Arts',
            'Sciences', 'Informatics', 'Computing', 'Accountancy', 'Business',
            'Economics', 'Education',
        }

        # KEY RULE: if a role was detected, this is a role query ("who is the dean")
        # Only extract a person name when NO role was detected ("who is Juan")
        # Honorifics — includes Filipino "maam" / "ma'am" / "sir"
        HONORIFICS = r"(?:sir|maam|ma[''`]?am|dr\.?|prof\.?|mr\.?|ms\.?|mrs\.?|engr\.?|atty\.?|asst\.?)"
        skip_lower = {w.lower() for w in skip_words}

        # KEY RULE: if a role was detected, this is a role query ("who is the dean")
        # Only extract a person name when NO role was detected ("who is Juan")
        if not entities['specific_role']:
            # Normalize query for matching — collapse multiple spaces
            _q = re.sub(r'\s+', ' ', original_query).strip()

            # Pattern 1: honorific + name — handles Title Case AND ALL CAPS
            # e.g. "Who is Mr. DIONECES O. ALIMOREN?" or "Who is maam Sulit"
            title_pat = (
                rf"(?:who\s+is\s+|about\s+|find\s+)"
                rf"{HONORIFICS}\s+"
                rf"([A-Za-z][A-Za-z.'\-]{{1,}}(?:\s+[A-Za-z.'\-]{{1,}})*)"
            )
            m = re.search(title_pat, _q, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                # Remove trailing punctuation
                raw = re.sub(r'[?.!,]+$', '', raw).strip()
                name = raw.title()
                if name.lower() not in skip_lower and len(name) > 2:
                    entities['first_names'].append(name)
            else:
                # Pattern 2: plain "who is X" — Title Case or ALL CAPS
                plain_pat = (
                    r"who\s+is\s+(?:the\s+)?"
                    r"([A-Za-z][A-Za-z.'\-]{1,}(?:\s+[A-Za-z.'\-]{1,})*)"
                )
                m = re.search(plain_pat, _q, re.IGNORECASE)
                if m:
                    raw = re.sub(r'[?.!,]+$', '', m.group(1).strip()).strip()
                    name = raw.title()
                    if name.lower() not in skip_lower and len(name) > 2:
                        entities['first_names'].append(name)

        # Other name contexts: contact, find, where is, email, honorific alone
        # Updated to handle ALL CAPS names too
        other_name_pats = [
            rf"contact\s+{HONORIFICS}?\s*([A-Za-z][A-Za-z'\-]+)",
            rf"about\s+{HONORIFICS}\s+([A-Za-z][A-Za-z'\-]+(?:\s+[A-Za-z'\-]+)*)",
            rf"find\s+{HONORIFICS}?\s*([A-Za-z][A-Za-z'\-]+)",
            rf"where\s+is\s+{HONORIFICS}\s+([A-Za-z][A-Za-z'\-]+)",
            rf"email\s+of\s+{HONORIFICS}?\s*([A-Za-z][A-Za-z'\-]+)",
            rf"{HONORIFICS}\s+([A-Za-z][A-Za-z'\-]{{2,}}(?:\s+[A-Za-z.'\-]{{1,}})*)",
        ]
        for pat in other_name_pats:
            for match in re.findall(pat, original_query, re.IGNORECASE):
                raw = re.sub(r'[?.!,]+$', '', match.strip())
                name = raw.title()
                if len(name) > 2 and name.lower() not in skip_lower:
                    if name not in entities['first_names']:
                        entities['first_names'].append(name)

        # Full capitalized names — Title Case (e.g. "Philip Geneta")
        potential_names = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', original_query)
        # ALL CAPS names — e.g. "DIONECES ALIMOREN", "CATHERYN RAMIREZ-LATADE"
        allcaps_names = re.findall(
            r'\b([A-Z]{2,}(?:[.\-][A-Z]{2,})?(?:\s+[A-Z]{1,2}\.)?(?:\s+[A-Z]{2,}(?:[.\-][A-Z]{2,})?)+)\b',
            original_query
        )
        all_names = potential_names + [n.title() for n in allcaps_names]
        entities['person_names'] = [
            n for n in all_names
            if len(n) > 2 and n not in skip_words
        ]

        # ── Single-word / bare name fallback ─────────────────────────────────
        # Handles: "sulit", "monette", "maam sulit", "sir garcia"
        # Only when no entity found and query is short (1-3 words)
        _qwords_bare = original_query.strip().split()
        if (not entities['first_names'] and not entities['person_names']
                and not entities['specific_role']
                and 1 <= len(_qwords_bare) <= 3):
            _HONOR = {'sir', 'maam', 'mam', 'dr', 'mr', 'ms', 'mrs',
                      'prof', 'engr', 'atty', 'asst'}
            for _w in _qwords_bare:
                _wc = re.sub(r'[^a-zA-Z]', '', _w).lower()
                if _wc in _HONOR:
                    continue  # skip honorific, keep looking
                if len(_wc) >= 3 and _wc not in skip_lower:
                    entities['first_names'].append(_wc.title())

        # ── 4. Locations ──────────────────────────────────────────────────────
        location_keywords = ['building', 'hall', 'library', 'gymnasium', 'auditorium',
                        'laboratory', 'office', 'room', 'floor', 'campus',
                        'canteen', 'cafeteria', 'clinic', 'chapel', 'gym',
                        'lrc', 'learning resource center', 'registrar', 'cashier']
        for keyword in location_keywords:
            if keyword in query_lower:
                m = re.search(rf'(\w+\s+)*{keyword}', query_lower)
                if m:
                    entities['locations'].append(m.group(0).strip())
                else:
                    # Even if no prefix, add the keyword itself as location
                    entities['locations'].append(keyword)

        # ── 5. Room numbers ───────────────────────────────────────────────────
        entities['room_numbers'] = re.findall(
            r'\b(?:room\s+)?([A-Z]?\d{2,4}[A-Z]?)\b', original_query, re.IGNORECASE
        )

        # ── 6. Time references ────────────────────────────────────────────────
        entities['time_references'] = [
            kw for kw in ['today', 'tomorrow', 'this week', 'next week',
                           'upcoming', 'latest', 'recent', 'current', 'now']
            if kw in query_lower
        ]

        print(f"\n=== Entity Extraction ===")
        print(f"Query: {original_query!r}")
        print(f"Role: {entities['specific_role']}")
        print(f"Departments: {entities['departments']}")
        print(f"Dept keywords: {entities['dept_keywords']}")
        print(f"First names: {entities['first_names']}")
        print(f"========================\n")

        return entities

    def retrieve_context(self, db: Session, original_query: str,
                         intent: str, entities: Dict) -> List[Tuple[Any, float]]:
        """
        Hybrid retrieval: semantic + keyword + fuzzy matching.
        Takes original_query (not normalized) so entity info is still intact.
        """
        config = self.intent_config.get(intent, {})
        max_results = config.get('max_results', 5)
        threshold = config.get('similarity_threshold', 0.3)

        documents = self._fetch_documents_by_intent(db, intent, entities, original_query)

        if not documents:
            return []

        # ── Bypass scoring for all-officials queries ──────────────────────────
        if intent == 'authority_query':
            _ql2 = original_query.lower() if original_query else ''
            _all_triggers = ['all official', 'all university official', 'all authorit',
                             'all faculty', 'all staff', 'all administrator',
                             'who are all', 'show all', 'list all', 'all personnel']
            if any(t in _ql2 for t in _all_triggers):
                print(f"[officials] bypassing scoring, returning {len(documents)} docs")
                return [(doc, 1.0) for doc in documents]

        # ── Bypass scoring for org list queries ───────────────────────────────
        # When user asks to list all orgs, return all without scoring filter
        if intent == 'organization_query':
            _ql = self.normalize_query(original_query)
            _list_triggers = ['all', 'list', 'show all', 'lahat', 'all org',
                              'all organization', 'show org', 'mga organisasyon',
                              'lahat ng org']
            _is_list = any(t in _ql for t in _list_triggers)
            if _is_list or len(documents) > 1:
                return [(doc, 1.0) for doc in documents]
            # Single org result — return as is
            return [(doc, 1.0) for doc in documents]

        # For authority queries: check if we need to ask "which college?" first
        if intent == 'authority_query':
            specific_role = entities.get('specific_role')
            has_department = bool(entities.get('departments')) or bool(entities.get('dept_keywords'))
            has_first_name = bool(entities.get('first_names'))

            print(f"[retrieve_context] role={specific_role} has_dept={has_department} "
                  f"has_name={has_first_name} docs={len(documents)}")

            # Return all for college selection only for multi-college roles
            multi_college_roles = ['dean', 'director', 'head', 'chairman', 'coordinator']
            if (specific_role in multi_college_roles
                    and not has_department
                    and not has_first_name
                    and len(documents) > 1):
                print("→ Multiple colleges found, returning all for selection")
                return [(doc, 0.9) for doc in documents]

        has_first_name = bool(entities.get('first_names'))
        has_specific_role = bool(entities.get('specific_role'))
        has_department = bool(entities.get('departments')) or bool(entities.get('dept_keywords'))

        # Skip semantic scoring when entity signals are strong — it hurts structured lookups
        # Any role OR name query uses entity-first scoring (no semantic noise)
        strong_entity_query = has_specific_role or has_first_name

        use_embeddings = self.use_embeddings and (not strong_entity_query)

        # ── Use pre-computed cache if ready, otherwise call Gemini API ─────────
        query_embedding = None
        doc_embeddings_list = None
        similarities = []
        if use_embeddings:
            try:
                query_embedding = embed_text(original_query)
                if query_embedding is None:
                    use_embeddings = False
                else:
                    doc_embeddings_list = []
                    for doc in documents:
                        table_name = doc.__class__.__tablename__
                        cached = self._embedding_cache.get((table_name, doc.id))
                        if cached is not None:
                            doc_embeddings_list.append(cached)
                        else:
                            # Doc added after startup — embed on the fly and cache it
                            text = self._doc_to_text(doc, intent)
                            emb = embed_text(text)
                            if emb is not None:
                                self._embedding_cache[(table_name, doc.id)] = emb
                            doc_embeddings_list.append(emb)

                    # Filter out None embeddings
                    valid_pairs = [(i, e) for i, e in enumerate(doc_embeddings_list) if e is not None]
                    if valid_pairs:
                        idxs, vecs = zip(*valid_pairs)
                        sims = cosine_sim_matrix(query_embedding, list(vecs))
                        similarities = [0.0] * len(doc_embeddings_list)
                        for idx, sim in zip(idxs, sims):
                            similarities[idx] = sim

            except Exception as e:
                print(f"Embedding error: {e}")
                use_embeddings = False

        scored_docs = []

        for i, doc in enumerate(documents):
            doc_text = self._doc_to_text(doc, intent)

            semantic_score = 0.0
            if use_embeddings and similarities:
                try:
                    semantic_score = float(similarities[i]) if i < len(similarities) else 0.0
                except Exception:
                    semantic_score = 0.0

            keyword_score = self._calculate_keyword_overlap(original_query, doc_text)
            fuzzy_score = self._calculate_fuzzy_match(original_query, doc, entities, intent)
            entity_score = self._calculate_entity_match(entities, doc, intent)

            # ── Full name exact match override ────────────────────────────────
            # When a full person name was extracted (e.g. "Monette M. Soquiat"),
            # any doc whose name contains ALL the key words of that name gets a
            # massive boost — guaranteeing it wins over generic keyword matches.
            name_exact_boost = 0.0
            if intent == 'authority_query' and entities.get('first_names') and hasattr(doc, 'name'):
                doc_name_lower = doc.name.lower()
                for fn in entities['first_names']:
                    fn_words = [w for w in fn.lower().split()
                                if len(w) > 2 and w not in
                                {'dr', 'mr', 'ms', 'mrs', 'prof', 'engr', 'atty', 'sir', 'maam'}]
                    if not fn_words:
                        continue
                    hits = sum(1 for w in fn_words if w in doc_name_lower)
                    if hits == len(fn_words):
                        # All words matched — this is the right person
                        name_exact_boost = 5.0
                        break
                    elif hits >= max(1, len(fn_words) - 1):
                        # All but one word matched — very likely the right person
                        name_exact_boost = max(name_exact_boost, 3.0)

            # ── Location name phrase boost ────────────────────────────────────
            # Fixes: "Where is Office of Vice Chancellor for Admin and Finance"
            # returning CET Dean's Office because word "administration" matched.
            # We count how many query content-words appear in the room NAME
            # specifically and boost docs where the name is a better phrase match.
            loc_phrase_boost = 0.0
            if intent == 'location_query' and hasattr(doc, 'name'):
                _skip_loc = {'where', 'is', 'the', 'of', 'for', 'and', 'or',
                             'find', 'locate', 'location', 'room', 'office', 'a',
                             'what', 'how', 'get', 'to', 'me', 'can', 'you'}
                _qw = [w for w in original_query.lower().split()
                       if w not in _skip_loc and len(w) >= 3]
                _dn = doc.name.lower()
                _hits = sum(1 for w in _qw if w in _dn)
                if _hits > 0:
                    loc_phrase_boost = min(_hits * 0.35, 1.0)

            if strong_entity_query:
                combined = (keyword_score * 0.25 + fuzzy_score * 0.25
                            + entity_score * 0.50) + loc_phrase_boost + name_exact_boost
            elif use_embeddings:
                combined = (semantic_score * 0.40 + keyword_score * 0.25
                            + fuzzy_score * 0.20 + entity_score * 0.15) + loc_phrase_boost + name_exact_boost
            else:
                combined = (keyword_score * 0.40 + fuzzy_score * 0.30
                            + entity_score * 0.30) + loc_phrase_boost + name_exact_boost

            if combined >= threshold:
                # Penalize emergency exits — they should never surface as a primary result
                if hasattr(doc, 'name') and 'emergency' in doc.name.lower():
                    combined = -1.0
                scored_docs.append((doc, combined))

        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # ── Name-query minimum score guard ────────────────────────────────────
        # When searching by person name, require a meaningful fuzzy match.
        # Prevents "Dioneces" fuzzy-matching "GENETA," (score 0.267) from winning
        # when the target person isn't in the fetched results at all.
        if (intent == 'authority_query'
                and entities.get('first_names')
                and not entities.get('specific_role')):
            # Keep only docs where the name actually appears or scores strongly
            name_filtered = []
            for doc, score in scored_docs:
                if not hasattr(doc, 'name'):
                    continue
                doc_lower = doc.name.lower()
                # Accept if ANY extracted name word appears as substring in doc name
                name_hit = any(
                    w.lower() in doc_lower
                    for fn in entities['first_names']
                    for w in fn.split()
                    if len(re.sub(r'[^a-zA-Z]', '', w)) >= 3
                    and re.sub(r'[^a-zA-Z]', '', w).lower() not in
                        {'dr', 'mr', 'ms', 'mrs', 'prof', 'engr', 'atty', 'sir', 'maam'}
                )
                if name_hit or score >= 3.0:  # score>=3 means name_exact_boost fired
                    name_filtered.append((doc, score))
            # CRITICAL FIX: always use name_filtered result (even if empty).
            # When empty, return [] so generate_response fires the fallback message
            # instead of silently returning wrong/unrelated people from scored_docs.
            scored_docs = name_filtered

        if len(scored_docs) > max_results:
            scored_docs = self._apply_diversity(scored_docs, max_results)

        return scored_docs[:max_results]

    def _fetch_documents_by_intent(self, db: Session, intent: str,
                                   entities: Dict, original_query: str = '') -> List[Any]:
        """Fetch relevant documents from database based on intent and entities."""
        try:
            if intent == 'authority_query':
                query = db.query(models.Authority)

                # ── If list query — return ALL authorities from DB ──────────
                _ql = original_query.lower() if original_query else ''
                _list_all_triggers = [
                    'all official', 'all university official', 'all authorit',
                    'all faculty', 'all staff', 'all administrator',
                    'show all', 'list all', 'who are all', 'all personnel',
                    'lahat ng', 'all the official'
                ]
                _matched = [t for t in _list_all_triggers if t in _ql]
                print(f"[officials] _ql={_ql!r} matched={_matched}")
                if _matched:
                    all_authorities = db.query(models.Authority).order_by(
                        models.Authority.department, models.Authority.position
                    ).all()
                    print(f"[officials] returning {len(all_authorities)} authorities")
                    return all_authorities

                # ── First name / surname search (highest priority) ──────────
                if entities.get('first_names'):
                    # Extract all meaningful words from the full extracted name
                    _all_name_words = []
                    for fn in entities['first_names']:
                        for w in fn.split():
                            if len(w) > 2 and w.lower() not in {
                                'dr', 'mr', 'ms', 'mrs', 'prof', 'engr',
                                'atty', 'sir', 'maam', 'the', 'and'
                            }:
                                _all_name_words.append(w)

                    if _all_name_words:
                        # Try each word individually — catches names stored in any format
                        # e.g. "SOQUIAT, MONETTE M." or "DR. MONETTE M. SOQUIAT"
                        word_filters = [
                            models.Authority.name.ilike(f'%{w}%')
                            for w in _all_name_words
                        ]
                        # Use AND logic for multi-word names (more precise)
                        # Use OR logic for single-word names (broader)
                        if len(_all_name_words) >= 2:
                            # Must match at least the 2 most distinctive words
                            # Pick the two longest words as they're most unique
                            sorted_words = sorted(_all_name_words, key=len, reverse=True)
                            primary_filters = [
                                models.Authority.name.ilike(f'%{w}%')
                                for w in sorted_words[:2]
                            ]
                            results = db.query(models.Authority).filter(
                                and_(*primary_filters)
                            ).all()
                            if not results:
                                # Fall back to OR on all words
                                results = db.query(models.Authority).filter(
                                    or_(*word_filters)
                                ).all()
                        else:
                            results = db.query(models.Authority).filter(
                                or_(*word_filters)
                            ).all()

                        if not results:
                            # Try broader OR search across ALL name words individually
                            results = db.query(models.Authority).filter(
                                or_(*word_filters)
                            ).all()
                        if not results:
                            # Try stripping punctuation from each word
                            # Handles names stored with different punctuation/formatting
                            clean_filters = [
                                models.Authority.name.ilike(
                                    f'%{re.sub(r"[^a-zA-Z]", "", w)}%'
                                )
                                for w in _all_name_words
                                if len(re.sub(r'[^a-zA-Z]', '', w)) >= 3
                            ]
                            if clean_filters:
                                results = db.query(models.Authority).filter(
                                    or_(*clean_filters)
                                ).all()
                        # Never fall back to ALL authorities — that returns wrong people.
                        # Return whatever we have (even empty); scorer/fallback handles it.
                        print(f"[authority] name search returned {len(results)} result(s)")
                        return results

                # ── Role filter ────────────────────────────────────────────
                specific_role = entities.get('specific_role')
                if specific_role:
                    role_filters = []
                    if specific_role == 'dean':
                        role_filters.append(
                            and_(
                                models.Authority.position.ilike('%dean%'),
                                ~models.Authority.position.ilike('%associate%'),
                                ~models.Authority.position.ilike('%assistant%'),
                                ~models.Authority.position.ilike('%asst%'),
                                ~models.Authority.position.ilike('%vice%'),
                            )
                        )
                    elif specific_role == 'associate dean':
                        role_filters.append(
                            or_(
                                models.Authority.position.ilike('%associate dean%'),
                                models.Authority.position.ilike('%assistant dean%'),
                                models.Authority.position.ilike('%asst dean%'),
                            )
                        )
                    elif specific_role == 'president':
                        role_filters.append(
                            and_(
                                models.Authority.position.ilike('%president%'),
                                ~models.Authority.position.ilike('%vice%'),
                            )
                        )
                    elif specific_role == 'vice president':
                        role_filters.append(models.Authority.position.ilike('%vice president%'))
                    elif specific_role == 'director':
                        role_filters.append(models.Authority.position.ilike('%director%'))
                    elif specific_role in ('head', 'chairman'):
                        role_filters.append(
                            or_(
                                models.Authority.position.ilike('%head%'),
                                models.Authority.position.ilike('%chairman%'),
                                models.Authority.position.ilike('%chairperson%'),
                            )
                        )
                    else:
                        role_filters.append(
                            models.Authority.position.ilike(f'%{specific_role}%')
                        )
                    if role_filters:
                        query = query.filter(or_(*role_filters))

                # ── Department / college filter ────────────────────────────
                # Combine canonical codes and expanded keywords for broad matching
                dept_codes = entities.get('departments', [])
                dept_kws = entities.get('dept_keywords', [])
                all_dept_terms = list(set(dept_codes + dept_kws))

                # ── Position-context keyword filter ────────────────────────
                # When the query contains specific unit/service keywords but NO college
                # was extracted (dept_codes is empty), search the position field directly
                # so non-college unit heads are found (e.g. Alimoren for ICT, Generoso for QA).
                # Maps query trigger words → position ILIKE search term.
                _ql_lower = (original_query or '').lower()
                _pos_ctx_terms = []
                _pos_ctx_map = {
                    # Most specific first (multi-word before single-word)
                    'internal audit':           'Internal Audit',
                    'quality assurance':        'Quality Assurance',
                    'sustainable development':  'Sustainable Development',
                    'ict services':             'ICT Services',
                    'general education':        'General Education',
                    'health services':          'Health Services',
                    'library services':         'Library Services',
                    'library':                  'Library',
                    'registration services':    'Registration Services',
                    'registration':             'Registration',
                    'testing and admission':    'Testing and Admission',
                    'testing':                  'Testing',
                    'admission':                'Admission',
                    'on the job training':      'On the Job Training',
                    'ojt':                      'On the Job Training',
                    'student organization':     'Student Organization',
                    'guidance and counselling': 'Guidance and Counselling',
                    'guidance and counseling':  'Guidance and Counselling',
                    'guidance':                 'Guidance',
                    'counselling':              'Counselling',
                    'counseling':               'Counselling',
                    'student discipline':       'Student Discipline',
                    'discipline':               'Discipline',
                    'national service training': 'National Service Training',
                    'nstp':                     'National Service Training',
                    'culture and arts':         'Culture and Arts',
                    'sports development':       'Sports Development',
                    'sports':                   'Sports',
                    'scholarship':              'Scholarship',
                    'financial assistance':     'Financial Assistance',
                    'human resource':           'Human Resource',
                    'records management':       'Records Management',
                    'records':                  'Records',
                    'procurement':              'Procurement',
                    'property and supply':      'Property and Supply',
                    'property':                 'Property',
                    'supply':                   'Supply',
                    'project and facility':     'Project and Facility',
                    'facility management':      'Facility Management',
                    'facility':                 'Facility',
                    'general services':         'General Services',
                    'environmental management': 'Environmental Management',
                    'environmental':            'Environmental',
                    'budget':                   'Budget',
                    'cashiering':               'Cashiering',
                    'cashier':                  'Cashiering',
                    'accounting':               'Accounting',
                    'disbursing':               'Disbursing',
                    'research':                 'Research',
                    'extension services':       'Extension Services',
                    'extension':                'Extension',
                    'external affairs':         'External Affairs',
                    'resource generation':      'Resource Generation',
                    'job placement':            'Job Placement',
                    'employment':               'Job Placement',
                    'planning and development': 'Planning and Development',
                    'planning':                 'Planning',
                    'development':              'Development',
                    'ict':                      'ICT',
                }
                if not dept_codes:  # only when no college filter applies
                    for trigger, pos_kw in _pos_ctx_map.items():
                        if trigger in _ql_lower:
                            _pos_ctx_terms.append(pos_kw)
                            break  # one match is enough (most-specific wins)

                if all_dept_terms:
                    dept_conditions = [
                        models.Authority.department.ilike(f'%{term}%')
                        for term in all_dept_terms
                    ]
                    query = query.filter(or_(*dept_conditions))
                elif _pos_ctx_terms:
                    # Search in position field instead of department
                    pos_conditions = [
                        models.Authority.position.ilike(f'%{term}%')
                        for term in _pos_ctx_terms
                    ]
                    query = query.filter(or_(*pos_conditions))

                return query.all()

            elif intent == 'location_query':
                _loc_base = db.query(models.RoomLocation).filter(
                    ~models.RoomLocation.name.ilike('%emergency%'),
                )

                # Alias map: common terms → DB search variants
                _alias = {
                    'library': ['library', 'lrc', 'learning resource center'],
                    'lrc': ['library', 'lrc', 'learning resource center'],
                    'gym': ['gym', 'gymnasium'],
                    'gymnasium': ['gym', 'gymnasium'],
                    'canteen': ['canteen', 'cafeteria'],
                    'cafeteria': ['canteen', 'cafeteria'],
                    'clinic': ['clinic', 'infirmary', 'health'],
                    'chapel': ['chapel', 'church'],
                    'registrar': ['registrar', 'registration'],
                    'cashier': ['cashier', 'finance', 'disbursing'],
                    'speech lab': ['speech'],
                    'speech laboratory': ['speech'],
                    'dean\'s office': ['dean\'s office', "dean's office", 'deans office'],
                    'deans office': ['dean\'s office', "dean's office", 'deans office'],
                    'computer lab': ['computer lab', 'computer laboratory', 'comlab'],
                    'computer laboratory': ['computer lab', 'computer laboratory', 'comlab'],
                    'comlab': ['computer lab', 'computer laboratory', 'comlab'],
                    'it lab': ['computer lab', 'computer laboratory', 'it lab'],
                    'vmb': ['vmb', 'valerio malabanan'],
                    'valerio': ['vmb', 'valerio malabanan'],
                    'gzb': ['gzb'],
                    'ob': ['ob'],
                    'cet': ['cet'],
                    'cics': ['cics'],
                    'restroom': ['restroom', 'comfort room', 'cr', 'lavatory'],
                    'comfort room': ['restroom', 'comfort room', 'cr'],
                    'cr': ['restroom', 'comfort room', 'cr'],
                }

                # Collect search terms from entity extraction
                _terms = []
                for loc in (entities.get('locations') or []):
                    _ll = loc.lower().strip()
                    _terms.extend(_alias.get(_ll, [_ll]))

                # ALSO pull words directly from the raw query — catches "speech lab",
                # "VMB", building codes that entity extraction may miss
                _skip = {'where', 'what', 'find', 'show', 'tell', 'about', 'is',
                         'the', 'are', 'how', 'get', 'to', 'me', 'can', 'you',
                         'please', 'want', 'know', 'look', 'for', 'location',
                         'located', 'place', 'situated', 'and', 'or', 'of', 'a'}
                _raw = [w for w in original_query.lower().split() if w not in _skip and len(w) >= 2]
                _terms.extend(_raw)

                # Room numbers (e.g. "402")
                for rn in (entities.get('room_numbers') or []):
                    _terms.append(rn)

                # Deduplicate
                _terms = list(dict.fromkeys(_terms))

                if _terms:
                    _filters = [
                        or_(
                            models.RoomLocation.name.ilike(f'%{t}%'),
                            models.RoomLocation.building.ilike(f'%{t}%'),
                        )
                        for t in _terms
                    ]
                    results = _loc_base.filter(or_(*_filters)).all()
                else:
                    results = _loc_base.all()

                # ── Exact-phrase boost: re-rank by how many consecutive query
                # words appear in the room name. This fixes cases like
                # "Vice Chancellor for Administration and Finance" returning
                # a CET record because individual words matched better.
                if results and len(results) > 1:
                    _qwords = [w for w in original_query.lower().split()
                               if w not in _skip and len(w) >= 3]
                    # Extract numbers from query for exact number matching
                    _query_nums = re.findall(r'\b\d+\b', original_query)

                    def _name_score(loc):
                        _n = loc.name.lower()
                        hits = sum(1 for w in _qwords if w in _n)
                        # Extra bonus for consecutive phrase match
                        for length in range(min(6, len(_qwords)), 1, -1):
                            for start in range(len(_qwords) - length + 1):
                                phrase = ' '.join(_qwords[start:start + length])
                                if len(phrase) > 5 and phrase in _n:
                                    hits += length * 2
                                    break
                        # CRITICAL: exact number match
                        if _query_nums:
                            loc_nums = re.findall(r'\b\d+\b', loc.name)
                            for num in _query_nums:
                                if num in loc_nums:
                                    hits += 10
                                else:
                                    hits -= 5
                        # CRITICAL: college/dept abbreviation match
                        # "CET dean's office" must beat "CAS dean's office"
                        # Check if any dept code from query appears in location name
                        _dept_codes = {
                            'cet': ['cet', 'engineering technology'],
                            'cas': ['cas', 'arts and science'],
                            'cabe': ['cabe', 'accountancy', 'business'],
                            'cics': ['cics', 'informatics', 'computing'],
                            'cte': ['cte', 'teacher education'],
                        }
                        _q_lower = original_query.lower()
                        for code, variants in _dept_codes.items():
                            query_has_dept = any(v in _q_lower for v in variants)
                            name_has_dept = code in _n or any(v in _n for v in variants)
                            if query_has_dept and name_has_dept:
                                hits += 8
                            elif query_has_dept and not name_has_dept:
                                hits -= 4
                        # Distinctive long words get extra weight
                        # Prevents "cashier office" returning "dean's office"
                        _skip_common = {'where', 'floor', 'level', 'building',
                                        'located', 'office', 'room', 'find'}
                        for w in _qwords:
                            if len(w) >= 6 and w not in _skip_common and w in _n:
                                hits += 3
                        return hits
                    results = sorted(results, key=_name_score, reverse=True)

                return results

            elif intent == 'history_query':
                all_history = db.query(models.History).order_by(models.History.year).all()

                # Strip common prefixes so matching focuses on the meaningful part
                query_lower = original_query.lower()
                stripped = re.sub(
                    r'^(tell me about|what is|what was|ano ang|about|'
                    r'kwentuhan mo ako tungkol sa|ibigay mo ang|i want to know about)\s+',
                    '', query_lower
                ).strip()

                stop = {'ano', 'ang', 'ng', 'sa', 'mga', 'na', 'at', 'the', 'is',
                        'of', 'a', 'an', 'in', 'on', 'about', 'what', 'tell',
                        'me', 'bsu', 'lipa', 'university', 'history', 'when'}
                raw_words = [
                    w for w in re.sub(r'[^\w\s]', '', stripped).split()
                    if w not in stop and len(w) > 2
                ]

                if raw_words or stripped:
                    def history_score(h):
                        text = (
                            (h.title or '') + ' ' +
                            (h.description or '') + ' ' +
                            str(h.year or '')
                        ).lower()
                        title_lower = (h.title or '').lower()

                        score = 0

                        # Highest priority: stripped query matches title directly
                        if stripped and (stripped in title_lower or title_lower in stripped):
                            score += 10

                        for w in raw_words:
                            if w in text:
                                score += 2          # exact word match
                            else:
                                # partial match
                                if any(w in token or token in w
                                       for token in text.split()
                                       if len(token) > 3):
                                    score += 1
                        return score

                    scored = [(h, history_score(h)) for h in all_history]
                    best_score = max(s for _, s in scored) if scored else 0

                    if best_score > 0:
                        matched = [(h, s) for h, s in scored if s > 0]
                        matched.sort(key=lambda x: x[1], reverse=True)
                        return [h for h, _ in matched]

                    # No history matched — return empty so fallback fires cleanly
                    return []

                return all_history

            elif intent == 'announcement_query':
                query = db.query(models.Announcement).order_by(
                    models.Announcement.date_posted.desc()
                )
                if entities.get('time_references'):
                    if any(t in entities['time_references'] for t in ['today', 'latest']):
                        query = query.limit(5)
                return query.limit(10).all()

            elif intent == 'organization_query':
                # ── Fetch all orgs with members ───────────────────────────
                orgs = db.query(models.Organization).all()
                for org in orgs:
                    org.members = (
                        db.query(models.OrganizationMember)
                        .filter(models.OrganizationMember.org_chart_id == org.id)
                        .order_by(models.OrganizationMember.sort_order)
                        .all()
                    )

                # ── Try to find specific org from query ───────────────────
                _q = original_query.lower().strip() if original_query else ''

                # Skip if it's a "list all" query
                list_triggers = ['all', 'list', 'show all', 'lahat', 'list all',
                                  'all organizations', 'all orgs']
                if any(t in _q for t in list_triggers):
                    return orgs

                # Score each org against the query
                def org_match_score(org, query_str):
                    score = 0.0
                    org_name_lower = org.name.lower()
                    org_words = org_name_lower.split()
                    query_words = [w for w in query_str.split() if len(w) > 1]

                    for qw in query_words:
                        # 1. Exact substring match in org name
                        if qw in org_name_lower:
                            score += 2.0

                        # 2. Acronym match — check if query word matches
                        #    initials of org name words
                        initials = ''.join(w[0] for w in org_words if w)
                        if qw == initials:
                            score += 3.0  # strong signal

                        # 3. Partial acronym — query word is start of initials
                        if initials.startswith(qw) or qw.startswith(initials):
                            score += 1.5

                        # 4. Fuzzy match each word in org name
                        for ow in org_words:
                            if len(ow) > 2 and len(qw) > 2:
                                ratio = SequenceMatcher(None, qw, ow).ratio()
                                if ratio > 0.80:
                                    score += ratio * 1.5

                        # 5. Fuzzy match full org name
                        full_ratio = SequenceMatcher(None, qw, org_name_lower).ratio()
                        if full_ratio > 0.70:
                            score += full_ratio

                    return score

                # Score all orgs
                scored = [(org, org_match_score(org, _q)) for org in orgs]
                scored.sort(key=lambda x: x[1], reverse=True)

                # Return best match if score is good enough
                best_org, best_score = scored[0] if scored else (None, 0)
                if best_score >= 1.5:
                    return [best_org]

                # No specific match found — return all orgs
                return orgs

            else:  # general_info
                results = []
                results.extend(db.query(models.Authority).limit(3).all())
                results.extend(db.query(models.RoomLocation).limit(3).all())
                results.extend(
                    db.query(models.Announcement)
                    .order_by(models.Announcement.date_posted.desc())
                    .limit(2)
                    .all()
                )
                return results

        except Exception as e:
            print(f"Database fetch error: {e}")
            import traceback; traceback.print_exc()
            return []

    def _doc_to_text(self, doc: Any, intent: str) -> str:
        parts = []
        for attr in ('name', 'title', 'position', 'department', 'building',
                     'description', 'content'):
            val = getattr(doc, attr, None)
            if val:
                parts.append(str(val))
        return ' '.join(parts)

    def _calculate_keyword_overlap(self, query: str, doc_text: str) -> float:
        stop_words = {'the', 'is', 'at', 'which', 'on', 'a', 'an', 'and', 'or',
                      'of', 'to', 'in', 'for', 'with', 'by', 'from', 'as'}
        query_words = set(self.normalize_query(query).split()) - stop_words
        doc_words = set(doc_text.lower().split()) - stop_words
        if not query_words:
            return 0.0
        return len(query_words & doc_words) / len(query_words)

    def _calculate_fuzzy_match(self, query: str, doc: Any,
                                entities: Dict, intent: str) -> float:
        max_score = 0.0

        if entities.get('first_names') and hasattr(doc, 'name'):
            doc_name_lower = doc.name.lower()
            for first_name in entities['first_names']:
                fn = first_name.lower()
                # Exact substring match — highest confidence
                if fn in doc_name_lower:
                    max_score = max(max_score, 0.98)
                    continue
                # Word-by-word: each word of the extracted name found in doc name
                fn_words = [w for w in fn.split() if len(w) > 1]
                if fn_words:
                    hits = sum(1 for w in fn_words if w in doc_name_lower)
                    if hits == len(fn_words):
                        max_score = max(max_score, 0.95)
                    elif hits >= 1:
                        max_score = max(max_score, 0.7 * hits / len(fn_words))
                # Fuzzy on first token (handles slight misspellings)
                parts = doc.name.split()
                if parts:
                    score = self.fuzzy_match_score(first_name, parts[0])
                    if score > 0.8:
                        max_score = max(max_score, score * 0.9)

        if entities.get('person_names') and hasattr(doc, 'name'):
            doc_name_lower = doc.name.lower()
            for name in entities['person_names']:
                nl = name.lower()
                if nl in doc_name_lower:
                    max_score = max(max_score, 0.95)
                else:
                    max_score = max(max_score, self.fuzzy_match_score(name, doc.name))

        if entities.get('locations'):
            for loc in entities['locations']:
                if hasattr(doc, 'name'):
                    max_score = max(max_score, self.fuzzy_match_score(loc, doc.name))
                if hasattr(doc, 'building'):
                    max_score = max(max_score, self.fuzzy_match_score(loc, doc.building))

        if entities.get('room_numbers') and hasattr(doc, 'name'):
            for room in entities['room_numbers']:
                if room in doc.name:
                    max_score = 1.0

        return max_score

    def _calculate_entity_match(self, entities: Dict, doc: Any, intent: str) -> float:
        score = 0.0

        specific_role = entities.get('specific_role')
        if specific_role and hasattr(doc, 'position'):
            pos = doc.position.lower()
            if specific_role == 'dean':
                if 'dean' in pos and not any(
                    w in pos for w in ['associate', 'assistant', 'asst', 'vice']
                ):
                    score += 1.5
                elif 'dean' in pos:
                    score -= 0.3
            elif specific_role == 'associate dean':
                if any(w in pos for w in ['associate', 'assistant', 'asst']) and 'dean' in pos:
                    score += 1.5
            elif specific_role == 'president':
                if 'president' in pos and 'vice' not in pos:
                    score += 1.5
            elif specific_role == 'vice president':
                if 'vice' in pos and 'president' in pos:
                    score += 1.5
            else:
                if specific_role in pos:
                    score += 1.0

        if entities.get('dept_keywords') and hasattr(doc, 'department'):
            dept_lower = doc.department.lower()
            for kw in entities['dept_keywords']:
                if kw.lower() in dept_lower:
                    score += 0.5
                    break

        if entities.get('departments') and hasattr(doc, 'department'):
            dept_lower = doc.department.lower()
            for code in entities['departments']:
                if code.lower() in dept_lower:
                    score += 0.5
                    break

        if entities.get('locations'):
            if hasattr(doc, 'building'):
                for loc in entities['locations']:
                    if loc.lower() in doc.building.lower():
                        score += 0.3

        return score

    def _apply_diversity(self, scored_docs: List[Tuple[Any, float]],
                         max_results: int) -> List[Tuple[Any, float]]:
        diverse = [scored_docs[0]]
        for doc, score in scored_docs[1:]:
            if all(self._doc_similarity(doc, sel) < 0.9 for sel, _ in diverse):
                diverse.append((doc, score))
            if len(diverse) >= max_results:
                break
        return diverse

    def _doc_similarity(self, doc1: Any, doc2: Any) -> float:
        if type(doc1) != type(doc2):
            return 0.0
        if hasattr(doc1, 'name') and hasattr(doc2, 'name'):
            return self.fuzzy_match_score(doc1.name, doc2.name)
        if hasattr(doc1, 'title') and hasattr(doc2, 'title'):
            return self.fuzzy_match_score(doc1.title, doc2.title)
        return 0.0

    def needs_department_clarification(self, original_query: str,
                                        entities: Dict,
                                        context: List[Tuple[Any, float]]) -> bool:
        """
        Ask which college ONLY when:
        - asking for dean/director/head
        - no college was specified
        - no person name given
        - multiple results exist
        """
        specific_role = entities.get('specific_role')
        has_department = (bool(entities.get('departments'))
                          or bool(entities.get('dept_keywords')))
        has_first_name = bool(entities.get('first_names'))

        print(f"[clarification?] role={specific_role} dept={has_department} "
              f"name={has_first_name} ctx={len(context)}")

        # Only ask "which college?" for roles that exist in MULTIPLE colleges
        # Unique roles (president, registrar, vice president, etc.) never need clarification
        multi_college_roles = ['dean', 'director', 'head', 'chairman', 'coordinator']
        if (specific_role in multi_college_roles
                and not has_department
                and not has_first_name):
            # If the query already contains specific position/unit context words,
            # the user is asking about a specific person (e.g. "head of ict services"),
            # not a college-level role — skip clarification and let scoring find them.
            # Covers ALL unit heads from the FY 2026 Designated Officials list.
            _position_specifics = [
                # ICT / Development / External Affairs
                'ict', 'ict services', 'planning', 'development', 'external affairs',
                'resource generation', 'job placement', 'employment',
                # Chancellor office units
                'internal audit', 'audit', 'quality assurance', 'sustainable',
                # Academic service units (non-college)
                'general education', 'health services', 'library', 'registration',
                'testing', 'admission', 'ojt', 'on the job', 'student organization',
                'guidance', 'counselling', 'counseling', 'discipline',
                'nstp', 'national service', 'culture', 'arts', 'sports',
                'scholarship', 'financial assistance',
                # Admin / Finance units
                'human resource', 'records', 'procurement', 'property', 'supply',
                'facility', 'project', 'general services', 'environmental',
                'budget', 'cashiering', 'cashier', 'accounting', 'disbursing',
                # Research / Extension
                'research', 'extension',
                # Catch-all service/unit words
                'services', 'management', 'office', 'unit', 'division', 'center',
                'affairs', 'finance', 'administration',
            ]
            _ql = original_query.lower()
            if any(w in _ql for w in _position_specifics):
                print(f"[clarification?] skipped — position-specific context found in query")
                return False
            # Show picker if multiple results OR no results (DB may just be empty for that dept)
            return True
        return False

    def generate_department_selection(self, specific_role: str = 'dean', lang: str = 'en',
                                        context: list = None) -> str:
        """Build clarification prompt from actual DB results, falling back to hardcoded colleges."""
        role_title = specific_role.title() if specific_role else 'Dean'

        # Build options from actual DB context
        options = []
        if context:
            seen = set()
            for doc, _ in context:
                dept = getattr(doc, 'department', '') or ''
                name = getattr(doc, 'name', '') or ''
                if dept and dept not in seen:
                    seen.add(dept)
                    options.append({'dept': dept, 'name': name})

        # Fallback to standard colleges if no context
        if not options:
            options = [
                {'dept': 'College of Engineering Technology (CET)',                'name': ''},
                {'dept': 'College of Informatics and Computing Sciences (CICS)',   'name': ''},
                {'dept': 'College of Arts and Sciences (CAS)',                     'name': ''},
                {'dept': 'College of Accountancy, Business, and Economics (CABE)', 'name': ''},
                {'dept': 'College of Teacher Education (CTE)',                     'name': ''},
            ]

        if lang == 'tl':
            response = f"**Aling {role_title} ang gusto mong malaman?**\n\n"
        else:
            response = f"**Which college {role_title} would you like to know about?**\n\n"

        for i, opt in enumerate(options, 1):
            line = f"**{i}.** {opt['dept']}"
            if opt['name']:
                line += f" - *{opt['name']}*"
            response += line + "\n"

        # Always include CET and CICS so JS college-picker buttons activate
        dept_str = " ".join(o['dept'] for o in options)
        if 'CET' not in dept_str or 'CICS' not in dept_str:
            response += "\n*(CET / CICS / CAS / CABE / CTE)*"

        if lang == 'tl':
            response += "\nI-type ang pangalan ng kolehiyo o numero."
        else:
            response += "\nType the college name to see their information."

        return response

    def generate_response(self, original_query: str,
                          context: List[Tuple[Any, float]],
                          intent: str, intent_confidence: float,
                          lang: str = 'en',
                          entities: Dict = None) -> str:
        """
        Generate response. Always uses original_query for entity re-extraction
        so department info is not lost.
        """
        # Re-use entities passed in from process_query — avoids double extraction
        if entities is None:
            entities = self.extract_entities(original_query)

        # Clarification check — pass context so options are built from real DB data
        if intent == 'authority_query' and self.needs_department_clarification(
                original_query, entities, context):
            return self.generate_department_selection(
                entities.get('specific_role', 'dean'), lang, context=context
            )

        if not context:
            return self.generate_fallback_response(intent, original_query, lang)

        is_list = self.is_list_query(original_query)

        # Force list for all-officials queries regardless of is_list result
        _ql3 = original_query.lower() if original_query else ''
        _force_list_triggers = ['all official', 'all university official', 'all authorit',
                                'all faculty', 'all staff', 'who are all', 'all personnel']
        if intent == 'authority_query' and any(t in _ql3 for t in _force_list_triggers):
            is_list = True

        if is_list and len(context) > 1:
            return self.format_list_response(context, original_query, intent, lang)

        doc, score = context[0]

        if intent == 'authority_query':
            return self.format_authority_response(doc, original_query, score, context, lang)
        elif intent == 'location_query':
            return self.format_location_response(doc, original_query, score, lang)
        elif intent == 'history_query':
            # Show list when query implies multiple records (milestones, timeline, history)
            PLURAL_TRIGGERS = ['milestone', 'milestones', 'timeline', 'all', 'list',
                               'history', 'kasaysayan', 'nakaraan', 'achievements']
            wants_list = (
                len(context) > 1 and
                any(t in original_query.lower() for t in PLURAL_TRIGGERS)
            )
            if wants_list:
                return self.format_history_list(context, lang)
            return self.format_history_response(doc, original_query, score, lang)
        elif intent == 'announcement_query':
            if is_list and len(context) > 1:
                return self.format_announcement_list(context, lang)
            return self.format_announcement_response(doc, original_query, score, lang)
        elif intent == 'organization_query':
            # If multiple orgs returned — always show as list
            if len(context) > 1:
                return self.format_list_response(context, original_query, 'organization_query', lang)
            # Single org — show detailed response
            return self.format_organization_response(doc, original_query, score, False, context, lang)
        else:
            return self._format_general_response(doc, original_query, score, lang)

    def format_list_response(self, context: List[Tuple[Any, float]],
                              query: str, intent: str, lang: str = 'en') -> str:
        if lang == 'tl' and intent == 'authority_query':
            response = f"Narito ang mga awtoridad ({len(context)} kabuuan)! 👥\n\n"
            for doc, score in context:
                response += f"• **{doc.name}** — {doc.position}\n  🏢 {doc.department}\n"
                if doc.email: response += f"  📧 {doc.email}\n"
                response += "\n"
            response += "Gusto mo bang makakuha ng higit pang detalye?"
            return response.strip()
        elif lang == 'tl' and intent == 'location_query':
            response = f"Narito ang mga lokasyon ({len(context)} kabuuan)! 🗺️\n\n"
            for doc, score in context:
                fs = {1:'1st',2:'2nd',3:'3rd'}.get(doc.floor, f'{doc.floor}th')
                response += f"• **{doc.name}**\n  🏢 {doc.building} · {fs} palapag\n\n"
            response += "Gamitin ang **Campus Navigator** para sa interactive na mapa!"
            return response.strip()
        elif lang == 'tl' and intent == 'organization_query':
            response = f"Narito ang mga organisasyon ({len(context)} kabuuan)! 🎓\n\n"
            for i, (doc, score) in enumerate(context, 1): response += f"{i}. **{doc.name}**\n"
            response += "\nMagtanong tungkol sa isang organisasyon para sa mga detalye!"
            return response.strip()
        elif lang == 'tl':
            response = f"Narito ang aking nahanap ({len(context)}):\n\n"
            for doc, score in context:
                if hasattr(doc, 'name'): response += f"• {doc.name}\n"
                elif hasattr(doc, 'title'): response += f"• {doc.title}\n"
            return response.strip()
        if intent == 'authority_query':
            # Group by department for cleaner display
            from collections import defaultdict
            dept_groups = defaultdict(list)
            for doc, score in context:
                dept_groups[doc.department].append(doc)

            response = f"👥 **University Officials ({len(context)} total)**\n\n"
            for dept, members in sorted(dept_groups.items()):
                response += f"**🏢 {dept}**\n"
                for doc in members:
                    response += f"• **{doc.name}** — {doc.position}\n"
                    if doc.email:
                        response += f"  📧 {doc.email}\n"
                response += "\n"
            response += "Ask about a specific person for more details!"
            response += "\n\n📝 *Note: This list may not show all officials. For the complete list, please check the university's official website or visit the admin office.*"
        
        elif intent == 'location_query':
            response = f"Here are the campus locations I found ({len(context)} total)! 🗺️\n\n"
            for doc, score in context:
                floor_suffix = {1: '1st', 2: '2nd', 3: '3rd'}.get(doc.floor, f'{doc.floor}th')
                response += f"• **{doc.name}**\n"
                response += f"  🏢 {doc.building} · {floor_suffix} floor\n\n"
            response += "You can also use the **Campus Navigator** for an interactive map!"
        elif intent == 'organization_query':
            response = f"🎓 **Campus Organizations ({len(context)} total)**\n\n"
            for i, (doc, score) in enumerate(context, 1):
                # Auto-generate acronym
                words = doc.name.split()
                acronym = ''.join(w[0].upper() for w in words if w)
                member_count = len(doc.members) if hasattr(doc, 'members') and doc.members else 0
                response += f"{i}. **{doc.name}**"
                if acronym and acronym != doc.name.upper() and len(acronym) <= 8:
                    response += f" ({acronym})"
                if member_count > 0:
                    response += f" — {member_count} member(s)"
                response += "\n"
            response += "\n💬 Ask about a specific org to see its members! Example: *'Who is ACETS?'*"
        else:
            response = f"Here's what I found ({len(context)} results):\n\n"
            for doc, score in context:
                if hasattr(doc, 'name'):
                    response += f"• {doc.name}\n"
                elif hasattr(doc, 'title'):
                    response += f"• {doc.title}\n"
        return response.strip()

    def format_authority_response(self, doc: Any, query: str, score: float,
                                   context: List[Tuple[Any, float]], lang: str = 'en') -> str:
        name = doc.name
        position = doc.position
        department = doc.department

        # Photo tag — backend sends base64 or URL in doc.photo
        photo_html = ''
        if getattr(doc, 'photo', None):
            photo_html = f'[PHOTO:{doc.photo}]'

        if lang == 'tl':
            response = f"{photo_html}Ang **{position}** ng **{department}** ay si **{name}**. 😊\n\n"
            if doc.office_location: response += f"📍 Mahahanap ang kanyang opisina sa {doc.office_location}.\n"
            if doc.email: response += f"📧 Para sa katanungan, makipag-ugnayan sa {doc.email}.\n"
            if doc.phone: response += f"📱 Maaari ka ring tumawag sa {doc.phone}.\n"
            if doc.bio: response += f"\n\n**Tungkol kay {name.split()[0]}:**\n{doc.bio}"
            if len(context) > 1 and score > 0.85:
                others = [(d,s) for d,s in context[1:3] if s > 0.80]
                if others:
                    response += "\n\n**Maaari ka ring naghahanap ng:**\n"
                    for rd,_ in others: response += f"• **{rd.name}** — {rd.position}\n"
            return response
        response = f"{photo_html}The **{position}** of **{department}** is **{name}**. 😊\n\n"

        details = []
        if doc.office_location:
            details.append(f"📍 You can find their office at {doc.office_location}.")
        if doc.email:
            details.append(f"📧 For inquiries, you may reach them at {doc.email}.")
        if doc.phone:
            details.append(f"📱 You can also contact them at {doc.phone}.")

        if details:
            response += "\n".join(details)

        if doc.bio:
            response += f"\n\n**A little about {name.split()[0]}:**\n{doc.bio}"

        if len(context) > 1 and score > 0.85:
            relevant_others = [(d, s) for d, s in context[1:3] if s > 0.80]
            if relevant_others:
                response += "\n\n**You might also be looking for:**\n"
                for rd, _ in relevant_others:
                    response += f"• **{rd.name}** — {rd.position}, {rd.department}\n"

        return response

    def format_location_response(self, doc: Any, query: str, score: float, lang: str = 'en') -> str:
        floor_suffix = {1: '1st', 2: '2nd', 3: '3rd'}.get(doc.floor, f'{doc.floor}th')
        if lang == 'tl':
            r = f"Ang **{doc.name}** ay nasa **{doc.building}**, {floor_suffix} palapag. 📍\n\n"
            if doc.description: r += f"{doc.description}\n\n"
            if doc.capacity: r += f"👥 Kayang tumanggap ng hanggang **{doc.capacity} tao**.\n\n"
            r += "🗺️ Para sa direksyon, gamitin ang **Campus Navigator**!\n\nMay ibang lokasyon ka bang gustong malaman?"
            return r
        response = f"The **{doc.name}** is located in the **{doc.building}** on the **{floor_suffix} floor**. 📍\n\n"

        if doc.description:
            response += f"{doc.description}\n\n"

        if doc.capacity:
            response += f"👥 It can accommodate up to **{doc.capacity} people**.\n\n"

        response += "🗺️ For step-by-step directions, use the **Campus Navigator** for an interactive map!\n\n"
        response += "Is there another location you'd like to know about?"
        return response

    def format_history_response(self, doc: Any, query: str, score: float, lang: str = 'en') -> str:
        # Use Tagalog DB fields when available, fall back to English fields
        # Use Filipino fields if lang=tl; strip to catch whitespace-only values
        _title_tl = (getattr(doc, 'title_tl', None) or '').strip()
        _desc_tl  = (getattr(doc, 'description_tl', None) or '').strip()
        title       = (_title_tl or doc.title)       if lang == 'tl' else doc.title
        description = (_desc_tl  or doc.description) if lang == 'tl' else doc.description
        if lang == 'tl':
            return (f"Narito ang isang bahagi ng kasaysayan ng BSU Lipa! 🏛️\n\n"
                    f"**{doc.year} — {title}**\n\n{description}\n\n"
                    f"Gusto mo bang malaman ang higit pa tungkol sa kasaysayan ng unibersidad?")
        return (
            f"Here's a piece of BSU Lipa's history! 🏛️\n\n"
            f"**{doc.year} — {title}**\n\n"
            f"{description}\n\n"
            f"Would you like to know more about the university's history or milestones?"
        )

    def format_history_list(self, context: List[Tuple[Any, float]], lang: str = 'en') -> str:
        """Show multiple history records (e.g. when user asks for milestones/timeline)."""
        if lang == 'tl':
            response = f"Narito ang mga pangunahing kasaysayan ng BSU Lipa! 🏛️\n\n"
            for doc, _ in context:
                _title_tl = (getattr(doc, 'title_tl', None) or '').strip()
                _desc_tl  = (getattr(doc, 'description_tl', None) or '').strip()
                title = _title_tl or doc.title
                desc  = _desc_tl  or doc.description
                response += f"**{doc.year} — {title}**\n{desc}\n\n"
            response += "Gusto mo bang malaman ang higit pa tungkol sa kasaysayan ng unibersidad?"
            return response.strip()
        response = f"Here are BSU Lipa's key historical milestones! 🏛️\n\n"
        for doc, _ in context:
            response += f"**{doc.year} — {doc.title}**\n{doc.description}\n\n"
        response += "Would you like to know more about any specific milestone?"
        return response.strip()

    def format_announcement_response(self, doc: Any, query: str, score: float, lang: str = 'en') -> str:
        date_str = doc.date_posted.strftime('%B %d, %Y') if doc.date_posted else ('Kamakailan' if lang == 'tl' else 'Recently')
        # Use Tagalog DB fields when available, fall back to English fields
        _atitle_tl   = (getattr(doc, 'title_tl', None) or '').strip()
        _acontent_tl = (getattr(doc, 'content_tl', None) or '').strip()
        title   = (_atitle_tl   or doc.title)   if lang == 'tl' else doc.title
        content = (_acontent_tl or doc.content) if lang == 'tl' else doc.content
        if lang == 'tl':
            r = f"Narito ang pinakabagong balita! 📢\n\n**{title}**\n"
            r += f"🗓️ Nai-post noong {date_str} · 🏷️ {doc.category}\n\n{content}\n\n"
            r += "Gusto mo bang makita ang higit pang mga anunsyo?"
            return r
        response = f"Here's the latest on that! 📢\n\n"
        response += f"**{title}**\n"
        response += f"🗓️ Posted on {date_str} · 🏷️ {doc.category}\n\n"
        response += f"{content}\n\n"
        response += "Would you like to see more announcements or news?"
        return response

    def format_announcement_list(self, context: List[Tuple[Any, float]], lang: str = 'en') -> str:
        if lang == 'tl':
            response = f"Narito ang mga pinakabagong anunsyo mula sa BSU Lipa! 📢\n\n"
            for doc, score in context:
                d = doc.date_posted.strftime('%B %d, %Y') if doc.date_posted else 'Kamakailan'
                _lt = (getattr(doc, 'title_tl', None) or '').strip()
                title = _lt or doc.title
                response += f"📅 **{d}** · {doc.category}\n**{title}**\n\n"
            response += "Magtanong tungkol sa alinman para sa buong detalye!"
            return response.strip()
        response = f"Here are the latest announcements from BSU Lipa! 📢\n\n"
        for doc, score in context:
            date_str = doc.date_posted.strftime('%B %d, %Y') if doc.date_posted else 'Recent'
            response += f"📅 **{date_str}** · {doc.category}\n"
            response += f"**{doc.title}**\n\n"
        response += "Ask about any of these for the full details!"
        return response.strip()

    def format_organization_response(self, doc: Any, query: str, score: float,
                                      is_list: bool,
                                      context: List[Tuple[Any, float]], lang: str = 'en') -> str:
        if is_list and len(context) > 1:
            return self.format_list_response(context, query, 'organization_query', lang)

        # Single org response
        org_name = doc.name if hasattr(doc, 'name') else 'Organization'
        members = doc.members if hasattr(doc, 'members') else []
        description = doc.description if hasattr(doc, 'description') and doc.description else None

        # Generate acronym from org name
        words = org_name.split()
        acronym = ''.join(w[0].upper() for w in words if w)

        if lang == 'tl':
            r = f"🎓 **{org_name}**"
            if acronym and acronym != org_name.upper():
                r += f" ({acronym})"
            r += "\n\n"
            if description:
                r += f"{description}\n\n"
            if members:
                r += f"**Mga Miyembro ({len(members)}):**\n"
                for m in members:
                    r += f"• **{m.name}** — {m.position}\n"
                r += "\nGusto mo bang magtanong tungkol sa ibang organisasyon?"
            else:
                r += "Wala pang mga miyembro na nakalista para sa organisasyong ito."
            return r.strip()

        # English response
        response = f"🎓 **{org_name}**"
        if acronym and acronym != org_name.upper():
            response += f" ({acronym})"
        response += "\n\n"

        if description:
            response += f"{description}\n\n"

        if members:
            response += f"**Members ({len(members)}):**\n"
            for member in members:
                response += f"• **{member.name}** — {member.position}\n"
            response += "\nWould you like to know about another organization? Just ask!"
        else:
            response += "No members have been listed for this organization yet.\n\n"
            response += "Try asking *'List all organizations'* to see other groups!"

        return response.strip()

    def _format_general_response(self, doc: Any, query: str, score: float, lang: str = 'en') -> str:
        if hasattr(doc, 'name') and hasattr(doc, 'position'):
            return self.format_authority_response(doc, query, score, [(doc, score)], lang)
        elif hasattr(doc, 'building'):
            return self.format_location_response(doc, query, score, lang)
        elif hasattr(doc, 'title') and hasattr(doc, 'content'):
            return self.format_announcement_response(doc, query, score, lang)
        return "I found some information but couldn't format it. Could you be more specific?"

    def generate_fallback_response(self, intent: str, query: str, lang: str = 'en') -> str:
        # Check if this was an "all officials" list query that failed
        _ql = query.lower() if query else ''
        _all_triggers = ['all official', 'all university official', 'all authorit',
                         'all faculty', 'all staff', 'who are all', 'all personnel']
        _is_list_fail = intent == 'authority_query' and any(t in _ql for t in _all_triggers)

        if _is_list_fail:
            if lang == 'tl':
                return "Paumanhin, wala akong impormasyon tungkol sa mga opisyal sa aking database."
            return "Sorry, I don't have that information in my database."

        if lang == 'tl':
            tl_fb = {
                'authority_query':    "Paumanhin, wala akong impormasyon tungkol sa taong iyon o posisyong iyan sa aking database.",
                'location_query':     "Paumanhin, wala akong impormasyon tungkol sa lokasyong iyan sa aking database.",
                'history_query':      "Paumanhin, wala akong impormasyon tungkol sa kasaysayang iyan sa aking database.",
                'announcement_query': "Paumanhin, wala akong impormasyon tungkol sa anunsyong iyan sa aking database.",
                'organization_query': "Paumanhin, wala akong impormasyon tungkol sa organisasyong iyan sa aking database.",
                'navigation_query':   "Paumanhin, wala akong impormasyon tungkol diyan sa aking database.",
                'general_info':       "Paumanhin, wala akong impormasyon tungkol diyan sa aking database.",
            }
            return tl_fb.get(intent, "Paumanhin, wala akong impormasyon tungkol diyan sa aking database.")

        _no_info = "Sorry, I don't have that information in my database."
        fallbacks = {
            'authority_query':    _no_info,
            'location_query':     _no_info,
            'history_query':      _no_info,
            'announcement_query': _no_info,
            'organization_query': _no_info,
            'navigation_query':   _no_info,
            'general_info':       _no_info,
        }
        return fallbacks.get(intent, _no_info)

    def check_custom_response(self, query: str, db: Session,
                               lang: str = 'en') -> Optional[str]:
        """
        Check the intents table for a matching custom response FIRST.
        Keywords field is comma-separated e.g. 'enrollment, how to enroll'.
        Returns the localised response_template if matched, else None.
        - lang='tl'  → uses response_template_tl if set, else falls back to response_template
        - lang='en'  → always uses response_template

        Matching rules:
        - Short keywords (<=4 chars) require word-boundary match, NOT just substring
        - Keywords that are standalone honorifics (sir, maam, mr, ms, dr, etc.)
          are skipped if the query also contains 'who is' — those are name searches
        - Longer keywords use simple substring match as before
        """
        # Honorifics that should never alone trigger a custom intent on a "who is" query
        HONORIFICS = {'sir', 'maam', "ma'am", 'mr', 'ms', 'mrs', 'dr',
                      'prof', 'engr', 'atty', 'hi', 'hey', 'hello'}
        is_person_search = re.search(
            r'\b(who\s+is|who\s+are|find|search|contact)\b',
            query.lower()
        )

        try:
            intents = db.query(models.Intent).all()
            query_lower = query.lower()
            best_match_en = None
            best_match_tl = None
            best_score = 0

            for intent in intents:
                if not intent.keywords or not intent.response_template:
                    continue
                keywords = [k.strip().lower() for k in intent.keywords.split(',') if k.strip()]

                for keyword in keywords:
                    kw_len = len(keyword)

                    # Skip very short single-word honorifics on person-search queries
                    if is_person_search and keyword in HONORIFICS:
                        continue

                    # Word-boundary match for short keywords (≤6 chars)
                    # Prevents "sir" matching inside "desire" or triggering on "who is sir X"
                    if kw_len <= 6:
                        if not re.search(rf'\b{re.escape(keyword)}\b', query_lower):
                            continue
                        # Even with word boundary, skip if it's just an honorific
                        # and query looks like a name search
                        if keyword in HONORIFICS and is_person_search:
                            continue
                    else:
                        # Longer keywords: simple substring is fine
                        if keyword not in query_lower:
                            continue

                    # This keyword matched — update best if it's the longest match
                    if kw_len > best_score:
                        best_score = kw_len
                        best_match_en = intent.response_template
                        best_match_tl = getattr(intent, 'response_template_tl', None) or None

            if best_match_en is None:
                return None
            # Return Filipino version if lang is tl AND a tl template exists
            if lang == 'tl' and best_match_tl:
                return best_match_tl
            return best_match_en
        except Exception as e:
            print(f"Custom response check error: {e}")
            return None

    def process_query(self, query: str, db: Session, forced_lang: str = None) -> Dict[str, Any]:
        """
        Main RAG pipeline.
        IMPORTANT: entity extraction always uses the ORIGINAL query,
        not the normalized version, so college codes are never lost.
        forced_lang: 'en' or 'tl' from UI selector, overrides auto-detection.
        """
        try:
            original_query = query.strip()

            # Step 0: Language — UI selector ALWAYS wins.
            # If forced_lang is set (from the frontend selector), use it unconditionally.
            # Only auto-detect when no selector choice was made.
            lang = forced_lang if forced_lang else detect_language(original_query)
            print(f"[process_query] forced_lang='{forced_lang}' → lang='{lang}' | query='{original_query[:60]}'")

            # Step 0.4: Direct person lookup — "Who is [Honorific] [FULLNAME]?"
            # Bypasses all intent/scoring logic for exact name queries.
            # Handles: "Who is Dr. VANESSAH V. CASTILLO?"
            #          "Who is Mr. DIONECES O. ALIMOREN?"
            _HONOR_PAT = r'(?:sir|maam|ma[\'`]?am|dr\.?|prof\.?|mr\.?|ms\.?|mrs\.?|engr\.?|atty\.?|asst\.?)'
            _direct_name_pat = (
                rf'(?:who\s+is\s+|about\s+|find\s+|contact\s+)'
                rf'{_HONOR_PAT}\s+'
                rf'([A-Za-z][A-Za-z.\'\\-]{{2,}}(?:\s+[A-Za-z.\'\\-]{{1,}})*)'
            )
            _direct_match = re.search(_direct_name_pat, original_query, re.IGNORECASE)
            if _direct_match:
                _raw_name = re.sub(r'[?.!,]+$', '', _direct_match.group(1).strip())
                _name_words = [
                    w for w in _raw_name.split()
                    if len(re.sub(r'[^a-zA-Z]', '', w)) >= 3
                    and re.sub(r'[^a-zA-Z]', '', w).lower() not in
                        {'dr', 'mr', 'ms', 'mrs', 'prof', 'engr', 'atty', 'sir', 'maam', 'asst', 'the', 'and'}
                ]
                if _name_words:
                    # Try AND (all words must match) then OR (any word)
                    _and_filters = [models.Authority.name.ilike(f'%{w}%') for w in _name_words]
                    _or_filters  = [models.Authority.name.ilike(f'%{w}%') for w in _name_words]
                    _direct_results = db.query(models.Authority).filter(and_(*_and_filters)).all()
                    if not _direct_results and len(_name_words) >= 2:
                        # Try with just the 2 longest words
                        _sorted = sorted(_name_words, key=len, reverse=True)
                        _two_filters = [models.Authority.name.ilike(f'%{w}%') for w in _sorted[:2]]
                        _direct_results = db.query(models.Authority).filter(and_(*_two_filters)).all()
                    if not _direct_results:
                        _direct_results = db.query(models.Authority).filter(or_(*_or_filters)).all()
                    # Validate: keep only results where at least one name word appears
                    _direct_results = [
                        r for r in _direct_results
                        if any(w.lower() in r.name.lower() for w in _name_words)
                    ]
                    if _direct_results:
                        _doc = _direct_results[0]
                        _resp = self.format_authority_response(_doc, original_query, 1.0, [(r, 1.0) for r in _direct_results], lang)
                        return {
                            'response': _resp,
                            'confidence': 1.0,
                            'intent': 'authority_query',
                            'suggestions': [r.name for r in _direct_results[1:4]],
                            'context_used': len(_direct_results),
                            'entities_found': {'first_names': [_raw_name.title()]}
                        }
                    else:
                        # Person not found — return clean fallback immediately
                        _fb = (
                            f"Paumanhin, wala akong impormasyon tungkol kay **{_raw_name.title()}** sa aking database."
                            if lang == 'tl' else
                            f"Sorry, I don't have information about **{_raw_name.title()}** in my database."
                        )
                        return {
                            'response': _fb,
                            'confidence': 1.0,
                            'intent': 'authority_query',
                            'suggestions': [],
                            'context_used': 0,
                            'entities_found': {'first_names': [_raw_name.title()]}
                        }

            # Step 0.45: Direct position-keyword search — "head of ict", "director of ict services"
            # Catches unit-head queries that don't match a college, bypassing scoring noise.
            _pos_kw_pat = r'\b(head|director|chief|coordinator)\s+of\s+([a-zA-Z][a-zA-Z\s]{2,30})'
            _pos_kw_match = re.search(_pos_kw_pat, original_query, re.IGNORECASE)
            if _pos_kw_match:
                _role_kw   = _pos_kw_match.group(1).lower()   # e.g. "head"
                _unit_kw   = _pos_kw_match.group(2).strip()   # e.g. "ict services"
                _unit_kw_clean = re.sub(r'[^a-zA-Z\s]', '', _unit_kw).strip()
                # Only proceed when unit keyword is NOT a college name (colleges are handled later)
                _college_words = {'cet', 'cics', 'cas', 'cabe', 'cte', 'engineering',
                                  'informatics', 'computing', 'accountancy', 'business',
                                  'economics', 'teacher', 'sciences', 'education'}
                _unit_words = [w.lower() for w in _unit_kw_clean.split()]
                _is_college = any(w in _college_words for w in _unit_words)
                if not _is_college and _unit_kw_clean:
                    # Search DB: position must contain the role AND any unit word
                    _unit_filters = [
                        models.Authority.position.ilike(f'%{w}%')
                        for w in _unit_words if len(w) >= 3
                    ]
                    _role_filter = models.Authority.position.ilike(f'%{_role_kw}%')
                    if _unit_filters:
                        _pos_results = (
                            db.query(models.Authority)
                            .filter(_role_filter)
                            .filter(or_(*_unit_filters))
                            .all()
                        )
                        if _pos_results:
                            _doc = _pos_results[0]
                            _resp = self.format_authority_response(
                                _doc, original_query, 1.0,
                                [(r, 1.0) for r in _pos_results], lang
                            )
                            return {
                                'response': _resp,
                                'confidence': 1.0,
                                'intent': 'authority_query',
                                'suggestions': [r.name for r in _pos_results[1:4]],
                                'context_used': len(_pos_results),
                                'entities_found': {}
                            }

            # Step 0.5: Check custom responses FIRST — highest priority
            custom = self.check_custom_response(original_query, db, lang=lang)
            if custom:
                return {
                    'response': custom,
                    'confidence': 1.0,
                    'intent': 'custom_response',
                    'suggestions': [],
                    'context_used': 0,
                    'entities_found': {}
                }


            # Step 0.6: College-number / college-name follow-up handler
            # When user replies "1"..."5" or a college name/code after the dean
            # clarification prompt, map it to a full authority query.
            _CN_MAP = {
                '1':'CET','2':'CAS','3':'CABE','4':'CICS','5':'CTE',
                'one':'CET','two':'CAS','three':'CABE','four':'CICS','five':'CTE',
                'cet':'CET','engineering':'CET','engineering technology':'CET',
                'cics':'CICS','informatics':'CICS','computing':'CICS','computing sciences':'CICS',
                'cas':'CAS','arts':'CAS','arts and sciences':'CAS',
                'cabe':'CABE','accountancy':'CABE','business':'CABE','economics':'CABE',
                'cte':'CTE','teacher':'CTE','education':'CTE','teacher education':'CTE',
            }
            _q_cn = original_query.strip().lower()
            _college_hit = _CN_MAP.get(_q_cn) or next(
                (v for k, v in _CN_MAP.items() if k in _q_cn and len(k) > 2), None
            )
            if _college_hit:
                original_query = f'Who is the dean of {_college_hit}?'
                _q_cn = original_query.lower()

            # Step 0.7: Vague / ambiguous query guard
            # Queries like "what is this", "what", "huh", "this" have no
            # campus-specific substance. Catch them here before intent scoring
            # sends them through the retrieval pipeline and accidentally
            # returns a random DB record.
            _VAGUE_PATTERNS = [
                r"^(what is this|what'?s this|what is that|what'?s that)$",
                r'^(what|huh|hmm|ha|ha\?|idk|idk what|ano ito|ano iyon|ano yan)$',
                r'^(this|that|it|ito|iyon|yan)$',
                r'^(ok|okay|oh|ah|uh|um|err|ahh|ohh)$',
                r'^(and|then|so|but|because|kasi|eh|nga|naman)$',
            ]
            _VAGUE_SHORT_THRESHOLD = 3   # words
            _VAGUE_CHAR_THRESHOLD  = 8   # characters (after strip)

            _q_stripped = original_query.strip().lower()
            _q_words    = _q_stripped.split()
            _is_vague   = any(
                re.search(pat, _q_stripped)
                for pat in _VAGUE_PATTERNS
            )
            # Also flag ultra-short queries with no campus keyword
            if not _is_vague and len(_q_words) <= _VAGUE_SHORT_THRESHOLD and len(_q_stripped) <= _VAGUE_CHAR_THRESHOLD:
                _campus_hints = [
                    'bsu', 'lipa', 'dean', 'room', 'lab', 'org', 'who',
                    'where', 'when', 'chan', 'sets', 'cet', 'cics', 'cas',
                    'cabe', 'cte', 'sino', 'saan', 'ano',
                    '1', '2', '3', '4', '5',
                    'engineering', 'informatics', 'accountancy', 'teacher',
                ]
                # Allow short queries that look like a bare name search:
                # any non-honorific word >=4 letters is treated as a potential surname
                _HONORIFICS_BARE = {'sir', 'maam', 'mam', 'dr', 'mr', 'ms', 'mrs',
                                    'prof', 'engr', 'atty', 'asst'}
                _has_name_word = any(
                    len(re.sub(r'[^a-z]', '', w)) >= 4
                    and re.sub(r'[^a-z]', '', w) not in _HONORIFICS_BARE
                    for w in _q_stripped.split()
                )
                if not any(h in _q_stripped for h in _campus_hints) and not _has_name_word:
                    _is_vague = True

            if _is_vague:
                _vague_en = (
                    "I'm SPARTA, your BSU Lipa campus assistant! 😊 "
                    "I can help you with:\n\n"
                    "**👥 People** — Designated officials\n"
                    "**📍 Locations** — Buildings and rooms\n"
                    "**🏛️ History** — BSU Lipa background\n"
                    "**🎓 Organizations** — Student organizations\n\n"
                    "What would you like to know about the campus?"
                )
                _vague_tl = (
                    "Ako si SPARTA, ang iyong BSU Lipa campus assistant! 😊 "
                    "Maaari kitang tulungan sa:\n\n"
                    "**👥 Mga Tao** — Mga itinalagang opisyal\n"
                    "**📍 Mga Lokasyon** — Mga gusali at silid\n"
                    "**🏛️ Kasaysayan** — BSU Lipa na nakaraan\n"
                    "**🎓 Mga Organisasyon** — Mga estudyanteng organisasyon\n\n"
                    "Ano ang gusto mong malaman tungkol sa kampus?"
                )
                return {
                    'response':       _vague_tl if lang == 'tl' else _vague_en,
                    'confidence':     1.0,
                    'intent':         'general_info',
                    'suggestions':    [],
                    'context_used':   0,
                    'entities_found': {}
                }
            # ── End vague query guard ──────────────────────────────────────────
            # Step 1: Normalize for intent detection only
            normalized_query = self.normalize_query(original_query)

            # Step 2: Intent Detection (on normalized query)
            intent, intent_confidence = self.detect_intent(normalized_query)

            # Step 2.2: Bare-name authority override
            # Handles: "sulit", "maam sulit", "sir garcia", "alimoren",
            #          "maam dela cruz", "prof santos", first-name-only, surname-only.
            # When the entire query is an honorific + name (or just a name),
            # force authority_query so it hits the person DB instead of FAQ.
            _BARE_HONORIFICS = {'sir', 'maam', 'mam', 'dr', 'mr', 'ms', 'mrs',
                                 'prof', 'engr', 'atty', 'asst', 'assoc'}
            _bare_words = [re.sub(r"[^a-z]", '', w)
                           for w in original_query.strip().lower().split()]
            _name_words = [w for w in _bare_words
                           if w and w not in _BARE_HONORIFICS and len(w) >= 2]
            _only_honorific_and_names = (
                len(_bare_words) >= 1
                and all(w in _BARE_HONORIFICS or (len(w) >= 2) for w in _bare_words)
                and _name_words  # at least one non-honorific word
                # query must NOT contain intent keywords that already gave a strong signal
                and intent_confidence < 0.55
                and not any(kw in original_query.lower() for kw in [
                    'where', 'location', 'history', 'org', 'organization',
                    'announcement', 'when', 'founded', 'club', 'building',
                    'room', 'floor', 'saan', 'kailan', 'kasaysayan'
                ])
            )
            if _only_honorific_and_names and intent != 'authority_query':
                print(f"[intent_override] bare-name query '{original_query}' -> authority_query")
                intent = 'authority_query'
                intent_confidence = 0.70

            # Step 2.3: Org acronym / name override
            # Catches queries like "who is SETS", "SETS", "tell me about SETS"
            # NEVER overrides when the query contains a role keyword like "dean of X"
            # because that's clearly an authority query, not an org query.
            _ROLE_KEYWORDS = {
                'dean', 'chancellor', 'president', 'director', 'head',
                'registrar', 'faculty', 'professor', 'coordinator', 'chair',
                'vp', 'vice president', 'officer', 'staff', 'instructor',
                'administrator', 'supervisor', 'manager', 'chief'
            }
            _has_role_kw = any(rk in original_query.lower() for rk in _ROLE_KEYWORDS)

            if intent in ('authority_query', 'general_info', 'history_query') and not _has_role_kw:
                try:
                    _ql_org = original_query.lower().strip()
                    _org_stripped = re.sub(
                        r'^(who is|what is|tell me about|about|sino si|sino ang|'
                        r'ano ang|what are|show me|give me info about|'
                        r'i want to know about|can you tell me about)\s+',
                        '', _ql_org
                    ).strip()
                    _org_stripped = re.sub(r'^(the|ang|si|ni|ng)\s+', '', _org_stripped).strip()

                    if len(_org_stripped) >= 2:
                        _all_orgs = db.query(models.Organization).all()
                        _best_org_score = 0.0
                        for _org in _all_orgs:
                            _oname = (_org.name or '').lower()
                            _owords = _oname.split()
                            _acronym = ''.join(w[0] for w in _owords if w)
                            # Exact acronym match — strongest signal
                            if _org_stripped == _acronym:
                                _best_org_score = 4.0
                                break
                            # Acronym is in the stripped query
                            if _acronym and len(_acronym) >= 3 and _acronym in _org_stripped:
                                _best_org_score = max(_best_org_score, 3.0)
                            # Stripped query is a substring of full org name
                            if len(_org_stripped) > 3 and _org_stripped in _oname:
                                _best_org_score = max(_best_org_score, 2.5)
                            # Any org word (4+ chars) matches whole word in query
                            _qwords = set(_org_stripped.split())
                            for _ow in _owords:
                                if len(_ow) >= 4 and _ow in _qwords:
                                    _best_org_score = max(_best_org_score, 2.0)
                        if _best_org_score >= 2.5:  # raised threshold from 2.0
                            print(f"[intent_override] '{original_query}' -> organization_query "
                                  f"(org score={_best_org_score:.1f})")
                            intent = 'organization_query'
                            intent_confidence = min(0.5 + _best_org_score * 0.1, 0.95)
                except Exception as _oe:
                    print(f"[intent_override] org check failed: {_oe}")

            # Step 2.5: Check if query matches a history title directly.
            # Only runs when intent is NOT already authority/location/org —
            # those have strong signals and should not be overridden.
            # Handles: "Tell me about Development of Campus Facilities" etc.
            SKIP_HISTORY_CHECK = {'authority_query', 'organization_query',
                                  'announcement_query', 'navigation_query'}
            if intent not in SKIP_HISTORY_CHECK:
                try:
                    query_lower = original_query.lower()
                    # Strip common prefixes to isolate the topic phrase
                    stripped_query = re.sub(
                        r'^(tell me about|what is|what was|ano ang|about|'
                        r'kwentuhan mo ako tungkol sa|ibigay mo ang|'
                        r'i want to know about|can you tell me about)\s+',
                        '', query_lower
                    ).strip()

                    # Also strip leading "the " / "bsu lipa " from stripped query
                    stripped_query = re.sub(r'^(the|bsu lipa|bsu|lipa)\s+', '', stripped_query).strip()

                    # Skip history check if query has strong authority signals
                    authority_signals = ['who is', 'who are', 'chancellor', 'dean',
                                        'president', 'vice chancellor', 'head of',
                                        'sino ang', 'sino si']
                    if any(sig in query_lower for sig in authority_signals):
                        pass  # do not override with history
                    elif len(stripped_query) > 3:
                        all_histories = db.query(models.History).all()
                        best_hist_score = 0.0
                        best_hist_intent = None

                        for h in all_histories:
                            title_lower = (h.title or '').lower().strip()
                            if not title_lower:
                                continue

                            # Score 1: direct substring match (highest confidence)
                            if title_lower in stripped_query or stripped_query in title_lower:
                                best_hist_score = 10.0
                                best_hist_intent = 'history_query'
                                break

                            # Score 2: meaningful word overlap
                            # Only count content words (>3 chars, not generic terms)
                            generic = {'lipa', 'bsu', 'campus', 'university',
                                       'program', 'programs', 'the', 'and', 'of'}
                            title_words = [
                                w for w in re.sub(r'[^\w\s]', '', title_lower).split()
                                if len(w) > 3 and w not in generic
                            ]
                            query_words = [
                                w for w in re.sub(r'[^\w\s]', '', stripped_query).split()
                                if len(w) > 3 and w not in generic
                            ]

                            if not title_words or not query_words:
                                continue

                            forward = sum(
                                1 for w in title_words
                                if w in stripped_query or
                                any(w in qw or qw in w
                                    for qw in query_words if len(qw) > 3)
                            )
                            ratio = forward / len(title_words)

                            if ratio > best_hist_score:
                                best_hist_score = ratio
                                if ratio >= 0.6:   # raised threshold
                                    best_hist_intent = 'history_query'

                        if best_hist_intent and best_hist_score >= 0.6:
                            intent = 'history_query'
                            intent_confidence = min(0.5 + best_hist_score * 0.2, 0.95)

                except Exception as e:
                    print(f"[intent] history title check failed: {e}")

            # Step 3: Entity Extraction (on ORIGINAL query — preserves abbreviations)
            entities = self.extract_entities(original_query)

            # Step 4: Context Retrieval (pass original query for scoring)
            context = self.retrieve_context(db, original_query, intent, entities)

            # ── Early exit: no DB results ──────────────────────────────────────
            if not context:
                # Location with no DB match → instant friendly fallback (no Gemini)
                if intent == 'location_query':
                    response = self.generate_fallback_response(intent, original_query, lang)
                    return {
                        'response': response,
                        'confidence': 0.0,
                        'intent': intent,
                        'suggestions': [],
                        'context_used': 0,
                        'entities_found': entities
                    }

                # For all other intents with no DB result, try FAQ chunks directly
                faq_text = retrieve_faq_context(db, original_query)
                if faq_text:
                    if lang == 'tl':
                        faq_header = "📄 **Natagpuan sa FAQ:**\n\n"
                    else:
                        faq_header = "📄 **From the BSU Lipa FAQ:**\n\n"
                    return {
                        'response': faq_header + faq_text,
                        'confidence': 0.55,
                        'intent': intent,
                        'suggestions': [],
                        'context_used': 0,
                        'entities_found': entities
                    }

                response = self.generate_fallback_response(intent, original_query, lang)
                return {
                    'response': response,
                    'confidence': intent_confidence * 0.35,
                    'intent': intent,
                    'suggestions': [],
                    'context_used': 0,
                    'entities_found': entities
                }

            # Step 5: Response Generation
            # Authority: RAG handles photo extraction + clarification logic;
            #            Gemini writes the text body (more natural, multilingual).
            #            If Gemini is unavailable, fall back to pure RAG template.
            # Everything else: Gemini with DB + FAQ context merged.
            if intent == 'authority_query':
                # ── 5a. Let RAG decide if we need a clarification prompt first ──
                rag_response = self.generate_response(
                    original_query, context, intent, intent_confidence, lang,
                    entities=entities
                )

                # Clarification prompts (college selection) must stay as-is —
                # they contain buttons/links that Gemini must never rewrite.
                is_clarification = (
                    "Which college" in rag_response
                    or "Aling kolehiyo" in rag_response
                    or "select a college" in rag_response.lower()
                    or "pumili ng kolehiyo" in rag_response.lower()
                )

                if is_clarification or not GEMINI_ENABLED:
                    response = rag_response
                else:
                    # ── 5b. Extract photo tag produced by RAG (if any) ──────────
                    import re as _re
                    photo_match = _re.search(r'\[PHOTO:[^\]]+\]', rag_response)
                    photo_prefix = photo_match.group(0) if photo_match else ''

                    # ── 5c. Ask Gemini to write the text (no photo in context) ──
                    try:
                        gemini_text = generate_with_gemini(
                            original_query, context, intent, lang
                        )
                    except Exception as _ge:
                        print(f"[authority/gemini] error: {_ge}")
                        gemini_text = None

                    if gemini_text:
                        response = photo_prefix + gemini_text if photo_prefix else gemini_text
                    else:
                        response = rag_response

            elif intent == 'organization_query':
                # Organization: always use RAG formatter for consistent output
                response = self.generate_response(
                    original_query, context, intent, intent_confidence, lang,
                    entities=entities
                )

            elif intent == 'location_query':
                # Location: always use fast RAG template — no Gemini call.
                # Gemini adds 2-3s of latency for a simple "where is X" answer
                # that RAG can answer instantly from DB fields.
                response = self.generate_response(
                    original_query, context, intent, intent_confidence, lang,
                    entities=entities
                )

            elif intent == 'general_info':
                # Pure RAG: search FAQ PDF chunks directly, no LLM needed.
                try:
                    import signal as _signal

                    def _timeout_handler(signum, frame):
                        raise TimeoutError("faq_retriever timeout")

                    _signal.signal(_signal.SIGALRM, _timeout_handler)
                    _signal.alarm(5)
                    try:
                        faq_text = retrieve_faq_context(db, original_query)
                    finally:
                        _signal.alarm(0)

                    if faq_text:
                        formatted = _format_faq_response(faq_text, original_query, lang)
                        if lang == 'tl':
                            header = "📄 **Mula sa BSU Lipa FAQ:**\n\n"
                        else:
                            header = "📄 **From the BSU Lipa FAQ:**\n\n"
                        response = header + formatted
                    else:
                        # Retry with lower threshold for short single-word queries
                        # like "vision", "mission", "tuition"
                        try:
                            faq_text2 = retrieve_faq_context(
                                db, original_query, top_k=2, min_score=0.05
                            )
                            if faq_text2:
                                formatted = _format_faq_response(faq_text2, original_query, lang)
                                header = ("📄 **Mula sa BSU Lipa FAQ:**\n\n"
                                         if lang == 'tl'
                                         else "📄 **From the BSU Lipa FAQ:**\n\n")
                                response = header + formatted
                            else:
                                response = ("Paumanhin, wala akong impormasyon tungkol diyan."
                                           if lang == 'tl'
                                           else "Sorry, I don't have that information in my database.")
                        except Exception:
                            response = ("Paumanhin, wala akong impormasyon tungkol diyan."
                                       if lang == 'tl'
                                       else "Sorry, I don't have that information in my database.")
                except Exception as _faq_err:
                    print(f"[faq] retrieval failed or timed out: {_faq_err}")
                    response = "Sorry, I don't have that information in my database."
            else:
                # history_query, announcement_query, navigation_query
                # All handled by RAG template generator
                response = self.generate_response(
                    original_query, context, intent, intent_confidence, lang,
                    entities=entities
                )

            # Step 6: Confidence
            if context:
                retrieval_confidence = context[0][1]
                overall_confidence = min(
                    intent_confidence * 0.25
                    + retrieval_confidence * 0.65
                    + (0.10 if entities else 0.05),
                    1.0
                )
            else:
                overall_confidence = intent_confidence * 0.35

            # Step 7: Log the search for analytics
            try:
                entity_name = None
                if entities.get('first_names'):
                    entity_name = entities['first_names'][0]
                elif entities.get('locations'):
                    entity_name = entities['locations'][0]
                elif entities.get('departments'):
                    entity_name = entities['departments'][0]
                log_entry = models.SearchLog(
                    query=original_query,
                    intent=intent,
                    entity_name=entity_name,
                    confidence=overall_confidence,
                    language=lang,
                )
                db.add(log_entry)
                db.commit()
            except Exception as log_err:
                print(f"[search_log] non-fatal logging error: {log_err}")

            return {
                'response': response,
                'confidence': overall_confidence,
                'intent': intent,
                'suggestions': [],
                'context_used': len(context),
                'entities_found': entities
            }

        except Exception as e:
            print(f"Error in RAG pipeline: {e}")
            import traceback; traceback.print_exc()
            return {
                'response': (
                    "I apologize, but I encountered an error processing your request. "
                    "Please try rephrasing your question or ask something else about BSU Lipa campus."
                ),
                'confidence': 0.0,
                'intent': 'error',
                'suggestions': [],
                'context_used': 0,
                'entities_found': {}
            }


def _format_faq_response(raw_text: str, query: str, lang: str = 'en') -> str:
    """
    Format raw FAQ chunk text into a clean readable response.
    Handles: Q&A pairs, Core Values sections, Vision/Mission text, plain paragraphs.
    """
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]

    # Remove pure header/title noise lines
    _NOISE = re.compile(
        r'^(vision,?\s*mission|university vision|university mission|'
        r'university core values?|frequently asked|batangas state university|'
        r'don claro|the national engineering|page \d+|\d+\s*of\s*\d+|'
        r'lipa campus|lipa city|leading innovations)\.?$',
        re.IGNORECASE
    )
    lines = [l for l in lines if not _NOISE.match(l)]
    if not lines:
        return raw_text[:600]

    # ── Detect content type ────────────────────────────────────────────────────
    has_qa = any(re.match(r'^Q\s*[\d.:]\s*|^Q:\s*', l, re.IGNORECASE) for l in lines)

    # Core value keywords — ALL CAPS headings like PATRIOTISM, SERVICE, etc.
    _CV_KEYWORDS = {'PATRIOTISM', 'SERVICE', 'INTEGRITY', 'RESILIENCE', 'FAITH',
                    'EXCELLENCE', 'INNOVATION', 'ACCOUNTABILITY', 'TRANSPARENCY'}
    has_core_values = any(l.upper() in _CV_KEYWORDS or
                          any(kw in l.upper() for kw in _CV_KEYWORDS)
                          for l in lines)

    # ── Q&A format ─────────────────────────────────────────────────────────────
    if has_qa:
        result_parts = []
        i = 0
        query_lower = query.lower()
        best_qa = []
        other_qa = []

        while i < len(lines):
            line = lines[i]
            is_q = bool(re.match(r'^Q\s*[\d.:]\s*|^Q:\s*', line, re.IGNORECASE))
            if is_q:
                q_text = re.sub(r'^Q\s*[\d.:]\s*', '', line, flags=re.IGNORECASE).strip()
                answer_lines = []
                i += 1
                while i < len(lines) and not re.match(r'^Q\s*[\d.:]', lines[i], re.IGNORECASE):
                    answer_lines.append(lines[i])
                    i += 1
                answer = ' '.join(answer_lines).strip()
                if answer:
                    q_words   = set(re.findall(r'\w+', q_text.lower()))
                    q_words_a = set(re.findall(r'\w+', answer.lower()))
                    query_words = set(re.findall(r'\w+', query_lower))
                    overlap = len(q_words & query_words) + len(q_words_a & query_words) * 0.3
                    entry = (f"**Q: {q_text}**\n{answer}", overlap)
                    if overlap > 0:
                        best_qa.append(entry)
                    else:
                        other_qa.append(entry)
            else:
                i += 1

        best_qa.sort(key=lambda x: x[1], reverse=True)
        final_parts = [text for text, _ in best_qa[:2]]
        if not final_parts and other_qa:
            final_parts = [other_qa[0][0]]
        return '\n\n'.join(final_parts) if final_parts else '\n'.join(lines[:8])

    # ── Core Values format ─────────────────────────────────────────────────────
    if has_core_values:
        # Parse value name + description pairs
        values_found = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # A core value heading: ALL CAPS, 1-3 words, short
            words = line.split()
            is_value_heading = (
                1 <= len(words) <= 4 and
                line == line.upper() and
                len(line) <= 30 and
                any(kw in line.upper() for kw in _CV_KEYWORDS)
            )
            if is_value_heading:
                desc_lines = []
                i += 1
                while i < len(lines):
                    next_words = lines[i].split()
                    next_is_heading = (
                        1 <= len(next_words) <= 4 and
                        lines[i] == lines[i].upper() and
                        len(lines[i]) <= 30
                    )
                    if next_is_heading:
                        break
                    desc_lines.append(lines[i])
                    i += 1
                desc = ' '.join(desc_lines).strip()
                if desc:
                    values_found.append((line.title(), desc))
            else:
                i += 1

        if values_found:
            query_lower = query.lower()
            # If asking about a specific value, show just that one
            specific = [(name, desc) for name, desc in values_found
                        if name.lower() in query_lower]
            to_show = specific if specific else values_found

            parts = [f"**{name}**\n{desc}" for name, desc in to_show[:5]]
            header = ""
            if 'core value' in query_lower or 'values' in query_lower:
                header = ("🏛️ **Core Values ng BSU Lipa:**\n\n"
                          if lang == 'tl' else
                          "🏛️ **BSU Lipa Core Values:**\n\n")
            return header + '\n\n'.join(parts)

    # ── Plain paragraph text (Vision, Mission, general prose) ─────────────────
    # Check if this is vision/mission content
    is_vision_mission = any(
        kw in ' '.join(lines[:4]).lower()
        for kw in ['vision', 'mission', 'globally recognized', 'holistic development']
    )

    paragraphs = []
    buf = ''
    for line in lines:
        # Skip section labels we'll add ourselves
        if re.match(r'^university\s+(vision|mission|core values?)$', line, re.IGNORECASE):
            if buf:
                paragraphs.append(buf.strip())
                buf = ''
            paragraphs.append(f'**{line.title()}**')
            continue
        if buf and line and line[0].isupper() and buf.rstrip().endswith('.'):
            paragraphs.append(buf.strip())
            buf = line
        elif buf:
            buf = buf + (' ' if not buf.endswith('-') else '') + line
        else:
            buf = line
    if buf:
        paragraphs.append(buf.strip())

    # Limit output length
    result = '\n\n'.join(paragraphs[:5])

    # Add a helpful header for vision/mission queries
    if is_vision_mission:
        query_lower = query.lower()
        if 'vision' in query_lower and 'mission' not in query_lower:
            result = "🎯 **University Vision**\n\n" + result
        elif 'mission' in query_lower and 'vision' not in query_lower:
            result = "🎯 **University Mission**\n\n" + result

    return result


def is_nonsense(message: str) -> bool:
    """
    Detect queries that are nonsense, math expressions, gibberish,
    or completely unrelated to a university — before hitting the RAG pipeline.
    Returns True if the message should get a clean 'not in database' reply.
    """
    msg = message.strip()
    msg_lower = msg.lower()

    # 1. Math / arithmetic expressions  e.g. "1+1", "2*3", "5/2", "sqrt(4)"
    if re.match(r'^[\d\s\+\-\*\/\^\(\)\.\%=]+$', msg):
        return True
    if re.search(r'\d[\+\-\*\/\^]\d', msg):
        return True
    math_words = ['sqrt', 'log(', 'sin(', 'cos(', 'tan(', 'integral', 'derivative',
                  'solve for', 'calculate', 'compute', '= ?', '=?']
    if any(w in msg_lower for w in math_words):
        return True

    # 2. Gibberish — random keyboard smash, no real words
    # Heuristic: if >60% of chars are repeated or no vowel in any 5+ char token
    tokens = re.findall(r'[a-zA-Z]{3,}', msg)
    if tokens:
        no_vowel_count = sum(
            1 for t in tokens
            if not re.search(r'[aeiouAEIOU]', t) and len(t) >= 4
        )
        if no_vowel_count / len(tokens) >= 0.7:
            return True

    # 3. Single/double random characters or symbols with no meaning
    if len(msg) <= 3 and not re.search(r'[a-zA-Z]{2,}', msg):
        return True

    # 4. Repeated character spam  e.g. "aaaaaaa", "hhhhhh", "???"
    if re.match(r'^(.)\1{4,}$', msg):
        return True

    # 5. Pure symbol / emoji / number strings
    if re.match(r'^[\W\d_]+$', msg) and len(msg) < 20:
        return True

    return False


def is_off_topic(message: str) -> bool:
    off_topic_keywords = [
        'weather', 'climate', 'movie', 'film', 'celebrity', 'actor', 'actress',
        'tv show', 'series', 'netflix', 'music', 'song', 'singer', 'band',
        'politics', 'election', 'government', 'congress',
        'nba', 'nfl', 'soccer', 'football', 'basketball',
        'recipe', 'cooking', 'restaurant', 'menu',
        'joke', 'riddle', 'game', 'play', 'lottery',
        'stock price', 'cryptocurrency', 'bitcoin', 'forex',
        'horoscope', 'zodiac', 'astrology',
        'dating', 'relationship advice', 'breakup',
    ]
    message_lower = message.lower()
    if any(kw in message_lower for kw in off_topic_keywords):
        university_terms = ['bsu', 'batangas state', 'university', 'campus',
                            'engineering', 'technology', 'college', 'student',
                            'faculty', 'department', 'lipa']
        if not any(t in message_lower for t in university_terms):
            return True
    return False


def process_chat_with_rag(message: str, db: Session,
                           embedding_model=None,
                           language: str = None) -> Dict[str, Any]:
    """Main entry point for chatbot with RAG."""
    # UI selector takes priority; fallback to auto-detect
    print(f"[language] received='{language}'")
    if language and (language.startswith('tl') or language.startswith('fil')):
        forced_lang = 'tl'
    elif language and language.startswith('en'):
        forced_lang = 'en'
    else:
        forced_lang = None
    print(f"[language] forced_lang='{forced_lang}'")

    if is_nonsense(message):
        lang = forced_lang or detect_language(message)
        no_info_msg = (
            "Paumanhin, wala akong impormasyon tungkol diyan sa aking database. "
            "Magtanong ng tungkol sa BSU Lipa campus!"
            if lang == 'tl' else
            "Sorry, I don't have that information in my database. "
            "Please ask me something about BSU Lipa campus!"
        )
        return {'response': no_info_msg, 'confidence': 1.0, 'intent': 'off_topic', 'suggestions': []}

    if is_off_topic(message):
        lang = forced_lang or detect_language(message)
        if lang == 'tl':
            off_msg = ("Ako si SPARTA, ang iyong BSU Lipa campus assistant. "
                       "Tumutulong lamang ako sa mga tanong tungkol sa aming kampus:\n\n"
                       "**👥 Mga Tao** - Mga itinalagang opisyal\n"
                       "**📍 Mga Lokasyon** - Mga gusali at silid\n"
                       "**🏛️ Kasaysayan** - BSU Lipa na nakaraan\n"
                       "**🎓 Mga Organisasyon** - Mga estudyanteng organisasyon\n\n"
                       "Magtanong ng tungkol sa BSU Lipa campus!")
        else:
            off_msg = ("I'm SPARTA, your BSU Lipa campus assistant. I can only help with questions "
                       "about our campus:\n\n"
                       "**👥 People** - Designated officials\n"
                       "**📍 Locations** - Buildings, rooms, facilities\n"
                       "**🏛️ History** - BSU Lipa background\n"
                       "**🎓 Organizations** - Student organization\n\n"
                       "Please ask me something about BSU Lipa campus!")
        return {'response': off_msg, 'confidence': 1.0, 'intent': 'off_topic', 'suggestions': []}

    # ── Reuse the singleton RAG instance (preserves embedding cache) ──────────
    rag = _get_rag_instance(embedding_model, db)
    return rag.process_query(message, db, forced_lang=forced_lang)


# ── Singleton RAG instance — created once, reused on every request ────────────
_rag_instance: "EnhancedDatabaseRAG" = None

def _get_rag_instance(embedding_model, db: Session) -> "EnhancedDatabaseRAG":
    """
    Return the shared RAG instance, creating and warming it up on first call.
    This ensures the embedding cache is built once at startup and reused forever.
    """
    global _rag_instance
    if _rag_instance is None:
        print("[rag] Creating singleton RAG instance...")
        _rag_instance = EnhancedDatabaseRAG(embedding_model)
        # Pre-load FAQ chunk cache so the first user query doesn't pay the cost
        try:
            from faq_retriever import retrieve_faq_context as _warm_faq
            _warm_faq(db, "vision mission")
            print("[rag] FAQ cache warmed up.")
        except Exception as _we:
            print(f"[rag] FAQ warm-up skipped: {_we}")
        print("[rag] Singleton ready.")
    return _rag_instance


def invalidate_rag_cache(table_name: str, doc_id: int = None) -> None:
    """
    Call this from main.py after any admin add/edit/delete endpoint
    so the embedding cache stays in sync with the database.

    Example in main.py:
        from rag_chatbot import invalidate_rag_cache
        invalidate_rag_cache('authority', authority_id)
    """
    global _rag_instance
    if _rag_instance is not None:
        _rag_instance.invalidate_cache(table_name, doc_id)