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

from sentence_transformers import SentenceTransformer, util
import re
from typing import List, Dict, Tuple, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
import models
from datetime import datetime
import json
import numpy as np
from difflib import SequenceMatcher


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
    m = re.search(r'\b(CET|CICS|CAS|CABE|CTE)\b', q, re.IGNORECASE)
    if m:
        add_code(m.group(1).upper())

    # ── Priority 2: Filipino "ng <abbrev>" e.g. "dean ng CET" ─────────────────
    if not codes:
        m = re.search(r'\bng\s+(CET|CICS|CAS|CABE|CTE)\b', q, re.IGNORECASE)
        if m:
            add_code(m.group(1).upper())

    # ── Priority 3: "of <abbrev>" e.g. "dean of CET" ──────────────────────────
    if not codes:
        m = re.search(r'\bof\s+(CET|CICS|CAS|CABE|CTE)\b', q, re.IGNORECASE)
        if m:
            add_code(m.group(1).upper())

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

    def __init__(self, embedding_model: SentenceTransformer = None):
        self.embedding_model = embedding_model
        self.use_embeddings = embedding_model is not None
        self.context_window_size = 5

        if self.use_embeddings:
            try:
                self.embedding_model.encode("test", convert_to_tensor=False)
                print("Sentence transformer loaded successfully")
            except Exception as e:
                print(f"Sentence transformer test failed: {e}, falling back to keyword matching")
                self.use_embeddings = False
                self.embedding_model = None

        self.intent_config = {
            'authority_query': {
                'keywords': ['who is', 'dean', 'head', 'director', 'president', 'contact',
                             'email', 'phone', 'office', 'authority', 'faculty', 'staff',
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
                             'cashier', 'gymnasium', 'office', 'campus'],
                'question_words': ['where', 'which building', 'what floor', 'saan'],
                'retrieval_strategy': 'spatial_aware',
                'max_results': 5,
                'similarity_threshold': 0.25
            },
            'history_query': {
                'keywords': ['history', 'when', 'founded', 'established', 'year', 'past',
                             'historical', 'timeline', 'milestone', 'origin', 'began',
                             'started', 'created', 'inception', 'background', 'heritage',
                             'legacy', 'tradition', 'evolution'],
                'question_words': ['when', 'what year', 'how long'],
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
            r'\bsaan ang\b': 'where is',
            r'\bano ang\b': 'what is',
            r'\bipaalam\b': 'tell me about',
            r'\bkung sino\b': 'who is',
            r'\bkung saan\b': 'where is',
        }

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
        if not entities['specific_role']:
            # Try with honorific: "who is Dr. Santos", "who is sir Juan"
            title_pat = r"who\s+is\s+(?:sir|dr\.?|prof\.?|mr\.?|ms\.?|mrs\.)\s+([A-Za-z][a-z]{2,}(?:\s+[A-Za-z][a-z]+)*)"
            m = re.search(title_pat, original_query, re.IGNORECASE)
            if m:
                name = m.group(1).strip().title()
                if name not in skip_words:
                    entities['first_names'].append(name)
            else:
                # Plain capitalized name: "who is Juan Dela Cruz"
                plain_pat = r"who\s+is\s+(?:the\s+)?([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)*)"
                m = re.search(plain_pat, original_query)
                if m:
                    name = m.group(1).strip()
                    if name not in skip_words:
                        entities['first_names'].append(name)

        # Other name contexts: contact, find, where is, email, honorific alone
        other_name_pats = [
            r"contact\s+(?:sir\s+|dr\.?\s+|prof\.?\s+|mr\.?\s+|ms\.?\s+|mrs\.?\s+)?([A-Z][a-z]+)",
            r"about\s+(?:sir\s+|dr\.?\s+|prof\.?\s+|mr\.?\s+|ms\.?\s+|mrs\.?\s+)?([A-Z][a-z]+)",
            r"find\s+(?:sir\s+|dr\.?\s+|prof\.?\s+|mr\.?\s+|ms\.?\s+|mrs\.?\s+)?([A-Z][a-z]+)",
            r"where\s+is\s+(?:sir\s+|dr\.?\s+|prof\.?\s+|mr\.?\s+|ms\.?\s+|mrs\.?\s+)?([A-Z][a-z]+)",
            r"email\s+of\s+(?:sir\s+|dr\.?\s+|prof\.?\s+|mr\.?\s+|ms\.?\s+|mrs\.?\s+)?([A-Z][a-z]+)",
            r"(?:sir|dr\.?|prof\.?|mr\.?|ms\.?|mrs\.)\s+([A-Z][a-z]+)",
        ]
        for pat in other_name_pats:
            for match in re.findall(pat, original_query, re.IGNORECASE):
                name = match.strip().title()
                if len(name) > 2 and name not in skip_words:
                    entities['first_names'].append(name)

        # Full capitalized names (fallback)
        potential_names = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', original_query)
        entities['person_names'] = [n for n in potential_names
                                     if len(n) > 2 and n not in skip_words]

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

        use_embeddings = (self.embedding_model is not None) and (not strong_entity_query)
        if use_embeddings:
            try:
                query_embedding = self.embedding_model.encode(
                    original_query, convert_to_tensor=True
                )
            except Exception as e:
                print(f"Embedding error: {e}")
                use_embeddings = False

        scored_docs = []

        for doc in documents:
            doc_text = self._doc_to_text(doc, intent)

            semantic_score = 0.0
            if use_embeddings:
                try:
                    doc_emb = self.embedding_model.encode(doc_text, convert_to_tensor=True)
                    semantic_score = float(util.cos_sim(query_embedding, doc_emb)[0][0])
                except Exception:
                    semantic_score = 0.0

            keyword_score = self._calculate_keyword_overlap(original_query, doc_text)
            fuzzy_score = self._calculate_fuzzy_match(original_query, doc, entities, intent)
            entity_score = self._calculate_entity_match(entities, doc, intent)

            if strong_entity_query:
                # Pure entity/keyword mode — fast, accurate, no semantic noise
                combined = (keyword_score * 0.25 + fuzzy_score * 0.25
                            + entity_score * 0.50)
            elif use_embeddings:
                combined = (semantic_score * 0.40 + keyword_score * 0.25
                            + fuzzy_score * 0.20 + entity_score * 0.15)
            else:
                combined = (keyword_score * 0.40 + fuzzy_score * 0.30
                            + entity_score * 0.30)

            if combined >= threshold:
                # Penalize emergency exits — they should never surface as a primary result
                if hasattr(doc, 'name') and 'emergency' in doc.name.lower():
                    combined = -1.0
                scored_docs.append((doc, combined))

        scored_docs.sort(key=lambda x: x[1], reverse=True)

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

                # ── First name search (highest priority) ───────────────────
                if entities.get('first_names'):
                    name_filters = []
                    for first_name in entities['first_names']:
                        name_filters += [
                            models.Authority.name.ilike(f'{first_name}%'),
                            models.Authority.name.ilike(f'% {first_name} %'),
                            models.Authority.name.ilike(f'% {first_name}'),
                            models.Authority.name.ilike(f'%. {first_name}%'),
                        ]
                    query = query.filter(or_(*name_filters))
                    results = query.all()
                    if not results:
                        # Partial fallback
                        partial = [
                            models.Authority.name.ilike(f'%{fn}%')
                            for fn in entities['first_names']
                        ]
                        results = db.query(models.Authority).filter(or_(*partial)).all()
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

                if all_dept_terms:
                    dept_conditions = [
                        models.Authority.department.ilike(f'%{term}%')
                        for term in all_dept_terms
                    ]
                    query = query.filter(or_(*dept_conditions))

                return query.all()

            elif intent == 'location_query':
                query = db.query(models.RoomLocation).filter(
                    ~models.RoomLocation.name.ilike('%emergency exit%'),
                    ~models.RoomLocation.name.ilike('%emergency%exit%'),
                    ~models.RoomLocation.type.ilike('%emergency%'),
                )
                if entities.get('locations'):
                    # Expand location aliases — library → also search LRC
                    location_alias_map = {
                        'library': ['library', 'lrc', 'learning resource center', 'learning resource'],
                        'lrc': ['library', 'lrc', 'learning resource center'],
                        'learning resource center': ['library', 'lrc', 'learning resource center'],
                        'gym': ['gym', 'gymnasium', 'sports', 'physical education'],
                        'gymnasium': ['gym', 'gymnasium'],
                        'canteen': ['canteen', 'cafeteria', 'food', 'dining'],
                        'cafeteria': ['canteen', 'cafeteria', 'dining'],
                        'clinic': ['clinic', 'health', 'medical', 'infirmary'],
                        'chapel': ['chapel', 'church', 'prayer'],
                        'registrar': ['registrar', 'registration', 'enrollment'],
                        'cashier': ['cashier', 'payment', 'finance'],
                    }
                    all_search_terms = []
                    for loc in entities['locations']:
                        loc_lower = loc.lower().strip()
                        aliases = location_alias_map.get(loc_lower, [loc_lower])
                        all_search_terms.extend(aliases)

                    # Remove duplicates
                    all_search_terms = list(set(all_search_terms))

                    loc_filters = [
                        or_(
                            models.RoomLocation.name.ilike(f'%{term}%'),
                            models.RoomLocation.building.ilike(f'%{term}%'),
                            models.RoomLocation.description.ilike(f'%{term}%') if hasattr(models.RoomLocation, 'description') else models.RoomLocation.name.ilike(f'%{term}%'),
                        )
                        for term in all_search_terms
                    ]
                    query = query.filter(or_(*loc_filters))
                if entities.get('room_numbers'):
                    room_filters = [
                        models.RoomLocation.name.ilike(f'%{r}%')
                        for r in entities['room_numbers']
                    ]
                    query = query.filter(or_(*room_filters))

                results = query.all()

                # Fallback — if no results, search using significant words from query
                if not results:
                    query_words = [
                        w for w in original_query.lower().split()
                        if len(w) > 3 and w not in
                        {'where', 'what', 'find', 'show', 'tell', 'about',
                         'is', 'the', 'are', 'how', 'get', 'to', 'me', 'can',
                         'you', 'please', 'i', 'want', 'know', 'look', 'for'}
                    ]
                    if query_words:
                        fallback_filters = [
                            or_(
                                models.RoomLocation.name.ilike(f'%{w}%'),
                                models.RoomLocation.building.ilike(f'%{w}%'),
                            )
                            for w in query_words
                        ]
                        results = db.query(models.RoomLocation).filter(
                            ~models.RoomLocation.name.ilike('%emergency%'),
                            or_(*fallback_filters)
                        ).all()

                return results

            elif intent == 'history_query':
                return db.query(models.History).order_by(models.History.year).all()

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
            for first_name in entities['first_names']:
                dn = doc.name.lower()
                fn = first_name.lower()
                if dn.startswith(fn + ' ') or (' ' + fn) in dn:
                    max_score = max(max_score, 0.95)
                else:
                    parts = doc.name.split()
                    if parts:
                        score = self.fuzzy_match_score(first_name, parts[0])
                        if score > 0.8:
                            max_score = max(max_score, score * 0.9)

        if entities.get('person_names') and hasattr(doc, 'name'):
            for name in entities['person_names']:
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
                and not has_first_name
                and len(context) > 1):
            return True
        return False

    def generate_department_selection(self, specific_role: str = 'dean', lang: str = 'en') -> str:
        role_title = specific_role.title() if specific_role else 'Dean'
        if lang == 'tl':
            response = f"**Aling kolehiyo ang {role_title} ang gusto mong malaman?**\n\n"
        else:
            response = f"**Which college {role_title} would you like to know about?**\n\n"
        response += "**1.** College of Engineering Technology (CET)\n"
        response += "**2.** College of Informatics and Computing Sciences (CICS)\n"
        response += "**3.** College of Arts and Sciences (CAS)\n"
        response += "**4.** College of Accountancy, Business, and Economics (CABE)\n"
        response += "**5.** College of Teacher Education (CTE)"
        return response

    def generate_response(self, original_query: str,
                          context: List[Tuple[Any, float]],
                          intent: str, intent_confidence: float,
                          lang: str = 'en') -> str:
        """
        Generate response. Always uses original_query for entity re-extraction
        so department info is not lost.
        """
        # Always extract entities from the ORIGINAL query
        entities = self.extract_entities(original_query)

        # Clarification check
        if intent == 'authority_query' and self.needs_department_clarification(
                original_query, entities, context):
            return self.generate_department_selection(entities.get('specific_role', 'dean'), lang)

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

        if lang == 'tl':
            response = f"Ang **{position}** ng **{department}** ay si **{name}**. 😊\n\n"
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
        response = f"The **{position}** of **{department}** is **{name}**. 😊\n\n"

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
        if lang == 'tl':
            return (f"Narito ang isang bahagi ng kasaysayan ng BSU Lipa! 🏛️\n\n"
                    f"**{doc.year} — {doc.title}**\n\n{doc.description}\n\n"
                    f"Gusto mo bang malaman ang higit pa tungkol sa kasaysayan ng unibersidad?")
        return (
            f"Here's a piece of BSU Lipa's history! 🏛️\n\n"
            f"**{doc.year} — {doc.title}**\n\n"
            f"{doc.description}\n\n"
            f"Would you like to know more about the university's history or milestones?"
        )

    def format_announcement_response(self, doc: Any, query: str, score: float, lang: str = 'en') -> str:
        date_str = doc.date_posted.strftime('%B %d, %Y') if doc.date_posted else ('Kamakailan' if lang == 'tl' else 'Recently')
        if lang == 'tl':
            r = f"Narito ang pinakabagong balita! 📢\n\n**{doc.title}**\n"
            r += f"🗓️ Nai-post noong {date_str} · 🏷️ {doc.category}\n\n{doc.content}\n\n"
            r += "Gusto mo bang makita ang higit pang mga anunsyo?"
            return r
        response = f"Here's the latest on that! 📢\n\n"
        response += f"**{doc.title}**\n"
        response += f"🗓️ Posted on {date_str} · 🏷️ {doc.category}\n\n"
        response += f"{doc.content}\n\n"
        response += "Would you like to see more announcements or news?"
        return response

    def format_announcement_list(self, context: List[Tuple[Any, float]], lang: str = 'en') -> str:
        if lang == 'tl':
            response = f"Narito ang mga pinakabagong anunsyo mula sa BSU Lipa! 📢\n\n"
            for doc, score in context:
                d = doc.date_posted.strftime('%B %d, %Y') if doc.date_posted else 'Kamakailan'
                response += f"📅 **{d}** · {doc.category}\n**{doc.title}**\n\n"
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
                return (
                    "📋 **Hindi ko ma-listahan ang lahat ng opisyal ngayon.**\n\n"
                    "Maaaring walang datos sa database pa. Subukan ang:\n\n"
                    "• *'Sino ang dekano ng CET?'*\n"
                    "• *'Sino ang chancellor ng BSU Lipa?'*\n"
                    "• *'Sino ang presidente ng unibersidad?'*\n\n"
                    "O mag-click sa mga quick questions sa ibaba! 👇"
                )
            return (
                "📋 **I wasn't able to list all university officials right now.**\n\n"
                "The database may not have officials added yet. Try asking about a specific person instead:\n\n"
                "• *'Who is the dean of CET?'*\n"
                "• *'Who is the chancellor of BSU Lipa?'*\n"
                "• *'Who is the university president?'*\n\n"
                "Or use the quick question buttons below! 👇"
            )

        if lang == 'tl':
            tl_fb = {
                'authority_query': "Hindi ko mahanap ang taong iyon o posisyon. 🤔\n\nSubukan ang buong titulo tulad ng *'Dekano ng CET'*, o tanungin ang *'Sino ang mga opisyal?'*",
                'location_query': "Wala akong impormasyon tungkol sa lokasyong iyon. 📍\n\nGamitin ang **Campus Navigator** para sa interactive na mapa ng kampus!",
                'history_query': "Wala akong ganoong kasaysayan. 🏛️\n\nSubukan ang pagtatanong tungkol sa pagkakatatag ng unibersidad!",
                'announcement_query': "Walang anunsyo na tumutugma. 📢\n\nSubukan ang *'mga pinakabagong anunsyo'*!",
                'organization_query': "Hindi ko mahanap ang organisasyong iyon. 🎓\n\nSubukan ang *'Listahan ng lahat ng organisasyon'*!",
                'navigation_query': "Gamitin ang **Campus Navigator** para sa detalyadong navigasyon! 🗺️",
                'general_info': "Ako si SPARTHA, ang iyong BSU Lipa campus assistant! 😊\n\n**👥 Mga Tao** - Guro, kawani, administrador\n**📍 Mga Lokasyon** - Gusali, silid, pasilidad\n**🏛️ Kasaysayan** - Timeline at mahahalagang pangyayari\n**📢 Mga Anunsyo** - Pinakabagong balita\n**🎓 Mga Organisasyon** - Mga estudyanteng grupo\n\nAno ang gusto mong malaman?",
            }
            return tl_fb.get(intent, tl_fb['general_info'])
        fallbacks = {
            'authority_query': (
                "Hmm, I wasn't able to find that person or position in my records. 🤔\n\n"
                "Try asking with the full official title like *'Dean of College of Engineering Technology'*, "
                "or ask *'Who are the university officials?'* to see everyone!"
            ),
            'location_query': (
                "I don't have information about that specific location. 📍 What other location would you like to know about?\n\n"
                "You can also use the **Campus Navigator** for detailed directions and an interactive map of the entire campus!"
            ),
            'history_query': (
                "I don't have that specific historical record. 🏛️\n\n"
                "Try asking about the university's founding, major milestones, or a specific year!"
            ),
            'announcement_query': (
                "I couldn't find any announcements matching that. 📢\n\n"
                "Try asking for *'latest announcements'* to see what's new on campus!"
            ),
            'organization_query': (
                "I couldn't find that organization. 🎓\n\n"
                "Try asking *'List all organizations'* to see everything available!"
            ),
            'navigation_query': (
                "For detailed navigation, please use the **Campus Navigator** for an interactive 3D map! 🗺️\n\n"
                "You can also ask me about specific locations like *'Where is the library?'*"
            ),
            'general_info': (
                "I'm SPARTHA, your BSU Lipa campus assistant! 😊 Here's what I can help you with:\n\n"
                "**👥 People** - Faculty, staff, and administrators\n"
                "**📍 Locations** - Buildings, rooms, and facilities\n"
                "**🏛️ History** - University timeline and milestones\n"
                "**📢 Announcements** - Latest news and events\n"
                "**🎓 Organizations** - Student groups and departments\n\n"
                "What would you like to know?"
            ),
        }
        return fallbacks.get(intent, fallbacks['general_info'])

    def check_custom_response(self, query: str, db: Session) -> Optional[str]:
        """
        Check the intents table for a matching custom response FIRST.
        Keywords field is comma-separated e.g. 'enrollment, how to enroll'.
        Returns the response_template if matched, else None.
        """
        try:
            intents = db.query(models.Intent).all()
            query_lower = query.lower()
            best_match = None
            best_score = 0
            for intent in intents:
                if not intent.keywords or not intent.response_template:
                    continue
                keywords = [k.strip().lower() for k in intent.keywords.split(',') if k.strip()]
                for keyword in keywords:
                    if keyword in query_lower and len(keyword) > best_score:
                        best_score = len(keyword)
                        best_match = intent.response_template
            return best_match
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

            # Step 0: Language — UI selector takes priority, else auto-detect
            lang = forced_lang if forced_lang else detect_language(original_query)

            # Step 0.5: Check custom responses FIRST — highest priority
            custom = self.check_custom_response(original_query, db)
            if custom:
                return {
                    'response': custom,
                    'confidence': 1.0,
                    'intent': 'custom_response',
                    'suggestions': [],
                    'context_used': 0,
                    'entities_found': {}
                }

            # Step 1: Normalize for intent detection only
            normalized_query = self.normalize_query(original_query)

            # Step 2: Intent Detection (on normalized query)
            intent, intent_confidence = self.detect_intent(normalized_query)

            # Step 3: Entity Extraction (on ORIGINAL query — preserves abbreviations)
            entities = self.extract_entities(original_query)

            # Step 4: Context Retrieval (pass original query for scoring)
            context = self.retrieve_context(db, original_query, intent, entities)

            # Step 5: Response Generation (pass original query)
            response = self.generate_response(original_query, context, intent, intent_confidence, lang)

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


def is_off_topic(message: str) -> bool:
    off_topic_keywords = [
        'weather', 'climate', 'movie', 'film', 'celebrity', 'actor', 'actress',
        'tv show', 'series', 'netflix', 'music', 'song', 'singer', 'band',
        'politics', 'election', 'president of', 'government', 'congress',
        'nba', 'nfl', 'soccer', 'football', 'basketball',
        'recipe', 'cooking', 'restaurant', 'menu',
        'joke', 'riddle', 'game', 'play', 'lottery'
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
                           embedding_model: SentenceTransformer = None,
                           language: str = None) -> Dict[str, Any]:
    """Main entry point for chatbot with RAG."""
    # UI selector takes priority; fallback to auto-detect
    print(f"[language] received='{language}'")
    if language and language.startswith('tl'):
        forced_lang = 'tl'
    elif language and language.startswith('en'):
        forced_lang = 'en'
    else:
        forced_lang = None
    print(f"[language] forced_lang='{forced_lang}'")

    if is_off_topic(message):
        lang = forced_lang or detect_language(message)
        if lang == 'tl':
            off_msg = ("Ako si SPARTHA, ang iyong BSU Lipa campus assistant. "
                       "Tumutulong lamang ako sa mga tanong tungkol sa aming kampus:\n\n"
                       "**👥 Mga Tao** - Pangalan ng Guro, kawani, mga administrador\n"
                       "**📍 Mga Lokasyon** - Mga gusali, silid, pasilidad\n"
                       "**🏛️ Kasaysayan** - Timeline at mahahalagang pangyayari\n"
                       "**📢 Mga Anunsyo** - Pinakabagong balita at kaganapan\n"
                       "**🎓 Mga Organisasyon** - Mga estudyanteng grupo\n\n"
                       "Magtanong ng tungkol sa BSU Lipa campus!")
        else:
            off_msg = ("I'm SPARTHA, your BSU Lipa campus assistant. I can only help with questions "
                       "about our campus:\n\n"
                       "**👥 People** - Name of the dean, faculty, staff, administrators\n"
                       "**📍 Locations** - Buildings, rooms, facilities\n"
                       "**🏛️ History** - University timeline and milestones\n"
                       "**📢 Announcements** - Latest news and events\n"
                       "**🎓 Organizations** - Student groups and departments\n\n"
                       "Please ask me something about BSU Lipa campus!")
        return {'response': off_msg, 'confidence': 1.0, 'intent': 'off_topic', 'suggestions': []}

    rag = EnhancedDatabaseRAG(embedding_model)
    return rag.process_query(message, db, forced_lang=forced_lang)