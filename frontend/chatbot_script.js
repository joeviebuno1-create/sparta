// ============ GLOBAL API HOST ============
const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const CHAT_API_URL = isLocal
    ? `http://localhost:8000/api/chat`
    : `https://sparta-production-0acb.up.railway.app/api/chat`;


document.addEventListener('DOMContentLoaded', function() {

const chatMessages = document.getElementById('chatMessages');
    const userInput = document.getElementById('userInput');
    const typingIndicator = document.getElementById('typingIndicator');
    const langSelect = document.getElementById('langSelect');
    const micBtn = document.getElementById('micBtn');
    const sendBtn = document.getElementById('sendBtn');
    const quickQuestionsContainer = document.getElementById('quickQuestionsContainer');

    // Conversation context for dynamic questions
    let conversationHistory = [];
    let lastIntent = null;
    let isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

    // Mobile-specific: Prevent scroll when typing
    if (isMobile) {
        userInput.addEventListener('focus', () => {
            setTimeout(() => {
                window.scrollTo(0, 0);
                document.body.scrollTop = 0;
            }, 300);
        });
    }

    // Mobile-specific: Better scrolling for quick questions
    if (isMobile) {
        let isScrolling = false;
        quickQuestionsContainer.addEventListener('touchstart', () => {
            isScrolling = false;
        });
        
        quickQuestionsContainer.addEventListener('touchmove', () => {
            isScrolling = true;
        });
        
        quickQuestionsContainer.addEventListener('touchend', (e) => {
            if (isScrolling) {
                e.preventDefault();
            }
        });
    }

    // ── Two hardcoded sets that never change ──────────────────────────────────

    // 1) Startup — always shown on first load (Image 1)
    const STARTUP_QUESTIONS = [
        { text: '🎓 Who is the dean?',          query: 'Who is the dean?' },
        { text: '🏛️ Who is the Chancellor?',    query: 'Who is the chancellor of BSU Lipa?' },
        { text: '📍 Where is the speech lab?',  query: 'Where is the speech lab?' },
        { text: '🏆 Tell me about SETS org',    query: 'Tell me about SETS organization' },
        { text: '🏛️ University history',        query: 'Tell me about BSU Lipa history' }
    ];

    // 2) College dean picker — shown when chatbot asks which college (Image 2)
    const COLLEGE_PICKER_QUESTIONS = [
        { text: '🏗️ CET Dean',   query: 'Who is the dean of College of Engineering Technology?' },
        { text: '💻 CICS Dean',  query: 'Who is the dean of College of Informatics and Computing Sciences?' },
        { text: '🎨 CAS Dean',   query: 'Who is the dean of College of Arts and Sciences?' },
        { text: '💼 CABE Dean',  query: 'Who is the dean of College of Accountancy Business and Economics?' },
        { text: '👨‍🏫 CTE Dean', query: 'Who is the dean of College of Teacher Education?' }
    ];

    // ── Helpers ───────────────────────────────────────────────────────────────

    function getApiBase() {
        const isDevTunnel = (
            window.location.hostname.includes('devtunnels.ms') ||
            window.location.hostname.includes('app.github.dev') ||
            window.location.hostname.includes('trycloudflare.com') ||
            window.location.hostname.includes('ngrok-free.app') ||
            window.location.hostname.includes('ngrok.io')
        );
        return isDevTunnel
            ? `${window.location.protocol}//${window.location.hostname}`
            : `${window.location.protocol}//${window.location.hostname}:8000`;
    }

    // Render a list of {text, query} objects into the container
    function renderQuickQuestions(questions) {
        quickQuestionsContainer.innerHTML = '';
        if (!questions || questions.length === 0) return;
        questions.forEach(q => {
            const btn = document.createElement('button');
            btn.className = 'quick-question-btn';
            btn.textContent = q.text;
            btn.onclick = () => sendQuickQuestion(q.query);
            quickQuestionsContainer.appendChild(btn);
        });
    }

    // Render a small divider label inline between sections
    function renderSectionDivider(label) {
        const div = document.createElement('div');
        div.className = 'quick-questions-divider';
        div.textContent = label;
        quickQuestionsContainer.appendChild(div);
    }

    // Fetch from DB and render; primary questions first, then "Explore more" section
    async function loadDynamicQuestions(intent) {
        try {
            const res = await fetch(`${getApiBase()}/api/quick-questions?intent=${encodeURIComponent(intent)}`);
            if (!res.ok) return;
            const data = await res.json();

            // New API shape: { primary: [...], explore: [...] }
            // Legacy flat-array shape: [...] — handle both
            const primary = Array.isArray(data) ? data : (data.primary || []);
            const explore  = Array.isArray(data) ? [] : (data.explore  || []);

            quickQuestionsContainer.innerHTML = '';

            if (primary.length > 0) renderQuickQuestions(primary);

            if (explore.length > 0) {
                renderSectionDivider('✦ Explore more');
                // append explore buttons without clearing
                explore.forEach(q => {
                    const btn = document.createElement('button');
                    btn.className = 'quick-question-btn';
                    btn.textContent = q.text;
                    btn.onclick = () => sendQuickQuestion(q.query);
                    quickQuestionsContainer.appendChild(btn);
                });
            }
        } catch (e) {
            console.warn('[quick-questions] DB fetch failed:', e.message);
            // Silently fall back to startup questions
            renderQuickQuestions(STARTUP_QUESTIONS);
        }
    }

    // Detect college-picker prompt from bot response text
    function isCollegePickerResponse(text) {
        return text &&
            (text.includes('What specific department') ||
             text.includes('Which college') ||
             text.includes('Which college Dean') ||
             text.includes('Which college Head')) &&
            text.includes('CET') && text.includes('CICS');
    }

    // Main entry point — decides which set to show and animates transition
    function updateQuickQuestions(intent = 'general_info', responseText = '', isStartup = false) {
        // Animate out
        quickQuestionsContainer.style.opacity = '0';
        quickQuestionsContainer.style.transform = 'translateY(10px)';

        setTimeout(async () => {
            if (isStartup) {
                // ── Case 1: page load → fixed startup set ─────────────
                renderQuickQuestions(STARTUP_QUESTIONS);

            } else if (isCollegePickerResponse(responseText)) {
                // ── Case 2: chatbot asked which college → fixed picker ─
                renderQuickQuestions(COLLEGE_PICKER_QUESTIONS);

            } else {
                // ── Case 3: all other responses → fully from DB ────────
                await loadDynamicQuestions(intent);
            }

            // Animate in
            quickQuestionsContainer.style.opacity = '1';
            quickQuestionsContainer.style.transform = 'translateY(0)';
        }, 300);
    }

    // Enter key to send
    userInput.addEventListener('keypress', e => {
        if (e.key === 'Enter') {
            e.preventDefault(); // Prevent default on mobile
            sendMessage();
        }
    });

    // Mobile: Handle virtual keyboard
    if (isMobile) {
        // Prevent page zoom on double-tap
        let lastTouchEnd = 0;
        document.addEventListener('touchend', (e) => {
            const now = Date.now();
            if (now - lastTouchEnd <= 300) {
                e.preventDefault();
            }
            lastTouchEnd = now;
        }, { passive: false });

        // Handle keyboard show/hide
        window.visualViewport?.addEventListener('resize', () => {
            const viewportHeight = window.visualViewport.height;
            document.documentElement.style.setProperty('--viewport-height', `${viewportHeight}px`);
        });
    }

    // Focus input on load
    window.addEventListener('load', () => {
        userInput.focus();
    });

    // Quick question handler
    function sendQuickQuestion(question) {
        userInput.value = question;
        sendMessage();
    }

    // ── Typo / spelling corrector ─────────────────────────────────────────────
    const TYPO_MAP = {
        // Common misspellings & shorthand
        'wher': 'where', 'wehre': 'where', 'whre': 'where', 'wher is': 'where is',
        'waht': 'what', 'whta': 'what', 'wath': 'what',
        'hos': 'who is', 'hwo': 'who', 'woh': 'who',
        'teh': 'the', 'hte': 'the', 'tthe': 'the',
        'is teh': 'is the', 'of teh': 'of the',
        'dena': 'dean', 'deam': 'dean', 'den': 'dean',
        'chanclor': 'chancellor', 'chancelor': 'chancellor', 'chncellor': 'chancellor',
        'presiednt': 'president', 'prsident': 'president', 'presedent': 'president',
        'universtiy': 'university', 'univeristy': 'university', 'univerisity': 'university',
        'buldng': 'building', 'buldging': 'building', 'bilding': 'building',
        'locaton': 'location', 'loction': 'location', 'lcation': 'location',
        'anouncement': 'announcement', 'announcment': 'announcement', 'announcemnt': 'announcement',
        'histroy': 'history', 'hisory': 'history', 'hsitory': 'history',
        'organizaton': 'organization', 'oragnization': 'organization', 'organziation': 'organization',
        'labratory': 'laboratory', 'labrotary': 'laboratory', 'labortory': 'laboratory',
        'libray': 'library', 'libraary': 'library', 'liberry': 'library',
        'clasroom': 'classroom', 'classroon': 'classroom', 'claassroom': 'classroom',
        'ofice': 'office', 'offce': 'office', 'offise': 'office',
        'teachr': 'teacher', 'teahcer': 'teacher', 'taecher': 'teacher',
        'studennt': 'student', 'stduent': 'student', 'studnt': 'student',
        'colege': 'college', 'collge': 'college', 'colleje': 'college',
        'departmnt': 'department', 'departement': 'department', 'deparment': 'department',
        'faculy': 'faculty', 'facuty': 'faculty', 'faculity': 'faculty',
        'adminstration': 'administration', 'adminitration': 'administration',
        'evnt': 'event', 'eevnt': 'event',
        'schedul': 'schedule', 'shedule': 'schedule', 'scheudle': 'schedule',
        'abt': 'about', 'abut': 'about',
        'pls': 'please', 'plss': 'please', 'plz': 'please',
        'wat': 'what', 'wen': 'when', 'hw': 'how', 'cud': 'could', 'wud': 'would',
        'ur': 'your', 'u': 'you', 'r': 'are', 'n': 'and', 'nd': 'and',
        'gud': 'good', 'gd': 'good', 'gr8': 'great',
        'spceh': 'speech', 'sepeach': 'speech',
        'cancellor': 'chancellor', 'chacellor': 'chancellor',
        'founed': 'founded', 'fouded': 'founded', 'fonded': 'founded',
        'bsu lipa': 'BSU Lipa', 'bsu': 'BSU',
        'sparta': 'SPARTA',
        // Additional common typos
        'wen is': 'when is', 'hwen': 'when', 'whn': 'when',
        'annoucement': 'announcement', 'annoncement': 'announcement',
        'loacation': 'location', 'loaction': 'location',
        'builidng': 'building', 'biulding': 'building',
        'stuednt': 'student', 'stundet': 'student',
        'taecher': 'teacher', 'techer': 'teacher',
        'proffessor': 'professor', 'professer': 'professor', 'proffesor': 'professor',
        'oraganization': 'organization', 'organisaton': 'organization',
        'hisotry': 'history', 'hitory': 'history',
        'loabatory': 'laboratory', 'laborartory': 'laboratory',
        'cahncel': 'chancellor', 'cahncellor': 'chancellor',
        'adminsitration': 'administration', 'admistration': 'administration',
        'infomation': 'information', 'informaton': 'information', 'inforamtion': 'information',
        'campous': 'campus', 'camups': 'campus',
        'universtiy': 'university', 'uniiversity': 'university',
        'speach': 'speech', 'speecht': 'speech',
        'navigaton': 'navigation', 'naviagtion': 'navigation',
        'dpartment': 'department', 'deparment': 'department',
    };

    function correctTypos(text) {
        if (!text || text.length < 2) return text;
        let corrected = text;

        // Apply word-level replacements (case-insensitive, whole word)
        for (const [typo, fix] of Object.entries(TYPO_MAP)) {
            const regex = new RegExp(`(?<![\\w])${typo}(?![\\w])`, 'gi');
            corrected = corrected.replace(regex, (match) => {
                // Preserve original casing style
                if (match === match.toUpperCase()) return fix.toUpperCase();
                if (match[0] === match[0].toUpperCase()) return fix.charAt(0).toUpperCase() + fix.slice(1);
                return fix;
            });
        }
        return corrected;
    }

    // ── Out-of-scope / nonsense detector ─────────────────────────────────────
    // Keywords that signal a query is campus-related
    const CAMPUS_KEYWORDS = [
        // People & roles
        'dean', 'chancellor', 'president', 'faculty', 'staff', 'professor',
        'teacher', 'instructor', 'official', 'admin', 'registrar', 'cashier',
        'who is', 'sino', 'pangalan',
        // Locations
        'where', 'location', 'building', 'room', 'office', 'lab', 'library',
        'laboratory', 'classroom', 'floor', 'campus', 'canteen', 'gym', 'chapel',
        'nasaan', 'saan',
        // Academic
        'college', 'department', 'cet', 'cics', 'cas', 'cabe', 'cte',
        'enrollment', 'schedule', 'curriculum', 'course',
        // Events & info
        'announcement', 'event', 'news', 'update', 'history', 'founded',
        'organization', 'org', 'club', 'bsu', 'sparta', 'batangas state',
        'anunsyo', 'kasaysayan', 'organisasyon',
        // Navigation
        'navigate', 'direction', 'map', 'find', 'go to', 'paano pumunta',
    ];

    // Greetings that are always OK
    const GREETING_PATTERNS = [
        /^(hi|hello|hey|good morning|good afternoon|good evening|kumusta|magandang)/i,
        /^(thanks|thank you|salamat|ok|okay|sure|got it|noted)/i,
        /^(help|tulong|ano ang magagawa mo|what can you do)/i,
    ];

    // Patterns that are clearly off-topic / nonsense
    const NONSENSE_PATTERNS = [
        /^[^a-zA-Z0-9\u00C0-\u024F\s.,!?'-]{3,}$/,   // Only symbols/emoji spam
        /^(.)\1{4,}$/,                                   // Repeated character: aaaaa
        /^[a-z]{1,2}(\s[a-z]{1,2}){3,}$/i,             // Short random word soup
    ];

    function isOutOfScope(text) {
        const lower = text.toLowerCase().trim();
        const wordCount = lower.split(/\s+/).length;

        // Always allow greetings
        if (GREETING_PATTERNS.some(p => p.test(lower))) return false;

        // Flag obvious nonsense patterns
        if (NONSENSE_PATTERNS.some(p => p.test(lower))) return true;

        // Very short (1-2 chars) that aren't meaningful
        if (lower.length <= 2) return true;

        // Check if it contains any campus-relevant keyword
        const hasCampusKeyword = CAMPUS_KEYWORDS.some(kw => lower.includes(kw));
        if (hasCampusKeyword) return false;

        // If it's a longer sentence (5+ words) with NO campus keywords, flag as out-of-scope
        // but only if it looks like a real question (not just a name being searched)
        if (wordCount >= 5 && !hasCampusKeyword) {
            // Allow if it could be a name/entity search (no verb-like question words)
            const hasQuestionWord = /\b(what|how|why|when|where|who|is|are|can|do|does|tell me|explain|give|show|list|find|please)\b/i.test(lower);
            if (hasQuestionWord) return true;
        }

        return false;
    }

    function getOutOfScopeResponse(text) {
        // Always respect the UI language selector, not text-based detection
        const isTagalog = langSelect && langSelect.value === 'tl-PH';

        // Check if it looks like gibberish/spam
        const isGibberish = NONSENSE_PATTERNS.some(p => p.test(text.trim()));

        if (isGibberish) {
            return isTagalog
                ? "Hindi ko naintindihan ang iyong mensahe. 🤔 Pakisubukan ulit na magtanong tungkol sa BSU Lipa campus!"
                : "I didn't quite understand that. 🤔 Please try asking a question about BSU Lipa campus — like people, locations, events, or organizations!";
        }

        return isTagalog
            ? "⚠️ **Walang impormasyon sa database para sa query na iyon.**\n\nAko ay SPARTA, isang campus assistant para sa **BSU Lipa** lamang. Kaya kong sagutin ang tungkol sa:\n\n**👥 Mga Tao** - Mga guro, kawani, opisyal\n**📍 Mga Lokasyon** - Mga gusali at silid\n**📅 Mga Anunsyo** - Pinakabagong balita\n**🏛️ Kasaysayan** - BSU Lipa na nakaraan\n**🎓 Mga Organisasyon** - Mga estudyanteng grupo\n\nAno ang gusto mong malaman tungkol sa campus?"
            : "⚠️ **No information found in the database for that query.**\n\nI'm SPARTA, a campus assistant for **BSU Lipa** only. I can help with:\n\n**👥 People** - Faculty, staff, and officials\n**📍 Locations** - Buildings and rooms\n**📅 Announcements** - Latest campus news\n**🏛️ History** - BSU Lipa background\n**🎓 Organizations** - Student groups\n\nWhat would you like to know about the campus?";
    }

    // ── Chat lock — prevents sending while a response is pending ──────────
    let isChatLocked = false;

    function setChatLock(locked) {
        isChatLocked = locked;
        userInput.disabled = locked;
        sendBtn.disabled = locked;
        micBtn.disabled = locked;
        sendBtn.style.opacity = locked ? '0.5' : '1';
        userInput.placeholder = locked
            ? '⏳ Waiting for response...'
            : 'Type your question or click the mic to speak...';
        // Disable quick question buttons too
        document.querySelectorAll('.quick-question-btn').forEach(b => {
            b.disabled = locked;
            b.style.opacity = locked ? '0.5' : '1';
            b.style.pointerEvents = locked ? 'none' : 'auto';
        });
    }

    // Main send message function - ENHANCED
    async function sendMessage() {
        const rawMessage = userInput.value.trim();
        if (!rawMessage || isChatLocked) return;

        // Apply typo correction
        const message = correctTypos(rawMessage);

        // Add user message (show corrected version)
        addMessage(message, 'user');
        userInput.value = '';

        // ── Out-of-scope / nonsense guard ──────────────────────────────────
        if (isOutOfScope(message)) {
            conversationHistory.push({ role: 'user', content: message });
            const oosReply = getOutOfScopeResponse(message);
            // Brief typing delay for natural feel
            typingIndicator.style.display = 'block';
            scrollToBottom();
            await new Promise(r => setTimeout(r, 700));
            typingIndicator.style.display = 'none';
            addMessage(oosReply, 'bot', false, 0.0, 'general_info');
            conversationHistory.push({ role: 'assistant', content: oosReply, intent: 'general_info' });
            updateQuickQuestions('general_info');
            speak(oosReply);
            return;
        }
        // ───────────────────────────────────────────────────────────────────

        // Add to conversation history
        conversationHistory.push({ role: 'user', content: message });

        // Lock chat while waiting
        setChatLock(true);

        // Show typing indicator
        typingIndicator.style.display = 'block';
        scrollToBottom();

        try {
        const response = await fetch(CHAT_API_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    language: document.getElementById('langSelect')
                        ? document.getElementById('langSelect').value
                        : 'en-US'
                })
            });

            if (!response.ok) {
                throw new Error('Server error');
            }

            const data = await response.json();
            
            // Hide typing indicator
            typingIndicator.style.display = 'none';

            // Add bot response with improved formatting
            addMessage(
                data.response, 
                'bot', 
                false, 
                data.confidence, 
                data.intent, 
                data.suggestions
            );
            
            // Store intent for context
            lastIntent = data.intent;
            conversationHistory.push({ role: 'assistant', content: data.response, intent: data.intent });

            // UPDATE QUICK QUESTIONS BASED ON RESPONSE INTENT
            // Pass the response text to detect college selection prompts
            updateQuickQuestions(data.intent, data.response);
            
            // Speak response
            speak(data.response);

        } catch (err) {
            console.error('Error:', err);
            typingIndicator.style.display = 'none';
            addMessage('Sorry, I encountered an error. Please try again or contact support.', 'bot', true);
            
            // Reset to default questions on error
            updateQuickQuestions('general_info');
        } finally {
            // Always unlock chat after response (or error)
            setChatLock(false);
        }
    }

    // Add message to chat - ENHANCED
    function addMessage(text, sender, isError = false, confidence = null, intent = null, suggestions = []) {
        const msg = document.createElement('div');
        msg.className = `message ${sender}`;

        const content = document.createElement('div');
        content.className = `message-content${isError ? ' error-message' : ''}`;

        // Format text with basic markdown support
        const formattedText = formatMarkdown(text);

        // Step 1 — Set message text
        content.innerHTML = formattedText;

        // Step 2 — Intent query type badge only
        if (sender === 'bot' && !isError && intent && intent !== 'unknown') {
            const container = document.createElement('div');
            container.className = 'confidence-container';

            const row = document.createElement('div');
            row.className = 'confidence-row';

            const intentBadge = document.createElement('span');
            intentBadge.className = 'intent-badge';
            intentBadge.textContent = `🎯 ${intent.replace(/_/g, ' ')}`;
            row.appendChild(intentBadge);

            container.appendChild(row);
            content.appendChild(container);
        }

        // Step 3 — Timestamp
        const time = document.createElement('span');
        time.className = 'message-time';
        time.textContent = new Date().toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit'
        });
        content.appendChild(time);

        // Step 4 — TTS button (bot messages only)
        if (sender === 'bot' && !isError) {
            const ttsBtn = document.createElement('button');
            ttsBtn.className = 'tts-msg-btn';
            ttsBtn.title = 'Read aloud';
            ttsBtn.innerHTML = `
                <span class="tts-msg-icon">🔊</span>
                <div class="tts-msg-wave">
                    <div class="tts-msg-wave-bar"></div>
                    <div class="tts-msg-wave-bar"></div>
                    <div class="tts-msg-wave-bar"></div>
                    <div class="tts-msg-wave-bar"></div>
                </div>
                <span class="tts-msg-label">Read aloud</span>`;
            ttsBtn.addEventListener('click', () => {
                if (ttsBtn.classList.contains('speaking')) {
                    stopSpeaking();
                } else {
                    speak(text, ttsBtn);
                }
            });
            content.appendChild(ttsBtn);
        }

        // Step 5 — Mount and scroll
        msg.appendChild(content);
        chatMessages.insertBefore(msg, typingIndicator);
        scrollToBottom();
    }


    // Typewriter effect — types text character by character
    function typewriterEffect(element, html, speed = 25, onComplete = null) {
        const plainText = html.replace(/<[^>]*>/g, '');
        const totalChars = plainText.length;

        const finish = () => {
            element.innerHTML = html;
            scrollToBottom();
            if (onComplete) onComplete();
        };

        // Skip animation for very long responses
        if (totalChars > 800) {
            finish();
            return;
        }

        let i = 0;
        element.innerHTML = '';
        element.style.minHeight = '1.2em';

        const interval = setInterval(() => {
            i += 1;
            if (i >= totalChars) {
                clearInterval(interval);
                finish();
                return;
            }
            element.textContent = plainText.substring(0, i) + '▋';
            scrollToBottom();
        }, speed);
    }

    // Format markdown-style text
    function formatMarkdown(text) {
        // Authority photo tag: [PHOTO:data:image/...base64...]
        text = text.replace(/\[PHOTO:([^\]]+)\]/g, (_, src) => {
            return `<div style="display:flex;flex-direction:column;align-items:center;margin:8px 0 12px 0;gap:8px;"><img src="${src}" alt="Authority Photo" style="width:110px;height:130px;object-fit:cover;object-position:center top;border-radius:10px;border:3px solid #c41e3a;box-shadow:0 4px 12px rgba(196,30,58,0.25);background:#f5f5f5;display:block;cursor:pointer;" onclick="openPhotoModal('${src}')" title="Click to view full photo"><button onclick="openPhotoModal('${src}')" style="display:flex;align-items:center;gap:5px;padding:5px 14px;background:linear-gradient(135deg,#c41e3a,#8b0000);color:white;border:none;border-radius:20px;font-size:11px;font-weight:600;cursor:pointer;box-shadow:0 2px 8px rgba(196,30,58,0.3);font-family:inherit;">🔍 View Full Photo</button></div>`;
        });

        // Bold: **text**
        text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        
        // Italic: *text*
        text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
        
        // Line breaks
        text = text.replace(/\n/g, '<br>');
        
        // Bullet points: • or -
        text = text.replace(/^[•\-]\s+(.+)$/gm, '<span style="display: block; margin-left: 20px;">• $1</span>');
        
        return text;
    }

    // Scroll to bottom of messages
    function scrollToBottom() {
        setTimeout(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
            
            // Mobile-specific: Ensure input is visible
            if (isMobile && document.activeElement === userInput) {
                userInput.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }, 100);
    }

    /* 🎤 Voice Input */
    let recognition = null;

    function startVoice() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            alert('Voice recognition is not supported in your browser. Please try Chrome or Edge.');
            return;
        }

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.lang = langSelect.value;
        recognition.continuous = false;
        recognition.interimResults = false;

        recognition.start();
        micBtn.classList.add('listening');
        userInput.placeholder = 'Listening...';

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            userInput.value = transcript;
            micBtn.classList.remove('listening');
            userInput.placeholder = 'Type your question or click the mic to speak...';
        };

        recognition.onend = () => {
            micBtn.classList.remove('listening');
            userInput.placeholder = 'Type your question or click the mic to speak...';
        };

        recognition.onerror = (event) => {
            console.error('Speech recognition error:', event.error);
            micBtn.classList.remove('listening');
            userInput.placeholder = 'Type your question or click the mic to speak...';
            
            if (event.error === 'no-speech') {
                alert('No speech detected. Please try again.');
            } else if (event.error === 'not-allowed') {
                alert('Microphone access denied. Please allow microphone access in your browser settings.');
            }
        };
    }

    /* 🔊 Text to Speech */
    // ── Voice selection cache ────────────────────────────────────────────────
    let cachedVoices = [];
    function loadVoices() {
        cachedVoices = window.speechSynthesis.getVoices();
    }
    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;

    function getBestVoice(lang) {
        const voices = cachedVoices.length ? cachedVoices : window.speechSynthesis.getVoices();
        if (!voices.length) return null;

        const isFilipino = lang === 'tl-PH';

        if (isFilipino) {
            // Priority order for Filipino TTS
            const priorities = [
                v => v.lang === 'fil-PH',
                v => v.lang === 'tl-PH',
                v => v.lang.startsWith('fil'),
                v => v.lang.startsWith('tl'),
                // Google voices tend to sound most natural
                v => v.name.toLowerCase().includes('google') && v.lang.startsWith('tl'),
                v => v.name.toLowerCase().includes('google') && v.lang.startsWith('fil'),
            ];
            for (const check of priorities) {
                const match = voices.find(check);
                if (match) return match;
            }
            // Last resort: any Filipino-sounding voice
            const fallback = voices.find(v =>
                v.name.toLowerCase().includes('filipino') ||
                v.name.toLowerCase().includes('tagalog')
            );
            if (fallback) return fallback;
        } else {
            // For English, prefer Google en-US or any en-US
            const enVoice =
                voices.find(v => v.name.toLowerCase().includes('google') && v.lang === 'en-US') ||
                voices.find(v => v.lang === 'en-US') ||
                voices.find(v => v.lang.startsWith('en'));
            if (enVoice) return enVoice;
        }
        return null;
    }

    function cleanTextForSpeech(text) {
        return text
            .replace(/\[PHOTO:[^\]]+\]/g, '')        // remove photo tags
            .replace(/\*\*(.+?)\*\*/g, '$1')       // bold
            .replace(/\*(.+?)\*/g, '$1')              // italic
            .replace(/#{1,6}\s/g, '')                  // headers
            .replace(/^[•\-\*]\s+/gm, '')            // bullet points
            .replace(/^\d+\.\s+/gm, '')              // numbered lists
            .replace(/https?:\/\/\S+/g, '')          // URLs
            .replace(/[📧📱🏢📍👥📂📅💡🎓📢🏛️♿🚶🗺️📜🎨⚽💼📆🎉📋😊🎯✅]/g, '')
            .replace(/\n{2,}/g, '. ')                  // double newlines to pause
            .replace(/\n/g, ', ')                      // single newlines to short pause
            .replace(/\s{2,}/g, ' ')                   // extra spaces
            .trim();
    }

    // ── TTS state tracking ──
    let activeTtsBtn = null;

    function setTtsIndicator(speaking, btnEl) {
        const pill = document.getElementById('ttsHeaderIndicator');
        // Header pill
        if (speaking) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
        // Clear old button state
        if (activeTtsBtn && activeTtsBtn !== btnEl) {
            activeTtsBtn.classList.remove('speaking');
        }
        activeTtsBtn = btnEl || null;
        if (activeTtsBtn) {
            if (speaking) {
                activeTtsBtn.classList.add('speaking');
            } else {
                activeTtsBtn.classList.remove('speaking');
            }
        }
    }

    function stopSpeaking() {
        window.speechSynthesis.cancel();
        setTtsIndicator(false, null);
    }

    function speakChunk(chunks, index, voice, lang, isFilipino, btnEl) {
        if (index >= chunks.length) {
            setTtsIndicator(false, null);
            return;
        }
        const utterance = new SpeechSynthesisUtterance(chunks[index]);
        utterance.lang = lang;
        if (voice) utterance.voice = voice;

        if (isFilipino) {
            utterance.rate = 0.95;
            utterance.pitch = 1.05;
            utterance.volume = 1.0;
        } else {
            utterance.rate = 1.1;
            utterance.pitch = 1.0;
            utterance.volume = 1.0;
        }

        if (index === 0) {
            utterance.onstart = () => setTtsIndicator(true, btnEl);
        }
        utterance.onend  = () => speakChunk(chunks, index + 1, voice, lang, isFilipino, btnEl);
        utterance.onerror = () => setTtsIndicator(false, null);
        window.speechSynthesis.speak(utterance);
    }

    function speak(text, btnEl = null) {
        window.speechSynthesis.cancel();
        setTtsIndicator(false, null);

        const lang = langSelect.value;
        const isFilipino = lang === 'tl-PH';
        const cleaned = cleanTextForSpeech(text);

        const chunks = cleaned
            .split(/(?<=[.!?])\s+/)
            .filter(c => c.trim().length > 0);

        if (!chunks.length) return;

        const voice = getBestVoice(lang);

        setTimeout(() => {
            speakChunk(chunks, 0, voice, lang, isFilipino, btnEl);
        }, 100);
    }

    // Stop speech when user starts typing
    userInput.addEventListener('input', () => {
        stopSpeaking();
    });

    // Language change handler
    langSelect.addEventListener('change', () => {
        console.log('Language changed to:', langSelect.value);
    });

    // Initialize — show fixed startup questions immediately on page load
    quickQuestionsContainer.style.transition = 'all 0.3s ease';
    updateQuickQuestions('general_info', '', true);



// ============ PHOTO MODAL ============
    function openPhotoModal(src) {
        // Remove existing modal if any
        const existing = document.getElementById('photoModal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'photoModal';
        modal.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.85);backdrop-filter:blur(6px);animation:fadeInModal 0.2s ease;';
        modal.innerHTML = `
            <div style="position:relative;max-width:90vw;max-height:90vh;display:flex;flex-direction:column;align-items:center;gap:12px;">
                <img src="${src}" alt="Full Photo" style="max-width:90vw;max-height:80vh;object-fit:contain;border-radius:12px;box-shadow:0 8px 40px rgba(0,0,0,0.6);border:3px solid #c41e3a;">
                <button onclick="document.getElementById('photoModal').remove()" style="padding:8px 24px;background:linear-gradient(135deg,#c41e3a,#8b0000);color:white;border:none;border-radius:20px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;box-shadow:0 4px 12px rgba(196,30,58,0.4);">✕ Close</button>
            </div>`;
        // Close on backdrop click
        modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
        document.body.appendChild(modal);
    }
    window.openPhotoModal = openPhotoModal;

// ============ EXPOSE GLOBAL FUNCTIONS ============
// Required because onclick= in HTML needs global scope
window.sendMessage = sendMessage;
window.renderQuickQuestions = renderQuickQuestions;
window.sendQuickQuestion = sendQuickQuestion;
window.startVoice = typeof startVoice !== 'undefined' ? startVoice : function(){};
window.stopSpeaking = typeof stopSpeaking !== 'undefined' ? stopSpeaking : function(){};

}); // end DOMContentLoaded