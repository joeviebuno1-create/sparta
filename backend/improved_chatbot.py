"""
HIGHLY ACCURATE CHATBOT IMPLEMENTATION FOR SPARTHA
===================================================
This version focuses on precision and returning ONLY the most relevant answer.

KEY IMPROVEMENTS:
1. Stricter filtering - only returns the BEST match
2. Better intent detection with query analysis
3. Smarter data fetching - doesn't mix unrelated data
4. Single-answer focus for specific questions
5. Enhanced keyword matching
"""

from sentence_transformers import SentenceTransformer, util
import re
from typing import List, Dict, Tuple, Optional
from sqlalchemy.orm import Session
import models

# Intent Categories with Enhanced Patterns
INTENT_PATTERNS = {
    'authority_query': {
        'keywords': ['who is', 'dean', 'head', 'director', 'president', 'authority', 'contact', 
                    'email', 'phone', 'office', 'department head', 'faculty', 'staff', 'chairman',
                    'chairperson', 'administrator', 'principal', 'vice president', 'vp'],
        'priority': 'high',
        'exclude_keywords': ['organization', 'org chart', 'structure', 'members']  # Don't confuse with org queries
    },
    'location_query': {
        'keywords': ['where', 'location', 'room', 'building', 'floor', 'find', 'directions',
                    'navigate', 'how to get', 'map'],
        'priority': 'high'
    },
    'history_query': {
        'keywords': ['history', 'when', 'founded', 'established', 'year', 'past', 'historical',
                    'timeline', 'milestone', 'anniversary'],
        'priority': 'medium'
    },
    'announcement_query': {
        'keywords': ['announcement', 'news', 'latest', 'update', 'event', 'happening',
                    'schedule', 'calendar', 'what\'s new', 'recent'],
        'priority': 'high'
    },
    'organization_query': {
        'keywords': ['organization', 'org chart', 'structure', 'department', 'members',
                    'team', 'organizational', 'student org', 'club'],
        'priority': 'medium'
    },
    'general_info': {
        'keywords': ['what', 'tell me about', 'information', 'about', 'explain'],
        'priority': 'low'
    }
}

# Off-topic keywords
OFF_TOPIC_KEYWORDS = [
    'weather', 'climate', 'temperature', 'rain', 'sunny',
    'politics', 'election', 'government', 'senator',
    'sports', 'basketball', 'football', 'games', 'nba',
    'entertainment', 'movie', 'celebrity', 'actor', 'actress',
    'cooking', 'recipe', 'food', 'restaurant',
    'joke', 'funny', 'laugh', 'humor',
]


def is_off_topic(message: str) -> bool:
    """Enhanced off-topic detection"""
    message_lower = message.lower()
    
    if any(keyword in message_lower for keyword in OFF_TOPIC_KEYWORDS):
        return True
    
    university_terms = ['bsu', 'batangas state', 'university', 'campus', 'dean', 
                       'department', 'building', 'room', 'faculty', 'student', 'engineering',
                       'technology', 'college', 'library', 'registrar']
    
    has_university_context = any(term in message_lower for term in university_terms)
    
    if re.search(r'\d+\s*[\+\-\*\/]\s*\d+', message) and not has_university_context:
        return True
    
    return False


def detect_intent(query: str) -> str:
    """Detect the primary intent with enhanced logic"""
    query_lower = query.lower()
    intent_scores = {}
    
    for intent_name, intent_data in INTENT_PATTERNS.items():
        score = 0
        
        # Check for exclude keywords (negative scoring)
        if 'exclude_keywords' in intent_data:
            if any(excl in query_lower for excl in intent_data['exclude_keywords']):
                score -= 10  # Heavy penalty
        
        # Check for intent keywords
        for keyword in intent_data['keywords']:
            if keyword in query_lower:
                # Exact phrase match gets more weight
                if keyword == query_lower:
                    score += 5
                else:
                    score += 2
        
        # Apply priority multiplier
        priority_multiplier = {'high': 1.5, 'medium': 1.0, 'low': 0.5}
        score *= priority_multiplier.get(intent_data['priority'], 1.0)
        
        intent_scores[intent_name] = score
    
    if max(intent_scores.values()) > 0:
        return max(intent_scores, key=intent_scores.get)
    return 'general_info'


def analyze_query_specificity(query: str) -> str:
    """
    Determine if query is asking for ONE specific thing or MULTIPLE things
    Returns: 'specific' or 'broad'
    """
    query_lower = query.lower()
    
    # Indicators of specific queries
    specific_indicators = [
        'who is the',
        'where is the',
        'what is the',
        'only',
        'just',
        'specifically',
        'the dean of',
        'the head of',
        'the director of'
    ]
    
    # Indicators of broad queries
    broad_indicators = [
        'all',
        'list',
        'show me all',
        'what are',
        'tell me about all',
        'every',
        'complete'
    ]
    
    if any(indicator in query_lower for indicator in specific_indicators):
        return 'specific'
    
    if any(indicator in query_lower for indicator in broad_indicators):
        return 'broad'
    
    # Default: if query is short and direct, it's specific
    if len(query.split()) <= 6:
        return 'specific'
    
    return 'broad'


def get_relevant_data(db: Session, query: str, intent: str, specificity: str) -> Dict[str, List]:
    """
    Fetch ONLY relevant data based on intent
    For specific queries, limit data to avoid mixing
    """
    data = {
        'authorities': [],
        'locations': [],
        'histories': [],
        'announcements': [],
        'organizations': [],
        'intents': []
    }
    
    query_lower = query.lower()
    
    # For AUTHORITY queries - ONLY fetch authorities, NOT organizations
    if intent == 'authority_query':
        authorities = db.query(models.Authority).all()
        for auth in authorities:
            # Create detailed searchable text
            search_text = f"{auth.name} {auth.position} {auth.department}".lower()
            
            # Only include if relevant to query
            query_words = query_lower.split()
            relevance = sum(1 for word in query_words if len(word) > 2 and word in search_text)
            
            if relevance > 0 or specificity == 'broad':
                auth_info = {
                    'name': auth.name,
                    'position': auth.position,
                    'department': auth.department,
                    'email': auth.email,
                    'phone': auth.phone,
                    'office_location': auth.office_location,
                    'bio': auth.bio,
                    'text': f"{auth.name} is the {auth.position} of {auth.department} department. "
                           f"Email: {auth.email or 'N/A'}, Phone: {auth.phone or 'N/A'}, "
                           f"Office: {auth.office_location or 'N/A'}",
                    'relevance_score': relevance
                }
                data['authorities'].append(auth_info)
        
        # Sort by relevance
        data['authorities'].sort(key=lambda x: x['relevance_score'], reverse=True)
    
    # For LOCATION queries - ONLY fetch locations
    elif intent == 'location_query':
        locations = db.query(models.RoomLocation).all()
        for loc in locations:
            search_text = f"{loc.name} {loc.building} {loc.type}".lower()
            query_words = query_lower.split()
            relevance = sum(1 for word in query_words if len(word) > 2 and word in search_text)
            
            if relevance > 0 or specificity == 'broad':
                loc_info = {
                    'name': loc.name,
                    'building': loc.building,
                    'floor': loc.floor,
                    'type': loc.type,
                    'capacity': loc.capacity,
                    'description': loc.description,
                    'text': f"{loc.name} is a {loc.type} located in {loc.building}, Floor {loc.floor}. "
                           f"{'Capacity: ' + str(loc.capacity) + ' people. ' if loc.capacity else ''}"
                           f"{loc.description or ''}",
                    'relevance_score': relevance
                }
                data['locations'].append(loc_info)
        
        data['locations'].sort(key=lambda x: x['relevance_score'], reverse=True)
    
    # For HISTORY queries
    elif intent == 'history_query':
        histories = db.query(models.History).all()
        for hist in histories:
            hist_info = {
                'year': hist.year,
                'title': hist.title,
                'description': hist.description,
                'text': f"In {hist.year}, {hist.title}: {hist.description}"
            }
            data['histories'].append(hist_info)
    
    # For ANNOUNCEMENT queries
    elif intent == 'announcement_query':
        announcements = db.query(models.Announcement).order_by(
            models.Announcement.date_posted.desc()
        ).limit(5).all()  # Only top 5 recent
        
        for ann in announcements:
            ann_info = {
                'title': ann.title,
                'content': ann.content,
                'category': ann.category,
                'date': ann.date_posted,
                'text': f"{ann.category} - {ann.title}: {ann.content}"
            }
            data['announcements'].append(ann_info)
    
    # For ORGANIZATION queries - ONLY fetch organizations
    elif intent == 'organization_query':
        organizations = db.query(models.Organization).all()
        for org in organizations:
            members = db.query(models.OrganizationMember).filter(
                models.OrganizationMember.org_chart_id == org.id
            ).order_by(models.OrganizationMember.sort_order).all()
            
            member_list = [{'name': m.name, 'position': m.position} for m in members]
            
            org_info = {
                'name': org.name,
                'description': org.description,
                'members': member_list,
                'text': f"{org.name}: {org.description or ''} " +
                       (f"Members include: " + ", ".join([f"{m['name']} ({m['position']})" 
                        for m in member_list[:5]]) if member_list else "")
            }
            data['organizations'].append(org_info)
    
    # For GENERAL queries - fetch limited data
    else:
        # Only fetch a small amount of each
        authorities = db.query(models.Authority).limit(3).all()
        for auth in authorities:
            data['authorities'].append({
                'name': auth.name,
                'position': auth.position,
                'department': auth.department,
                'text': f"{auth.name} is the {auth.position} of {auth.department}"
            })
    
    # Always check custom intents
    intents = db.query(models.Intent).all()
    for intent_item in intents:
        keywords = [k.strip() for k in intent_item.keywords.split(',')]
        if any(keyword.lower() in query_lower for keyword in keywords):
            data['intents'].append({
                'type': intent_item.intent_type,
                'response': intent_item.response_template,
                'text': intent_item.response_template
            })
    
    return data


def semantic_search_and_rank(query: str, data: Dict[str, List], 
                             embedding_model: SentenceTransformer,
                             specificity: str,
                             top_k: int = 3) -> List[Tuple[str, float, str, dict]]:
    """
    Perform semantic search with STRICT filtering for specific queries
    """
    all_items = []
    
    for category, items in data.items():
        for item in items:
            if item.get('text'):
                all_items.append((item['text'], category, item))
    
    if not all_items:
        return []
    
    texts = [item[0] for item in all_items]
    
    # Encode
    query_embedding = embedding_model.encode(query, convert_to_tensor=True)
    text_embeddings = embedding_model.encode(texts, convert_to_tensor=True)
    
    # Calculate similarities
    similarities = util.pytorch_cos_sim(query_embedding, text_embeddings)[0]
    
    # Create results
    results = []
    for idx, (text, category, original_data) in enumerate(all_items):
        score = float(similarities[idx])
        results.append((text, score, category, original_data))
    
    # Sort by score
    results.sort(key=lambda x: x[1], reverse=True)
    
    # For SPECIFIC queries: Use strict threshold and return only top result if it's good
    if specificity == 'specific':
        threshold = 0.4  # Higher threshold for specific queries
        
        # Filter by threshold
        filtered = [r for r in results if r[1] > threshold]
        
        if filtered:
            # If best result is SIGNIFICANTLY better than second, return only it
            if len(filtered) == 1 or (filtered[0][1] - filtered[1][1] > 0.15):
                return [filtered[0]]  # Return ONLY the best match
            else:
                return filtered[:2]  # Return top 2 if they're close
        return []
    
    # For BROAD queries: Use lower threshold and return more results
    else:
        threshold = 0.25
        return [r for r in results[:top_k] if r[1] > threshold]


def generate_specific_response(query: str, intent: str, specificity: str,
                               ranked_results: List[Tuple[str, float, str, dict]]) -> str:
    """
    Generate a FOCUSED response
    For specific queries: ONE clear answer
    For broad queries: Multiple results
    """
    if not ranked_results:
        return generate_fallback_response(intent)
    
    # Get the best match
    best_match = ranked_results[0]
    category = best_match[2]
    data = best_match[3]
    score = best_match[1]
    
    response = ""
    
    # Generate response based on category
    if category == 'authorities':
        response = f"**{data['name']}** is the **{data['position']}** of the **{data['department']}** department.\n\n"
        if data.get('email'):
            response += f"📧 Email: {data['email']}\n"
        if data.get('phone'):
            response += f"📱 Phone: {data['phone']}\n"
        if data.get('office_location'):
            response += f"🏢 Office: {data['office_location']}\n"
        if data.get('bio') and specificity == 'broad':
            response += f"\n{data['bio']}"
    
    elif category == 'locations':
        response = f"**{data['name']}** is located in **{data['building']}**, Floor {data['floor']}.\n\n"
        response += f"📍 Type: {data['type']}\n"
        if data.get('capacity'):
            response += f"👥 Capacity: {data['capacity']} people\n"
        if data.get('description'):
            response += f"\n{data['description']}"
    
    elif category == 'histories':
        response = f"**{data['title']}** ({data['year']})\n\n"
        response += f"{data['description']}"
    
    elif category == 'announcements':
        response = f"**{data['title']}**\n\n"
        response += f"📂 Category: {data['category']}\n"
        response += f"📅 Posted: {data['date'].strftime('%B %d, %Y') if data.get('date') else 'N/A'}\n\n"
        response += f"{data['content']}"
    
    elif category == 'organizations':
        response = f"**{data['name']}**\n\n"
        if data.get('description'):
            response += f"{data['description']}\n\n"
        if data['members']:
            response += "**Members:**\n"
            for member in data['members']:
                response += f"• {member['name']} - {member['position']}\n"
    
    elif category == 'intents':
        response = data['response']
    
    else:
        response = best_match[0]
    
    # For SPECIFIC queries: Don't add extra info (keep it focused)
    # For BROAD queries: Add related information
    if specificity == 'broad' and len(ranked_results) > 1 and score > 0.4:
        additional = []
        for result in ranked_results[1:3]:
            if result[1] > 0.35:
                additional.append(result)
        
        if additional:
            response += "\n\n**Related Information:**\n"
            for result in additional:
                result_data = result[3]
                if result[2] == 'authorities':
                    response += f"• {result_data['name']} - {result_data['position']}\n"
                elif result[2] == 'locations':
                    response += f"• {result_data['name']} - {result_data['building']}\n"
    
    return response


def generate_fallback_response(intent: str) -> str:
    """Helpful fallback when no data found"""
    fallback_messages = {
        'authority_query': "I couldn't find specific information about that person or position. Try asking with the exact title, like 'Who is the dean of Engineering Technology?' or 'Contact information for the registrar'.",
        'location_query': "I don't have information about that location. Try asking about specific buildings, rooms, or departments.",
        'history_query': "I don't have that historical information. Try asking about major milestones or founding dates.",
        'announcement_query': "I don't have announcements matching that query. Try asking for 'latest announcements' or specific categories.",
        'organization_query': "I couldn't find that organization. Try asking about specific student organizations or departments.",
        'general_info': "I don't have specific information about that. I can help you with:\n• University authorities and contacts\n• Campus locations and buildings\n• University history\n• Latest announcements\n• Organizational structure"
    }
    
    return fallback_messages.get(intent, fallback_messages['general_info'])


def get_follow_up_suggestions(intent: str, query: str, specificity: str) -> List[str]:
    """Generate helpful follow-up suggestions"""
    if specificity == 'specific':
        suggestions = {
            'authority_query': [
                "What are the office hours?",
                "How can I contact them?",
                "Who else is in the department?"
            ],
            'location_query': [
                "How do I get there?",
                "What are the operating hours?",
                "What facilities are available?"
            ],
            'announcement_query': [
                "Are there more announcements?",
                "Show me events this week"
            ]
        }
    else:
        suggestions = {
            'authority_query': [
                "Show me all deans",
                "Who are the department heads?",
                "List all administrators"
            ],
            'location_query': [
                "Show all buildings",
                "List all classrooms",
                "Where are the laboratories?"
            ]
        }
    
    return suggestions.get(intent, [])


def process_chat_message(message: str, db: Session, 
                         embedding_model: SentenceTransformer) -> Dict[str, any]:
    """
    Main function with ENHANCED ACCURACY
    """
    try:
        # Check off-topic
        if is_off_topic(message):
            return {
                'response': "I'm SPARTHA, the BSU Lipa campus assistant. I can only help with questions about our campus, locations, facilities, authorities, history, and announcements. Please ask me something related to BSU Lipa campus.",
                'confidence': 1.0,
                'intent': 'off_topic',
                'suggestions': [
                    "Who is the dean of Engineering?",
                    "Where is the library?",
                    "Show me latest announcements"
                ]
            }
        
        # Detect intent
        intent = detect_intent(message)
        
        # Analyze query specificity
        specificity = analyze_query_specificity(message)
        
        # Get relevant data (ONLY what's needed)
        data = get_relevant_data(db, message, intent, specificity)
        
        # Perform semantic search with strict filtering
        ranked_results = semantic_search_and_rank(
            message, data, embedding_model, specificity, top_k=3
        )
        
        # Generate focused response
        response = generate_specific_response(message, intent, specificity, ranked_results)
        
        # Calculate confidence
        confidence = ranked_results[0][1] if ranked_results else 0.0
        
        # Get suggestions
        suggestions = get_follow_up_suggestions(intent, message, specificity)
        
        return {
            'response': response,
            'confidence': confidence,
            'intent': intent,
            'suggestions': suggestions
        }
        
    except Exception as e:
        print(f"Error in process_chat_message: {e}")
        import traceback
        traceback.print_exc()
        return {
            'response': "I apologize, but I encountered an error. Please try rephrasing your question.",
            'confidence': 0.0,
            'intent': 'error',
            'suggestions': []
        }