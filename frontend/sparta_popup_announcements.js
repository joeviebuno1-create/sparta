/**
 * sparta_popup_announcements.js
 * Drop-in popup announcement widget — matches the main menu popup style exactly.
 * Usage: <script src="sparta_popup_announcements.js"></script>
 * Auto-initialises on DOMContentLoaded.
 */
(function () {
    'use strict';

    const API_BASE = 'https://sparta-production-0acb.up.railway.app';

    const CSS = `
        :root { --primary-red: #c41e3a; }

        #spPopupOverlay {
            position: fixed; inset: 0;
            background: rgba(10,5,20,0.72);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
            z-index: 9999;
            display: none;
            align-items: flex-end;
            justify-content: center;
            padding: 0.75rem;
            padding-bottom: max(0.75rem, env(safe-area-inset-bottom));
        }
        @media (min-width: 540px) {
            #spPopupOverlay { align-items: center; padding: 1rem; }
        }
        #spPopupOverlay.visible {
            display: flex;
            animation: spOverlayIn 0.35s ease both;
        }
        @keyframes spOverlayIn { from{opacity:0} to{opacity:1} }

        .sp-card {
            background: #fff;
            border-radius: 24px;
            width: 100%;
            max-width: 580px;
            max-height: 92vh; max-height: 92dvh;
            overflow: hidden;
            display: flex; flex-direction: column;
            box-shadow:
                0 2px 4px rgba(0,0,0,0.04),
                0 8px 24px rgba(0,0,0,0.1),
                0 30px 80px rgba(0,0,0,0.35);
            animation: spCardDrop 0.45s cubic-bezier(0.175,0.885,0.32,1.275) both;
        }
        @media (max-width: 539px) {
            .sp-card {
                border-radius: 20px 20px 16px 16px;
                max-height: 94dvh; width: 100%;
                animation: spCardSheet 0.38s cubic-bezier(0.22,1,0.36,1) both;
            }
        }
        @keyframes spCardSheet { from{transform:translateY(60px);opacity:0} to{transform:translateY(0);opacity:1} }
        @keyframes spCardDrop  { from{transform:scale(0.88) translateY(30px);opacity:0} to{transform:scale(1) translateY(0);opacity:1} }

        .sp-hero {
            position: relative; width: 100%; flex-shrink: 0;
            background: #0f172a; line-height: 0;
        }
        .sp-hero-img {
            width: 100%; height: auto;
            max-height: 55vh; max-height: 55dvh;
            object-fit: contain; display: block; background: #0f172a;
        }
        @media (max-width: 539px) { .sp-hero-img { max-height: 45dvh; } }

        .sp-hero-overlay {
            position: absolute; inset: 0;
            background: linear-gradient(to bottom, rgba(0,0,0,0.18) 0%, rgba(0,0,0,0) 40%, rgba(0,0,0,0.45) 100%);
            pointer-events: none;
        }
        .sp-hero-noimg {
            width: 100%; height: 140px;
            display: flex; align-items: center; justify-content: center;
            position: relative; overflow: hidden;
        }
        .sp-hero-noimg::before {
            content: ''; position: absolute; inset: 0;
            background: repeating-linear-gradient(45deg, transparent, transparent 18px, rgba(255,255,255,0.04) 18px, rgba(255,255,255,0.04) 36px);
        }
        .sp-hero-noimg-icon {
            font-size: 4.5rem; opacity: 0.35;
            filter: drop-shadow(0 4px 12px rgba(0,0,0,0.3));
        }

        .sp-close {
            position: absolute; top: 0.85rem; right: 0.85rem; z-index: 10;
            background: rgba(0,0,0,0.35);
            border: 1.5px solid rgba(255,255,255,0.3);
            border-radius: 50%; width: 36px; height: 36px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; color: #fff; font-size: 0.95rem;
            transition: background 0.2s, transform 0.2s;
            backdrop-filter: blur(6px);
        }
        .sp-close:hover { background: rgba(196,30,58,0.85); transform: rotate(90deg) scale(1.1); }

        .sp-hero-badge {
            position: absolute; bottom: 0.9rem; left: 1rem; z-index: 5;
            padding: 0.22rem 0.85rem; border-radius: 50px;
            font-size: 0.7rem; font-weight: 800;
            letter-spacing: 0.1em; text-transform: uppercase;
        }
        .sp-cat-Academic  { background: rgba(37,99,235,0.9);    color: #fff; }
        .sp-cat-Events    { background: rgba(5,150,105,0.9);    color: #fff; }
        .sp-cat-General   { background: rgba(100,116,139,0.85); color: #fff; }
        .sp-cat-Emergency { background: rgba(220,38,38,0.95);   color: #fff; box-shadow: 0 0 12px rgba(220,38,38,0.6); }

        .sp-body {
            overflow-y: auto; -webkit-overflow-scrolling: touch;
            flex: 1; padding: 1.25rem 1.5rem 0.75rem;
            scrollbar-width: thin; scrollbar-color: #e2e8f0 transparent;
            overscroll-behavior: contain;
        }
        .sp-body::-webkit-scrollbar { width: 4px; }
        .sp-body::-webkit-scrollbar-track { background: transparent; }
        .sp-body::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 4px; }
        @media (max-width: 539px) { .sp-body { padding: 1rem 1.2rem 0.5rem; } }

        .sp-ann-title {
            font-weight: 900; font-size: 1.35rem; color: #0f172a;
            line-height: 1.3; margin-bottom: 0.85rem; letter-spacing: -0.01em;
        }
        .sp-ann-content { font-size: 0.95rem; color: #475569; line-height: 1.75; white-space: pre-line; }
        .sp-ann-date {
            display: flex; align-items: center; gap: 0.4rem;
            margin-top: 1.1rem; padding-top: 0.85rem;
            border-top: 1px solid #f1f5f9;
            font-size: 0.77rem; color: #94a3b8; font-weight: 500;
        }
        .sp-empty { text-align: center; padding: 3rem 1rem; color: #94a3b8; }
        .sp-empty-icon { font-size: 3rem; margin-bottom: 0.75rem; display: block; }
        .sp-empty-text { font-size: 0.95rem; }

        .sp-footer {
            display: flex; align-items: center; justify-content: space-between;
            padding: 0.75rem 1.25rem 1rem; flex-shrink: 0; gap: 0.5rem;
        }
        @media (max-width: 539px) {
            .sp-footer { padding: 0.6rem 1rem max(0.8rem, env(safe-area-inset-bottom)); }
        }
        .sp-arrow {
            width: 38px; height: 38px; border-radius: 50%;
            border: 1.5px solid #e2e8f0; background: #fff;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; font-size: 1rem; color: #475569;
            transition: all 0.2s; flex-shrink: 0;
        }
        .sp-arrow:hover:not(:disabled) {
            border-color: var(--primary-red); color: var(--primary-red);
            background: #fff5f5; transform: scale(1.1);
        }
        .sp-arrow:disabled { opacity: 0.25; cursor: default; }

        .sp-dots { display: flex; gap: 0.35rem; align-items: center; flex: 1; justify-content: center; }
        .sp-dot {
            height: 7px; border-radius: 50px; background: #e2e8f0;
            cursor: pointer; transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
            width: 7px; border: none;
        }
        .sp-dot.active { background: var(--primary-red); width: 22px; }

        .sp-counter {
            font-size: 0.78rem; color: #94a3b8; font-weight: 600;
            min-width: 36px; text-align: center;
        }

        #spNotifBell {
            display: none; position: fixed; top: 70px; right: 14px; z-index: 8888;
            background: linear-gradient(135deg, #c41e3a, #9b1530);
            color: #fff; border: none; border-radius: 50px;
            padding: 8px 14px 8px 10px; font-size: 0.82rem; font-weight: 600;
            cursor: pointer; box-shadow: 0 4px 14px rgba(196,30,58,0.35);
            align-items: center; gap: 6px; transition: transform 0.2s;
        }
        #spNotifBell:hover { transform: scale(1.05); }
        #spNotifBell.visible { display: flex; }
        .sp-bell-badge {
            background: rgba(255,255,255,0.3); border-radius: 99px;
            padding: 1px 7px; font-size: 0.75rem; font-weight: 700;
        }
    `;

    let popups = [];
    let currentIndex = 0;

    function escText(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function getCategoryClass(cat) {
        const map = { Academic: 'sp-cat-Academic', Events: 'sp-cat-Events', Emergency: 'sp-cat-Emergency' };
        return map[cat] || 'sp-cat-General';
    }

    function getCategoryIcon(cat) {
        const icons = { Academic: '🎓', Events: '🎉', Emergency: '🚨', General: '📢' };
        return icons[cat] || '📢';
    }

    function formatDate(iso) {
        if (!iso) return '';
        try { return new Date(iso).toLocaleDateString('en-PH', { year: 'numeric', month: 'long', day: 'numeric' }); }
        catch { return iso; }
    }

    function navigate(dir) {
        currentIndex = Math.max(0, Math.min(popups.length - 1, currentIndex + dir));
        renderPopup();
    }

    function inject() {
        const style = document.createElement('style');
        style.textContent = CSS;
        document.head.appendChild(style);

        // Bell
        const bell = document.createElement('button');
        bell.id = 'spNotifBell';
        bell.title = 'View Announcements';
        bell.onclick = openPopup;
        bell.innerHTML = `🔔 <span class="sp-bell-badge" id="spBellCount">0</span>`;
        document.body.appendChild(bell);

        // Overlay
        const overlay = document.createElement('div');
        overlay.id = 'spPopupOverlay';
        overlay.onclick = (e) => { if (e.target === overlay) closePopup(); };
        overlay.innerHTML = `
            <div class="sp-card" id="spCard">
                <div class="sp-hero" id="spHero">
                    <button class="sp-close" onclick="window._spClose()" title="Close">✕</button>
                </div>
                <div class="sp-body" id="spBody">
                    <div class="sp-empty">
                        <span class="sp-empty-icon">📭</span>
                        <span class="sp-empty-text">No announcements at this time.</span>
                    </div>
                </div>
                <div class="sp-footer" id="spFooter" style="display:none;">
                    <button class="sp-arrow" id="spPrev" onclick="window._spNav(-1)">&#8592;</button>
                    <div class="sp-dots" id="spDots"></div>
                    <span class="sp-counter" id="spCounter"></span>
                    <button class="sp-arrow" id="spNext" onclick="window._spNav(1)">&#8594;</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        // Keyboard navigation (same as main menu)
        document.addEventListener('keydown', (e) => {
            if (!document.getElementById('spPopupOverlay').classList.contains('visible')) return;
            if (e.key === 'Escape')     { closePopup();  return; }
            if (e.key === 'ArrowRight') { navigate(1);   return; }
            if (e.key === 'ArrowLeft')  { navigate(-1);  return; }
        });

        // Touch swipe (same as main menu)
        let touchStartX = 0;
        const card = document.getElementById('spCard');
        card.addEventListener('touchstart', e => { touchStartX = e.touches[0].clientX; }, { passive: true });
        card.addEventListener('touchend', e => {
            const dx = e.changedTouches[0].clientX - touchStartX;
            if (Math.abs(dx) > 50) navigate(dx < 0 ? 1 : -1);
        }, { passive: true });
    }

    function renderPopup() {
        const hero   = document.getElementById('spHero');
        const body   = document.getElementById('spBody');
        const dots   = document.getElementById('spDots');
        const footer = document.getElementById('spFooter');
        const prev   = document.getElementById('spPrev');
        const next   = document.getElementById('spNext');
        const ctr    = document.getElementById('spCounter');

        if (!popups.length) {
            hero.innerHTML = `<button class="sp-close" onclick="window._spClose()" title="Close">✕</button>
                <div class="sp-hero-noimg"><span class="sp-hero-noimg-icon">📢</span></div>`;
            body.innerHTML = `<div class="sp-empty">
                <span class="sp-empty-icon">📭</span>
                <span class="sp-empty-text">No announcements at this time.</span></div>`;
            dots.innerHTML = '';
            footer.style.display = 'none';
            return;
        }

        const ann = popups[currentIndex];
        const catClass = getCategoryClass(ann.category);

        // Hero
        if (ann.image_data) {
            hero.innerHTML = `
                <button class="sp-close" onclick="window._spClose()" title="Close">✕</button>
                <img src="${ann.image_data}" alt="${escText(ann.title)}" class="sp-hero-img">
                <div class="sp-hero-overlay"></div>
                <span class="sp-hero-badge ${catClass}">${escText(ann.category)}</span>`;
        } else {
            hero.innerHTML = `
                <button class="sp-close" onclick="window._spClose()" title="Close">✕</button>
                <div class="sp-hero-noimg">
                    <span class="sp-hero-noimg-icon">${getCategoryIcon(ann.category)}</span>
                </div>
                <div class="sp-hero-overlay"></div>
                <span class="sp-hero-badge ${catClass}">${escText(ann.category)}</span>`;
        }

        // Body
        body.innerHTML = `
            <div class="sp-ann-title">${escText(ann.title)}</div>
            ${ann.content ? `<div class="sp-ann-content">${escText(ann.content)}</div>` : ''}
            <div class="sp-ann-date">
                <span>📅</span>
                <span>Posted ${formatDate(ann.created_at)}</span>
            </div>`;

        // Footer
        if (popups.length > 1) {
            footer.style.display = 'flex';
            prev.disabled = currentIndex === 0;
            next.disabled = currentIndex === popups.length - 1;
            ctr.textContent = `${currentIndex + 1}/${popups.length}`;
            dots.innerHTML = popups.map((_, i) =>
                `<button class="sp-dot ${i === currentIndex ? 'active' : ''}" onclick="window._spGoto(${i})"></button>`
            ).join('');
        } else {
            footer.style.display = 'none';
        }
    }

    function openPopup() {
        currentIndex = 0;
        renderPopup();
        document.getElementById('spPopupOverlay').classList.add('visible');
    }

    function closePopup() {
        document.getElementById('spPopupOverlay').classList.remove('visible');
    }

    window._spClose = closePopup;
    window._spNav   = navigate;
    window._spGoto  = (i) => { currentIndex = i; renderPopup(); };
    window.openSpartaPopup = openPopup;

    async function init() {
        try {
            const res = await fetch(`${API_BASE}/api/announcement-popups`);
            if (!res.ok) return;
            const data = await res.json();
            popups = (data || []).filter(p => p.is_active !== false);
            if (!popups.length) return;

            inject();

            document.getElementById('spBellCount').textContent = popups.length;
            document.getElementById('spNotifBell').classList.add('visible');

            setTimeout(openPopup, 800);
        } catch (e) {
            console.log('[SPARTA popup] Could not load announcements:', e.message);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();