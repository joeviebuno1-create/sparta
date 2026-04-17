// ============ GLOBAL API HOST ============
const isDevTunnel = window.location.hostname.includes('devtunnels.ms') || window.location.hostname.includes('localhost');
const CHAT_API_URL = isDevTunnel
    ? `${window.location.protocol}//${window.location.hostname}/api/chat`
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

    // DYNAMIC QUICK QUESTIONS BASED ON CONTEXT
    const contextualQuestions = {
        'authority_query': [
            { text: '🎓 College Deans', query: 'Who is the dean?' },
            { text: '🏛️ Who is the Chancellor?', query: 'Who is the chancellor of BSU Lipa?' },
            { text: '🏫 Who is the President?', query: 'Who is the university president?' },
            { text: '👥 All university officials', query: 'Who are all the university officials?' },
        ],
        'authority_query_college_select': [
            { text: '🏗️ CET Dean', query: 'Who is the dean of College of Engineering Technology?' },
            { text: '💻 CICS Dean', query: 'Who is the dean of College of Informatics and Computing Sciences?' },
            { text: '🎨 CAS Dean', query: 'Who is the dean of College of Arts and Sciences?' },
            { text: '💼 CABE Dean', query: 'Who is the dean of College of Accountancy Business and Economics?' },
            { text: '👨‍🏫 CTE Dean', query: 'Who is the dean of College of Teacher Education?' }
        ],
        'announcement_query': [
            { text: '📢 More announcements', query: 'Show me more recent announcements' },
            { text: '🎓 Academic announcements', query: 'Any academic announcements?' },
            { text: '🎉 Campus events', query: 'What campus events are happening?' }
        ],
        'history_query': [
            { text: '📜 More history', query: 'Tell me more about BSU history' },
            { text: '🏛️ Major milestones', query: 'What are the major milestones of BSU?' },
            { text: '🎓 Founding story', query: 'How was BSU founded?' }
        ],
        'organization_query': [
            { text: '📋 All organizations', query: 'List all organizations' },
            { text: '🏆 Tell me about CABE org', query: 'Tell me about CABE organization' },
            { text: '🏆 Tell me about JME org', query: 'Tell me about JME organization' },
            { text: '🏆 Tell me about SSC org', query: 'Tell me about SSC organization' },
        ],  
        'location_query': [
            { text: '📍 Where is the computer lab 1?', query: 'Where is the computer lab 1?' },
            { text: '📍 Where is the computer lab 2?', query: 'Where is the computer lab 2?' }
        ],
        'general_info': [
            { text: '🎓 College deans', query: 'Who is the dean?' },
            { text: '📍 Where is the speech lab?', query: 'Where is the speech lab?' },
            { text: '📢 Announcements', query: 'What are the latest announcements?' },
            { text: '🏛️ BSU history', query: 'Tell me about BSU Lipa history' }
        ],
        'navigation_query': [
            { text: '📍 Where is the computer lab 1?', query: 'Where is the computer lab 1?' }
        ]
    };

    // Default questions — used as fallback before DB loads
    let defaultQuestions = [
        { text: '🎓 Who is the dean?', query: 'Who is the dean?' },
        { text: '🏛️ Who is the Chancellor?', query: 'Who is the chancellor of BSU Lipa?' },
        { text: '📍 Where is the speech lab?', query: 'Where is the speech lab?' },
        { text: '🏆 Tell me about SETS org', query: 'Tell me about SETS organization' },
        { text: '🏛️ University history', query: 'Tell me about BSU Lipa history' }
    ];

    // Fetch dynamic quick questions from database based on intent
    async function loadDynamicQuestions(intent = 'general_info') {
        try {
            const isDevTunnel = (window.location.hostname.includes('devtunnels.ms') ||
                window.location.hostname.includes('app.github.dev') ||
                window.location.hostname.includes('trycloudflare.com') ||
                window.location.hostname.includes('ngrok-free.app') ||
                window.location.hostname.includes('ngrok.io'));
            const BASE = isDevTunnel
                ? `${window.location.protocol}//${window.location.hostname}`
                : `${window.location.protocol}//${window.location.hostname}:8000`;

            const response = await fetch(`${BASE}/api/quick-questions?intent=${intent}`);
            if (!response.ok) return;

            const data = await response.json();
            if (!data || data.length === 0) return;

            // Render dynamic questions
            renderQuickQuestions(data.map(q => ({ text: q.text, query: q.query })));
        } catch (e) {
            console.log('Using static quick questions:', e.message);
        }
    }

    // Render a list of questions into the container
    function renderQuickQuestions(questions) {
        quickQuestionsContainer.innerHTML = '';
        questions.forEach(q => {
            const btn = document.createElement('button');
            btn.className = 'quick-question-btn';
            btn.textContent = q.text;
            btn.onclick = () => sendQuickQuestion(q.query);
            quickQuestionsContainer.appendChild(btn);
        });
    }

    // Update quick questions dynamically based on context
    function updateQuickQuestions(intent = 'general_info', responseText = '') {
        // Check if response is asking for college selection (updated detection)
        const isCollegeSelection = responseText && 
                                   (responseText.includes('What specific department') ||
                                    responseText.includes('Which college') ||
                                    responseText.includes('Which college Dean') ||
                                    responseText.includes('Which college Head')) &&
                                   responseText.includes('CET') && 
                                   responseText.includes('CICS');
        
        // If asking for college selection, show college quick questions
        const effectiveIntent = isCollegeSelection ? 'authority_query_college_select' : intent;
        const questions = contextualQuestions[effectiveIntent] || defaultQuestions;
        
        // Animate out
        quickQuestionsContainer.style.opacity = '0';
        quickQuestionsContainer.style.transform = 'translateY(10px)';
        
        setTimeout(() => {
            // Clear and rebuild with static contextual questions first
            renderQuickQuestions(questions);

            // Then enrich with dynamic DB questions (non-blocking)
            // Only for intents that benefit from DB suggestions
            const dynamicIntents = ['authority_query', 'location_query',
                                    'organization_query', 'announcement_query'];
            if (dynamicIntents.includes(effectiveIntent)) {
                loadDynamicQuestions(effectiveIntent);
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

    // Main send message function - ENHANCED
    async function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;

        // Add user message
        addMessage(message, 'user');
        userInput.value = '';

        // Add to conversation history
        conversationHistory.push({ role: 'user', content: message });

        // Show typing indicator
        typingIndicator.style.display = 'block';
        scrollToBottom();

        try {
        const response = await fetch(CHAT_API_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
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

        // Helper — builds and appends timestamp + TTS + badges after typing
        const appendExtras = () => {
            // Timestamp
            const time = document.createElement('span');
            time.className = 'message-time';
            time.textContent = new Date().toLocaleTimeString('en-US', {
                hour: '2-digit',
                minute: '2-digit'
            });
            content.appendChild(time);

            // TTS button
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
        };

        if (sender === 'bot' && !isError) {
            content.innerHTML = ''; // typewriter fills this
        } else {
            content.innerHTML = formattedText;
            appendExtras(); // instant for user/error messages
        }

        // Add confidence and intent badges for bot messages
        if (sender === 'bot' && confidence !== null) {
            const confidenceContainer = document.createElement('div');
            confidenceContainer.className = 'confidence-container';
            
            // Confidence badge
            const confidenceBadge = document.createElement('span');
            confidenceBadge.className = 'confidence-badge';
            
            let confidenceClass = 'confidence-low';
            let confidenceText = 'Low';
            
            if (confidence > 0.7) {
                confidenceClass = 'confidence-high';
                confidenceText = 'High';
            } else if (confidence > 0.4) {
                confidenceClass = 'confidence-medium';
                confidenceText = 'Medium';
            }
            
            confidenceBadge.className += ' ' + confidenceClass;
            confidenceBadge.textContent = `${confidenceText} (${(confidence * 100).toFixed(0)}%)`;
            confidenceContainer.appendChild(confidenceBadge);

            // Intent badge
            if (intent && intent !== 'unknown') {
                const intentBadge = document.createElement('span');
                intentBadge.className = 'intent-badge';
                intentBadge.textContent = intent.replace('_', ' ');
                confidenceContainer.appendChild(intentBadge);
            }

            content.appendChild(confidenceContainer);
        }

        msg.appendChild(content);
        chatMessages.insertBefore(msg, typingIndicator);
        scrollToBottom();

        // Trigger typewriter for bot messages — append extras after typing done
        if (sender === 'bot' && !isError) {
            typewriterEffect(content, formattedText, 25, () => {
                appendExtras();
            });
        }
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

    // Initialize with default questions
    setTimeout(() => {
        quickQuestionsContainer.style.transition = 'all 0.3s ease';
    }, 100);

// ============ EXPOSE GLOBAL FUNCTIONS ============
// Required because onclick= in HTML needs global scope
window.sendMessage = sendMessage;
window.renderQuickQuestions = typeof renderQuickQuestions !== 'undefined' ? renderQuickQuestions : function(){};
window.loadDynamicQuestions = typeof loadDynamicQuestions !== 'undefined' ? loadDynamicQuestions : function(){};
window.sendQuickQuestion = sendQuickQuestion;
window.startVoice = typeof startVoice !== 'undefined' ? startVoice : function(){};
window.stopSpeaking = typeof stopSpeaking !== 'undefined' ? stopSpeaking : function(){};

}); // end DOMContentLoaded