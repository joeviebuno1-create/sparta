/* ===================================
   SPARTHA ADMIN DASHBOARD - ENHANCED VERSION
   Interactive 3D Path Building with Animated Golden Paths
   =================================== */

// ========== CONFIGURATION ==========
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? '/api/admin'
    : 'https://sparta-production-0acb.up.railway.app/api/admin';
    
// Global state
let allLocations = [];
let allPaths = [];
let currentFilter = 'all';

// Path Building State
let isPathBuilding = false;
let pathWaypoints = []; // Array of {x, y, z, marker} coordinates
let currentPathMode = 'none'; // 'none', 'to_location', 'from_location'
let currentLocationId = null; // ID of the location being edited

// 3D Map Variables
let scene, camera, renderer, controls, campusModel;
let raycaster, mouse;

// Visual Elements
let locationMarker = null; // Blue marker for the main location
let waypointMarkers = []; // Red markers for path waypoints
let pathLines = []; // Golden path lines
let animatedParticles = []; // Animated particles along the path

// Animation
let animationId = null;
let animationTime = 0;

// Icon mapping
const ICON_MAP = {
    'entrance': '🚪',
    'evacuation': '🚨',
    'classroom': '🏫',
    'laboratory': '🔬',
    'office': '🏢',
    'library': '📚',
    'cafeteria': '🍽️',
    'auditorium': '🎭',
    'gym': '🏃',
    'restroom': '🚻',
    'parking': '🚗',
    'other': '📌'
};

// ========== HTTPONLY COOKIE AUTH HELPERS ==========
// JWT is stored in an HttpOnly cookie set by the server.
// JavaScript CANNOT read the cookie — the browser sends it automatically.
// Only username is stored in localStorage for display purposes.

function showLoginOverlay() {
    const overlay = document.getElementById('loginOverlay');
    if (overlay) {
        overlay.style.display = 'flex';
        overlay.style.opacity = '1';
        overlay.style.transform = 'scale(1)';
    }
}

async function apiFetch(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {})
        }
    });
    if (response.status === 401) {
        localStorage.removeItem('spartha_user');
        alert('⏰ Session expired. Please log in again.');
        showLoginOverlay();
        return null;
    }
    return response;
}

async function apiFetchForm(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        credentials: 'include',
    });
    if (response.status === 401) {
        localStorage.removeItem('spartha_user');
        alert('⏰ Session expired. Please log in again.');
        showLoginOverlay();
        return null;
    }
    return response;
}

// ========== PATH COLOR SELECTION ==========
function selectPathColor(button, color) {
    // Remove active class from all buttons
    document.querySelectorAll('.color-preset-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Add active class to clicked button
    button.classList.add('active');
    
    // Update hidden input value
    document.getElementById('path_color').value = color;
    
    console.log('Path color selected:', color);
}

// Make function globally available
window.selectPathColor = selectPathColor;

// ========== ENHANCED ANIMATIONS ==========
// Add ripple effect to buttons
function createRipple(event) {
    const button = event.currentTarget;
    const ripple = document.createElement('span');
    const rect = button.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const x = event.clientX - rect.left - size / 2;
    const y = event.clientY - rect.top - size / 2;
    
    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = x + 'px';
    ripple.style.top = y + 'px';
    ripple.classList.add('ripple');
    
    const existingRipple = button.querySelector('.ripple');
    if (existingRipple) {
        existingRipple.remove();
    }
    
    button.appendChild(ripple);
    
    setTimeout(() => ripple.remove(), 600);
}

// Add CSS for ripple effect
const rippleStyle = document.createElement('style');
rippleStyle.textContent = `
    .btn {
        position: relative;
        overflow: hidden;
    }
    .ripple {
        position: absolute;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.4);
        transform: scale(0);
        animation: ripple-animation 0.6s ease-out;
        pointer-events: none;
    }
    @keyframes ripple-animation {
        to {
            transform: scale(4);
            opacity: 0;
        }
    }
`;
document.head.appendChild(rippleStyle);

// Stagger animation for cards
function staggerCards() {
    const cards = document.querySelectorAll('.card');
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.1}s`;
    });
}

// Add parallax effect to header
function initParallax() {
    const header = document.querySelector('.header');
    if (!header) return;
    
    document.addEventListener('mousemove', (e) => {
        const moveX = (e.clientX - window.innerWidth / 2) * 0.01;
        const moveY = (e.clientY - window.innerHeight / 2) * 0.01;
        header.style.transform = `translate(${moveX}px, ${moveY}px)`;
    });
}

// Smooth scroll reveal for elements
function initScrollReveal() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, { threshold: 0.1 });
    
    // Only animate .tab-btn, NOT .tab-content (hiding tab-content breaks active tab display)
    document.querySelectorAll('.tab-btn').forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
}

// Initialize enhanced animations
document.addEventListener('DOMContentLoaded', () => {
    // Add ripple effect to all buttons
    document.querySelectorAll('.btn, .tab-btn').forEach(button => {
        button.addEventListener('click', createRipple);
    });
    
    staggerCards();
    initParallax();
    initScrollReveal();
    
    // Add smooth transitions to tab switching
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const activeContent = document.querySelector('.tab-content.active');
            if (activeContent) {
                activeContent.style.animation = 'fadeOutContent 0.3s ease-out';
                setTimeout(() => {
                    activeContent.style.animation = '';
                }, 300);
            }
        });
    });
});

// Add CSS for fade out animation
const fadeOutStyle = document.createElement('style');
fadeOutStyle.textContent = `
    @keyframes fadeOutContent {
        from {
            opacity: 1;
            transform: translateY(0);
        }
        to {
            opacity: 0;
            transform: translateY(-10px);
        }
    }
`;
document.head.appendChild(fadeOutStyle);


// ========== INITIALIZATION ==========
window.onload = function() {
    // Default to Statistics tab on load
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const statsTab = document.getElementById('statistics');
    if (statsTab) statsTab.classList.add('active');
    const statsBtn = document.querySelector('.tab-btn[onclick*="statistics"]');
    if (statsBtn) statsBtn.classList.add('active');

    loadStatistics();
    loadNavigationStatistics();
    setupEventListeners();
};

// ========== TAB SWITCHING ==========
function switchTab(tabName, event) {
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    document.getElementById(tabName).classList.add('active');
    // Use closest() so clicking the emoji inside the button still finds the button
    if (event && event.target) {
        event.target.closest('.tab-btn')?.classList.add('active');
    } else {
        // Fallback: find the button by matching its onclick attribute
        document.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.getAttribute('onclick')?.includes(`'${tabName}'`)) {
                btn.classList.add('active');
            }
        });
    }
    
    loadData(tabName);
    
    if (tabName === 'navigation') {
        setTimeout(() => {
            if (!scene) {
                initNavigationTab();
            }
        }, 100);
    }
}

// ========== DATA LOADING ==========
async function loadData(tabName) {
    try {
        let endpoint = '';
        let displayFunction = null;
        
        switch(tabName) {
            case 'authorities':
                endpoint = '/authorities';
                displayFunction = displayAuthorities;
                break;
            case 'history':
                endpoint = '/history';
                displayFunction = displayHistory;
                break;
            case 'announcements':
                endpoint = '/announcements';
                displayFunction = displayAnnouncements;
                break;
            case 'intents':
                endpoint = '/intents';
                displayFunction = displayIntents;
                break;
            case 'navigation':
                await loadNavigationData();
                return;
            case 'model3d':
                await loadModelUploadHistory();
                return;
            case 'orgchart':
                await loadOrganizations();
                return;
            case 'popupAnnouncements':
                await loadPopupAnnouncements();
                return;
        }
        
        if (endpoint && displayFunction) {
            const response = await apiFetch(endpoint);
            const data = await response.json();
            displayFunction(data);
        }
    } catch (error) {
        console.error('Error loading data:', error);
    }
}

// Display functions (authorities, history, announcements, intents)
function displayAuthorities(authorities) {
    const tbody = document.querySelector('#authoritiesTable tbody');
    tbody.innerHTML = '';
    authorities.forEach(auth => {
        const photoCell = auth.photo
            ? `<img src="${auth.photo}" alt="${auth.name}" style="width:44px;height:44px;border-radius:50%;object-fit:cover;border:2px solid #c41e3a;">`
            : `<div style="width:44px;height:44px;border-radius:50%;background:#f1f5f9;display:flex;align-items:center;justify-content:center;font-size:1.3rem;">&#128100;</div>`;
        const row = document.createElement('tr');
        row.innerHTML = `
            <td style="text-align:center;">${photoCell}</td>
            <td><strong>${auth.name}</strong></td>
            <td>${auth.position}</td>
            <td>${auth.department}</td>
            <td>${auth.email || '-'}</td>
            <td>${auth.phone || '-'}</td>
            <td>
            <button class="btn btn-small btn-secondary" onclick="editAuthority(${auth.id})" style="margin-right:4px;">✏️ Edit</button>
            <button class="btn btn-small btn-danger" onclick="deleteItem('authorities', ${auth.id})">Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function displayHistory(history) {
    const tbody = document.querySelector('#historyTable tbody');
    tbody.innerHTML = '';
    history.forEach(item => {
        const row = document.createElement('tr');
        const tlTitle = item.title_tl
            ? `<span style="color:#166534;">${item.title_tl}</span>`
            : `<span style="color:#94a3b8;font-size:0.8rem;">—</span>`;
        row.innerHTML = `
            <td><strong>${item.year}</strong></td>
            <td>${item.title}</td>
            <td>${tlTitle}</td>
            <td>${item.description.substring(0, 80)}...</td>
            <td>
                <button class="btn btn-small btn-secondary" onclick="editHistory(${item.id})" style="margin-right:4px;">✏️ Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteItem('history', ${item.id})">Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function displayAnnouncements(announcements) {
    const tbody = document.querySelector('#announcementsTable tbody');
    tbody.innerHTML = '';
    announcements.forEach(ann => {
        const row = document.createElement('tr');
        const date = new Date(ann.date_posted).toLocaleDateString();
        const tlTitle = ann.title_tl
            ? `<span style="color:#166534;">${ann.title_tl}</span>`
            : `<span style="color:#94a3b8;font-size:0.8rem;">—</span>`;
        row.innerHTML = `
            <td><strong>${ann.title}</strong></td>
            <td>${tlTitle}</td>
            <td>${ann.content.substring(0, 80)}...</td>
            <td>${ann.category}</td>
            <td>${date}</td>
            <td>
                <button class="btn btn-small btn-secondary" onclick="editAnnouncement(${ann.id})" style="margin-right:4px;">✏️ Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteItem('announcements', ${ann.id})">Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function displayIntents(intents) {
    const tbody = document.querySelector('#intentsTable tbody');
    tbody.innerHTML = '';
    intents.forEach(intent => {
        const row = document.createElement('tr');
        const tlResponse = intent.response_template_tl
            ? `<span style="color:#166534;">${intent.response_template_tl.substring(0, 80)}...</span>`
            : `<span style="color:#94a3b8;font-size:0.8rem;">—</span>`;
        row.innerHTML = `
            <td><strong>${intent.intent_type}</strong></td>
            <td>${intent.keywords}</td>
            <td>${intent.response_template.substring(0, 80)}...</td>
            <td>${tlResponse}</td>
            <td>
                <button class="btn btn-small btn-secondary" onclick="editIntent(${intent.id})" style="margin-right:4px;">✏️ Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteItem('intents', ${intent.id})">Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

// Delete item
async function deleteItem(type, id) {
    if (!confirm('Are you sure you want to delete this item?')) return;
    
    try {
        const response = await apiFetch(`/${type}/${id}`, { method: 'DELETE' });
        
        if (response.ok) {
            showAlert(type + 'Alert', '✅ Item deleted successfully!', 'success');
            loadData(type);
        }
        
    } catch (error) {
        showAlert(type + 'Alert', '❌ Error deleting item', 'error');
    }

}

async function editAuthority(id) {
    const response = await apiFetch('/authorities');
    if (!response || !response.ok) return;
    const authorities = await response.json();
    const auth = authorities.find(a => a.id === id);
    if (!auth) return;

    document.getElementById('auth_name').value = auth.name || '';
    document.getElementById('auth_position').value = auth.position || '';
    document.getElementById('auth_department').value = auth.department || '';
    document.getElementById('auth_email').value = auth.email || '';
    document.getElementById('auth_phone').value = auth.phone || '';
    document.getElementById('auth_office').value = auth.office_location || '';
    document.getElementById('auth_bio').value = auth.bio || '';

    if (auth.photo) {
        document.getElementById('auth_photo_img').src = auth.photo;
        document.getElementById('auth_photo_preview').style.display = 'block';
    } else {
        document.getElementById('auth_photo_preview').style.display = 'none';
    }

    document.getElementById('authorityForm').dataset.editingId = id;
    document.querySelector('#authorityForm [type=submit]').textContent = '✏️ Update Authority';
    // Scroll to form
    document.getElementById('authorityForm').scrollIntoView({ behavior: 'smooth' });
}

async function editHistory(id) {
    const response = await apiFetch('/history');
    if (!response || !response.ok) return;
    const items = await response.json();
    const item = items.find(h => h.id === id);
    if (!item) return;

    document.getElementById('hist_year').value = item.year || '';
    document.getElementById('hist_title').value = item.title || '';
    document.getElementById('hist_description').value = item.description || '';
    document.getElementById('hist_title_tl').value = item.title_tl || '';
    document.getElementById('hist_description_tl').value = item.description_tl || '';

    document.getElementById('historyForm').dataset.editingId = id;
    document.querySelector('#historyForm [type=submit]').textContent = '✏️ Update Historical Event';
    document.getElementById('historyForm').scrollIntoView({ behavior: 'smooth' });
}

async function editAnnouncement(id) {
    const response = await apiFetch('/announcements');
    if (!response || !response.ok) return;
    const items = await response.json();
    const item = items.find(a => a.id === id);
    if (!item) return;

    document.getElementById('ann_title').value = item.title || '';
    document.getElementById('ann_content').value = item.content || '';
    document.getElementById('ann_category').value = item.category || 'General';
    document.getElementById('ann_title_tl').value = item.title_tl || '';
    document.getElementById('ann_content_tl').value = item.content_tl || '';

    document.getElementById('announcementForm').dataset.editingId = id;
    document.querySelector('#announcementForm [type=submit]').textContent = '✏️ Update Announcement';
    document.getElementById('announcementForm').scrollIntoView({ behavior: 'smooth' });
}

async function editIntent(id) {
    const response = await apiFetch('/intents');
    if (!response || !response.ok) return;
    const items = await response.json();
    const item = items.find(i => i.id === id);
    if (!item) return;

    // Fill the intent form fields (adapt field IDs to match your intents form)
    const typeEl = document.getElementById('intent_type');
    const keywordsEl = document.getElementById('intent_keywords');
    const responseEl = document.getElementById('intent_response');
    const responseTlEl = document.getElementById('intent_response_tl');

    if (typeEl) typeEl.value = item.intent_type || '';
    if (keywordsEl) keywordsEl.value = item.keywords || '';
    if (responseEl) responseEl.value = item.response_template || '';
    if (responseTlEl) responseTlEl.value = item.response_template_tl || '';

    document.getElementById('intentsForm') && (document.getElementById('intentsForm').dataset.editingId = id);
    const submitBtn = document.querySelector('#intentsForm [type=submit]');
    if (submitBtn) submitBtn.textContent = '✏️ Update Response';
    document.getElementById('intentsForm')?.scrollIntoView({ behavior: 'smooth' });
}

// ========== NAVIGATION STATISTICS ==========
async function loadNavigationStatistics() {
    try {
        // Try the dedicated nav-statistics endpoint first, fall back to locations data
        let navData = null;
        const navStatResp = await apiFetch('/nav-statistics');
        if (navStatResp && navStatResp.ok) {
            navData = await navStatResp.json();
        } else {
            // Fallback: build stats from locations search log if available
            const locResp = await apiFetch('/locations');
            if (locResp && locResp.ok) {
                const locs = await locResp.json();
                // Build a synthetic stats object from location data
                navData = buildNavStatsFromLocations(locs);
            }
        }

        if (!navData) {
            document.getElementById('recentNavBody').innerHTML =
                '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:2rem;">Navigation statistics endpoint not available yet.</td></tr>';
            return;
        }

        // Summary cards
        document.getElementById('navStatTotalSearches').textContent = navData.total_searches ?? locs?.length ?? '—';
        document.getElementById('navStatUniqueLocations').textContent = navData.unique_locations ?? '—';
        document.getElementById('navStatTopLocation').textContent = navData.top_location ?? '—';
        document.getElementById('navStatTodaySearches').textContent = navData.today_searches ?? '—';

        // Most searched locations bar chart
        const locDiv = document.getElementById('navLocationChart');
        if (navData.top_locations && navData.top_locations.length) {
            const maxL = Math.max(...navData.top_locations.map(l => l.count));
            locDiv.innerHTML = navData.top_locations.map(item => {
                const pct = maxL > 0 ? (item.count / maxL * 100).toFixed(0) : 0;
                return `<div style="margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#475569;margin-bottom:3px;">
                        <span>📍 ${escapeHtml(item.name)}</span><span><strong>${item.count}</strong></span>
                    </div>
                    <div style="background:#e2e8f0;border-radius:99px;height:10px;overflow:hidden;">
                        <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#7c3aed,#5b21b6);border-radius:99px;transition:width 0.6s ease;"></div>
                    </div>
                </div>`;
            }).join('');
        } else {
            locDiv.innerHTML = '<p style="color:#94a3b8;font-size:0.85rem;">No search data yet.</p>';
        }

        // Searches by type chart
        const typeDiv = document.getElementById('navTypeChart');
        if (navData.type_breakdown && navData.type_breakdown.length) {
            const maxT = Math.max(...navData.type_breakdown.map(t => t.count));
            const typeColors = {
                classroom: '#3b82f6', laboratory: '#10b981', office: '#f59e0b',
                library: '#8b5cf6', cafeteria: '#ef4444', auditorium: '#ec4899',
                gym: '#14b8a6', restroom: '#64748b', parking: '#6366f1',
                entrance: '#c41e3a', evacuation: '#dc2626', other: '#94a3b8'
            };
            typeDiv.innerHTML = navData.type_breakdown.map(item => {
                const pct = maxT > 0 ? (item.count / maxT * 100).toFixed(0) : 0;
                const color = typeColors[item.type] || '#94a3b8';
                const icon = ICON_MAP[item.type] || '📌';
                return `<div style="margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#475569;margin-bottom:3px;">
                        <span>${icon} ${item.type.charAt(0).toUpperCase() + item.type.slice(1)}</span><span><strong>${item.count}</strong></span>
                    </div>
                    <div style="background:#e2e8f0;border-radius:99px;height:10px;overflow:hidden;">
                        <div style="height:100%;width:${pct}%;background:${color};border-radius:99px;transition:width 0.6s ease;"></div>
                    </div>
                </div>`;
            }).join('');
        } else {
            typeDiv.innerHTML = '<p style="color:#94a3b8;font-size:0.85rem;">No type data yet.</p>';
        }

        // Recent nav searches table
        const tbody = document.getElementById('recentNavBody');
        if (navData.recent_searches && navData.recent_searches.length) {
            tbody.innerHTML = navData.recent_searches.map(s => {
                const dt = s.searched_at ? new Date(s.searched_at).toLocaleString('en-PH', {
                    month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—';
                return `<tr>
                    <td><strong>${escapeHtml(s.name || s.location_name || '—')}</strong></td>
                    <td>${ICON_MAP[s.type] || '📌'} ${s.type || '—'}</td>
                    <td>${s.floor != null ? 'Floor ' + s.floor : '—'}</td>
                    <td>${escapeHtml(s.building || '—')}</td>
                    <td style="color:#64748b;font-size:0.82rem;">${dt}</td>
                </tr>`;
            }).join('');
        } else {
            // Fallback: show all locations as inventory
            const locResp2 = await apiFetch('/locations');
            if (locResp2 && locResp2.ok) {
                const locs2 = await locResp2.json();
                document.getElementById('navStatTotalSearches').textContent = locs2.length;
                document.getElementById('navStatUniqueLocations').textContent = [...new Set(locs2.map(l => l.name))].length;
                document.getElementById('navStatTopLocation').textContent = locs2[0]?.name ?? '—';
                document.getElementById('navStatTodaySearches').textContent = '—';
                tbody.innerHTML = locs2.slice(0, 20).map(s => `<tr>
                    <td><strong>${escapeHtml(s.name)}</strong></td>
                    <td>${ICON_MAP[s.type] || '📌'} ${s.type || '—'}</td>
                    <td>${s.floor != null ? 'Floor ' + s.floor : '—'}</td>
                    <td>${escapeHtml(s.building || '—')}</td>
                    <td style="color:#64748b;font-size:0.82rem;">—</td>
                </tr>`).join('');

                // Build type breakdown from locations list
                const typeCounts = {};
                locs2.forEach(l => { typeCounts[l.type] = (typeCounts[l.type] || 0) + 1; });
                const typeArr = Object.entries(typeCounts).map(([type, count]) => ({ type, count }))
                    .sort((a, b) => b.count - a.count);
                const maxT2 = Math.max(...typeArr.map(t => t.count));
                const typeColors2 = {
                    classroom: '#3b82f6', laboratory: '#10b981', office: '#f59e0b',
                    library: '#8b5cf6', cafeteria: '#ef4444', auditorium: '#ec4899',
                    gym: '#14b8a6', restroom: '#64748b', parking: '#6366f1',
                    entrance: '#c41e3a', evacuation: '#dc2626', other: '#94a3b8'
                };
                document.getElementById('navTypeChart').innerHTML = typeArr.map(item => {
                    const pct = maxT2 > 0 ? (item.count / maxT2 * 100).toFixed(0) : 0;
                    const color = typeColors2[item.type] || '#94a3b8';
                    const icon = ICON_MAP[item.type] || '📌';
                    return `<div style="margin-bottom:10px;">
                        <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#475569;margin-bottom:3px;">
                            <span>${icon} ${item.type.charAt(0).toUpperCase() + item.type.slice(1)}</span><span><strong>${item.count}</strong></span>
                        </div>
                        <div style="background:#e2e8f0;border-radius:99px;height:10px;overflow:hidden;">
                            <div style="height:100%;width:${pct}%;background:${color};border-radius:99px;transition:width 0.6s ease;"></div>
                        </div>
                    </div>`;
                }).join('');

                // Top locations list
                const nameCounts = {};
                locs2.forEach(l => { nameCounts[l.name] = (nameCounts[l.name] || 0) + 1; });
                const topLocs = Object.entries(nameCounts).map(([name, count]) => ({ name, count }))
                    .sort((a, b) => b.count - a.count).slice(0, 8);
                const maxL2 = Math.max(...topLocs.map(l => l.count));
                document.getElementById('navLocationChart').innerHTML = topLocs.map(item => {
                    const pct = maxL2 > 0 ? (item.count / maxL2 * 100).toFixed(0) : 0;
                    return `<div style="margin-bottom:10px;">
                        <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#475569;margin-bottom:3px;">
                            <span>📍 ${escapeHtml(item.name)}</span><span><strong>${item.count}</strong></span>
                        </div>
                        <div style="background:#e2e8f0;border-radius:99px;height:10px;overflow:hidden;">
                            <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#7c3aed,#5b21b6);border-radius:99px;transition:width 0.6s ease;"></div>
                        </div>
                    </div>`;
                }).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:2rem;">No navigation search data yet.</td></tr>';
            }
        }
    } catch (err) {
        console.error('Nav statistics error:', err);
    }
}
window.loadNavigationStatistics = loadNavigationStatistics;

function buildNavStatsFromLocations(locs) {
    if (!locs || !locs.length) return null;
    return {
        total_searches: locs.length,
        unique_locations: [...new Set(locs.map(l => l.name))].length,
        top_location: locs[0]?.name ?? '—',
        today_searches: '—',
        top_locations: [],
        type_breakdown: [],
        recent_searches: []
    };
}

// Show alert
function showAlert(id, message, type = 'info') {
    const alertEl = document.getElementById(id);
    if (!alertEl) {
        console.warn('Alert element not found:', id);
        alert(message);
        return;
    }
    alertEl.textContent = message;
    alertEl.className = `alert alert-${type}`;
    alertEl.style.display = 'block';
    setTimeout(() => {
        alertEl.style.display = 'none';
    }, 4000);
}

// ========== NAVIGATION TAB ==========

async function loadNavigationData() {
    try {
        // Load all locations
        const locResponse = await apiFetch('/locations');
        if (!locResponse) return;
        allLocations = await locResponse.json();
        
        // Load all routes
        const routeResponse = await apiFetch('/routes');
        allPaths = await routeResponse.json();
        
        displayLocations(allLocations);
        populateLocationDropdowns();
        
    } catch (error) {
        console.error('Error loading navigation data:', error);
        showAlert('navAlert', '❌ Error loading navigation data', 'error');
    }
}

function displayLocations(locations) {
    const tbody = document.querySelector('#locationsTable tbody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    const filteredLocations = currentFilter === 'all' 
        ? locations 
        : locations.filter(loc => loc.type === currentFilter);
    
    filteredLocations.forEach(loc => {
        const row = document.createElement('tr');
        const icon = loc.icon || ICON_MAP[loc.type] || '📌';
        const coords = `(${(loc.coord_x || 0).toFixed(1)}, ${(loc.coord_y || 0).toFixed(1)}, ${(loc.coord_z || 0).toFixed(1)})`;
        
        // Find paths for this location
        const relatedPaths = allPaths.filter(p => 
            p.start_location_id === loc.id || p.end_location_id === loc.id
        );
        
        row.innerHTML = `
            <td style="font-size: 2rem; text-align: center;">${icon}</td>
            <td><strong>${loc.name}</strong></td>
            <td>${loc.building}</td>
            <td>${loc.floor}</td>
            <td><span class="badge">${loc.type}</span></td>
            <td><code>${coords}</code></td>
            <td>${relatedPaths.length} path(s)</td>
            <td>
                <button class="btn btn-small" onclick="viewLocationOn3D(${loc.id})">👁️ View</button>
                <button class="btn btn-small btn-danger" onclick="deleteLocation(${loc.id})">🗑️</button>
            </td>
        `;
        tbody.appendChild(row);
    });
    
    if (filteredLocations.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem;">No locations found</td></tr>';
    }
}

function populateLocationDropdowns() {
    const dropdown = document.getElementById('path_connected_location');
    if (!dropdown) return;
    
    dropdown.innerHTML = '<option value="">Select location...</option>';
    
    allLocations.forEach(loc => {
        const icon = loc.icon || ICON_MAP[loc.type] || '📌';
        const option = document.createElement('option');
        option.value = loc.id;
        option.textContent = `${icon} ${loc.name} (${loc.building})`;
        dropdown.appendChild(option);
    });
}

function filterLocations(type) {
    currentFilter = type;
    displayLocations(allLocations);
}

async function deleteLocation(locationId) {
    if (!confirm('Are you sure you want to delete this location? This will also delete any paths connected to it.')) return;
    
    try {
        const response = await apiFetch(`/locations/${locationId}`, { method: 'DELETE' });
        
        if (response.ok) {
            showAlert('navAlert', '✅ Location deleted successfully!', 'success');
            await loadNavigationData();
        }
    } catch (error) {
        showAlert('navAlert', '❌ Error deleting location', 'error');
    }
}

function viewLocationOn3D(locationId) {
    const location = allLocations.find(loc => loc.id === locationId);
    if (!location || !camera) return;
    
    // Clear existing markers
    clearAllVisuals();
    
    // Add marker for this location
    if (location.coord_x !== null) {
        const marker = createMarker(
            location.coord_x, 
            location.coord_y, 
            location.coord_z,
            0x4A90E2, // Blue
            2.0
        );
        locationMarker = marker;
        scene.add(marker);
    }
    
    // Find and display all paths associated with this location
    const relatedPaths = allPaths.filter(p => 
        p.start_location_id === locationId || p.end_location_id === locationId
    );
    
    if (relatedPaths.length > 0) {
        console.log(`Found ${relatedPaths.length} path(s) for location ${location.name}`);
        
        relatedPaths.forEach(path => {
            // Get the connected location
            const connectedLocationId = path.start_location_id === locationId 
                ? path.end_location_id 
                : path.start_location_id;
            const connectedLocation = allLocations.find(loc => loc.id === connectedLocationId);
            
            if (connectedLocation && path.waypoints && path.waypoints.length > 0) {
                // Add marker for connected location
                const connectedMarker = createMarker(
                    connectedLocation.coord_x,
                    connectedLocation.coord_y,
                    connectedLocation.coord_z,
                    0x00FF00, // Green for connected location
                    1.5
                );
                waypointMarkers.push(connectedMarker);
                scene.add(connectedMarker);
                
                // Display path waypoints
                path.waypoints.forEach(wp => {
                    const wpMarker = createMarker(wp.x, wp.y, wp.z, 0xFF0000, 1.0);
                    waypointMarkers.push(wpMarker);
                    scene.add(wpMarker);
                });
                
                // Draw the complete path
                const pathColor = path.path_color || '#F4D03F';
                drawCompletePath(location, connectedLocation, path.waypoints, pathColor);
            }
        });
    }
    
    // Move camera to view this location
    if (location.coord_x !== null) {
        camera.position.set(
            location.coord_x + 50,
            location.coord_y + 50,
            location.coord_z + 50
        );
        controls.target.set(location.coord_x, location.coord_y, location.coord_z);
        controls.update();
    }
    
    const pathCount = relatedPaths.length;
    const message = pathCount > 0 
        ? `📍 Viewing ${location.name} with ${pathCount} path(s)` 
        : `📍 Viewing ${location.name} (no paths)`;
    showAlert('navAlert', message, 'info');
}

// ========== PATH MODE FUNCTIONS ==========

function changePathMode(mode) {
    currentPathMode = mode;
    const configSection = document.getElementById('pathConfigSection');
    
    if (mode === 'none') {
        configSection.style.display = 'none';
        stopPathBuilding();
    } else {
        configSection.style.display = 'block';
        
        // Update UI labels based on mode
        const pathNameInput = document.getElementById('path_name');
        if (mode === 'to_location') {
            pathNameInput.placeholder = 'e.g., Main Entrance to This Location';
        } else {
            pathNameInput.placeholder = 'e.g., This Location to Exit';
        }
    }
}

function startPathBuilding() {
    if (isPathBuilding) {
        stopPathBuilding();
        return;
    }
    
    const pathName = document.getElementById('path_name').value;
    const connectedLocation = document.getElementById('path_connected_location').value;
    
    if (!pathName || !connectedLocation) {
        alert('⚠️ Please enter a path name and select a connected location first!');
        return;
    }
    
    isPathBuilding = true;
    pathWaypoints = [];
    
    // Clear existing path visuals
    clearPathVisuals();
    
    // Update button
    const btn = document.querySelector('.btn-build-path');
    btn.classList.add('active');
    btn.innerHTML = '<span id="buildPathBtnText">🛑 Stop Building (Click to Finish)</span>';
    
    // Show waypoints box
    document.getElementById('pathWaypointsBox').style.display = 'block';
    updateWaypointsList();
    
    showAlert('navAlert', '🛤️ Path building mode activated! Click on the 3D map to add waypoints.', 'info');
}

function stopPathBuilding() {
    isPathBuilding = false;
    
    // Update button
    const btn = document.querySelector('.btn-build-path');
    if (btn) {
        btn.classList.remove('active');
        btn.innerHTML = '<span id="buildPathBtnText">🛤️ Click Map to Build Path</span>';
    }
    
    showAlert('navAlert', '✓ Path building stopped', 'info');
}

function addWaypointFromClick(coords) {
    if (!isPathBuilding) return;
    
    // Add waypoint to array
    const waypoint = {
        x: coords.x,
        y: coords.y,
        z: coords.z,
        index: pathWaypoints.length
    };
    
    // Create visual marker
    const marker = createMarker(coords.x, coords.y, coords.z, 0xFF4444, 1.5);
    waypoint.marker = marker;
    scene.add(marker);
    waypointMarkers.push(marker);
    
    pathWaypoints.push(waypoint);
    
    // Draw path lines
    if (pathWaypoints.length > 1) {
        drawPathBetweenWaypoints();
    }
    
    updateWaypointsList();
    
    // Play sound or visual feedback
    marker.scale.set(2, 2, 2);
    setTimeout(() => {
        marker.scale.set(1, 1, 1);
    }, 200);
}

function drawPathBetweenWaypoints() {
    // Clear existing path lines
    pathLines.forEach(line => scene.remove(line));
pathLines = [];
    
    // Create path line geometry - STRAIGHT LINES
    const points = pathWaypoints.map(wp => new THREE.Vector3(wp.x, wp.y, wp.z));
    
    if (points.length < 2) return;
    
    // Draw straight line segments between waypoints
    for (let i = 0; i < points.length - 1; i++) {
        const segmentPoints = [points[i], points[i + 1]];
        const geometry = new THREE.BufferGeometry().setFromPoints(segmentPoints);
        
        // Golden material with better visibility
        const material = new THREE.LineBasicMaterial({
            color: 0xFFD700,
            linewidth: 4,
            transparent: true,
            opacity: 0.9
        });
        
        const line = new THREE.Line(geometry, material);
        scene.add(line);
        pathLines.push(line);
    }
    
    // Add animated particles along straight path
    addAnimatedParticlesStraight(points);
}

function addAnimatedParticlesStraight(points) {
    // Clear existing particles
    animatedParticles.forEach(p => scene.remove(p.mesh));
    animatedParticles = [];
    
    // Create 5 particles that move along the straight path
    for (let i = 0; i < 5; i++) {
        const geometry = new THREE.SphereGeometry(0.8, 16, 16);
        const material = new THREE.MeshBasicMaterial({
            color: 0xFFFFFF,
            transparent: true,
            opacity: 0.9
        });
        const particle = new THREE.Mesh(geometry, material);
        
        scene.add(particle);
        
        animatedParticles.push({
            mesh: particle,
            points: points,
            progress: i / 5, // Stagger the particles
            speed: 0.008,  // Slightly faster for straight lines
            currentSegment: 0
        });
    }
}

function updateWaypointsList() {
    const list = document.getElementById('pathWaypointsList');
    const count = document.getElementById('pathWaypointCount');
    
    count.textContent = pathWaypoints.length;
    
    if (pathWaypoints.length === 0) {
        list.innerHTML = '<p class="empty-state">Click points on the 3D map to add waypoints</p>';
        return;
    }
    
    list.innerHTML = pathWaypoints.map((wp, index) => `
        <div class="waypoint-item">
            <span class="waypoint-number">${index + 1}</span>
            <span class="waypoint-coords">X: ${wp.x.toFixed(1)}, Y: ${wp.y.toFixed(1)}, Z: ${wp.z.toFixed(1)}</span>
            <button type="button" class="btn-remove-waypoint" onclick="removeWaypoint(${index})" title="Remove">
                ✕
            </button>
        </div>
    `).join('');
}

function removeWaypoint(index) {
    if (index < 0 || index >= pathWaypoints.length) return;
    
    // Remove marker from scene
    const waypoint = pathWaypoints[index];
    if (waypoint.marker) {
        scene.remove(waypoint.marker);
        const markerIndex = waypointMarkers.indexOf(waypoint.marker);
        if (markerIndex > -1) {
            waypointMarkers.splice(markerIndex, 1);
        }
    }
    
    // Remove from array
    pathWaypoints.splice(index, 1);
    
    // Redraw path
    if (pathWaypoints.length > 1) {
        drawPathBetweenWaypoints();
    } else {
        clearPathVisuals();
    }
    
    updateWaypointsList();
}

function clearPathWaypoints() {
    if (!confirm('Clear all waypoints?')) return;
    
    // Remove all markers
    waypointMarkers.forEach(marker => scene.remove(marker));
    waypointMarkers = [];
    
    // Clear path lines
    clearPathVisuals();
    
    pathWaypoints = [];
    updateWaypointsList();
}

function previewCurrentPath() {
    if (pathWaypoints.length < 2) {
        alert('⚠️ Add at least 2 waypoints to preview the path!');
        return;
    }
    
    // Animate camera along the straight path
    const points = pathWaypoints.map(wp => new THREE.Vector3(wp.x, wp.y, wp.z));
    
    // Calculate total path length
    let totalLength = 0;
    const segmentLengths = [];
    for (let i = 0; i < points.length - 1; i++) {
        const length = points[i].distanceTo(points[i + 1]);
        segmentLengths.push(length);
        totalLength += length;
    }
    
    let progress = 0;
    const previewInterval = setInterval(() => {
        progress += 0.01;
        if (progress >= 1) {
            clearInterval(previewInterval);
            return;
        }
        
        // Find current segment
        let targetDistance = progress * totalLength;
        let currentDistance = 0;
        let segmentIndex = 0;
        
        for (let i = 0; i < segmentLengths.length; i++) {
            if (currentDistance + segmentLengths[i] >= targetDistance) {
                segmentIndex = i;
                break;
            }
            currentDistance += segmentLengths[i];
        }
        
        // Interpolate position within segment
        const segmentProgress = (targetDistance - currentDistance) / segmentLengths[segmentIndex];
        const start = points[segmentIndex];
        const end = points[segmentIndex + 1];
        
        const point = new THREE.Vector3();
        point.lerpVectors(start, end, segmentProgress);
        
        camera.position.set(point.x + 20, point.y + 30, point.z + 20);
        controls.target.copy(point);
        controls.update();
    }, 30);
}

function clearPathVisuals() {
    // Clear path lines
    pathLines.forEach(line => scene.remove(line));
    pathLines = [];
    
    // Clear animated particles
    animatedParticles.forEach(p => scene.remove(p.mesh));
    animatedParticles = [];
}

function clearAllVisuals() {
    clearPathVisuals();
    
    // Clear waypoint markers
    waypointMarkers.forEach(marker => scene.remove(marker));
    waypointMarkers = [];
    
    // Clear location marker
    if (locationMarker) {
        scene.remove(locationMarker);
        locationMarker = null;
    }
}

function clearAllMarkers() {
    clearAllVisuals();
    pathWaypoints = [];
    updateWaypointsList();
    showAlert('navAlert', '🧹 All markers cleared', 'info');
}

// ========== COMPLETE PATH DRAWING ==========

function drawCompletePath(startLocation, endLocation, waypoints, pathColor = '#F4D03F') {
    if (!waypoints || waypoints.length < 2) return;
    
    // Convert waypoints to Vector3
    const points = [];
    
    // Add start location
    if (startLocation.coord_x !== null) {
        points.push(new THREE.Vector3(startLocation.coord_x, startLocation.coord_y, startLocation.coord_z));
    }
    
    // Add waypoints
    waypoints.forEach(wp => {
        points.push(new THREE.Vector3(wp.x, wp.y, wp.z));
    });
    
    // Add end location
    if (endLocation.coord_x !== null) {
        points.push(new THREE.Vector3(endLocation.coord_x, endLocation.coord_y, endLocation.coord_z));
    }
    
    // Draw straight line segments between all points
    for (let i = 0; i < points.length - 1; i++) {
        const segmentPoints = [points[i], points[i + 1]];
        const geometry = new THREE.BufferGeometry().setFromPoints(segmentPoints);
        
        // Convert hex color to THREE color
        const color = new THREE.Color(pathColor);
        
        const material = new THREE.LineBasicMaterial({
            color: color,
            linewidth: 4,
            transparent: true,
            opacity: 0.9
        });
        
        const line = new THREE.Line(geometry, material);
        scene.add(line);
        pathLines.push(line);
    }
    
    // Add animated particles
    addAnimatedParticlesStraight(points);
}

// ========== 3D MAP FUNCTIONS ==========

function createMarker(x, y, z, color = 0x1E90FF, size = 1.0) {
    // Create a group for the marker
    const markerGroup = new THREE.Group();
    
    // Main blue sphere
    const geometry = new THREE.SphereGeometry(size, 32, 32);
    const material = new THREE.MeshStandardMaterial({ 
        color: 0x1E90FF,  // Dodger Blue
        emissive: 0x4169E1,  // Royal Blue
        emissiveIntensity: 0.8,
        metalness: 0.6,
        roughness: 0.2,
        transparent: true,
        opacity: 0.95
    });
    const sphere = new THREE.Mesh(geometry, material);
    markerGroup.add(sphere);
    
    // Inner glow ring
    const ring1 = new THREE.Mesh(
        new THREE.RingGeometry(size * 1.5, size * 1.8, 32),
        new THREE.MeshBasicMaterial({
            color: 0x4A90E2,
            transparent: true,
            opacity: 0.5,
            side: THREE.DoubleSide
        })
    );
    ring1.rotation.x = -Math.PI / 2;
    markerGroup.add(ring1);
    
    // Outer ripple ring
    const ring2 = new THREE.Mesh(
        new THREE.RingGeometry(size * 2.2, size * 2.5, 32),
        new THREE.MeshBasicMaterial({
            color: 0x87CEEB,
            transparent: true,
            opacity: 0.3,
            side: THREE.DoubleSide
        })
    );
    ring2.rotation.x = -Math.PI / 2;
    markerGroup.add(ring2);
    
    markerGroup.position.set(x, y, z);
    
    // Add animation data
    markerGroup.userData = {
        originalScale: size,
        pulsePhase: Math.random() * Math.PI * 2,
        sphere: sphere,
        ring1: ring1,
        ring2: ring2
    };
    
    return markerGroup;
}

function initNavigationTab() {
    const container = document.getElementById('map3DPicker');
    const canvas = document.getElementById('map3DCanvas');
    
    if (!container || !canvas) {
        console.error('3D map container not found');
        return;
    }
    
    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f1f3);
    scene.fog = new THREE.Fog(0xf0f1f3, 200, 500);
    
    // Camera
    camera = new THREE.PerspectiveCamera(
        60,
        container.clientWidth / container.clientHeight,
        0.1,
        1000
    );
    camera.position.set(0, 150, -250);
    
    // Renderer
    renderer = new THREE.WebGLRenderer({ 
        canvas: canvas,
        antialias: true,
        alpha: true
    });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    
    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(50, 100, 50);
    directionalLight.castShadow = true;
    scene.add(directionalLight);
    
    const hemisphereLight = new THREE.HemisphereLight(0x87CEEB, 0x545454, 0.5);
    scene.add(hemisphereLight);

    
    // Controls
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 20;
    controls.maxDistance = 400;
    controls.maxPolarAngle = Math.PI / 2.1;
    
    // Load GLB model
    const loader = new THREE.GLTFLoader();
    loader.load(
        'https://sparta-production-0acb.up.railway.app/static/batangas_state_university-_the_neu_lipa_map.glb',
        (gltf) => {
            campusModel = gltf.scene;
            
            // Center and scale model
            const box = new THREE.Box3().setFromObject(campusModel);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            
            campusModel.position.sub(center);
            
            const scale = 100 / Math.max(size.x, size.y, size.z);
            campusModel.scale.set(scale, scale, scale);
            
            // Enable shadows
            campusModel.traverse((node) => {
                if (node.isMesh) {
                    node.castShadow = true;
                    node.receiveShadow = true;
                }
            });
            
            scene.add(campusModel);
            
            document.getElementById('mapLoading').style.display = 'none';
            showAlert('navAlert', '✅ 3D Campus Map loaded! Click to place markers.', 'success');
        },
        (xhr) => {
            const progress = (xhr.loaded / xhr.total * 100).toFixed(0);
            console.log(`Loading: ${progress}%`);
            document.querySelector('.loading-text').textContent = `Loading 3D Campus Map (${progress}%)`;
        },
        (error) => {
            console.error('Error loading model:', error);
            document.getElementById('mapLoading').innerHTML = `
                <div style="color: white; text-align: center;">
                    <div style="font-size: 3rem;">⚠️</div>
                    <div style="font-size: 1.2rem; font-weight: 600;">Failed to Load Model</div>
                    <div style="font-size: 0.9rem; margin-top: 0.5rem;">Check GLB file path</div>
                </div>
            `;
        }
    );
    
    // Raycaster for click detection
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();
    
    canvas.addEventListener('click', onCanvasClick);
    
    // Animation loop
    function animate() {
        animationId = requestAnimationFrame(animate);
        controls.update();
        animationTime += 0.016;
        
        // Animate particles along straight path
        animatedParticles.forEach(particle => {
            if (!particle.points || particle.points.length < 2) return;
            
            particle.progress += particle.speed;
            
            // Calculate total path length
            let totalLength = 0;
            const segmentLengths = [];
            for (let i = 0; i < particle.points.length - 1; i++) {
                const length = particle.points[i].distanceTo(particle.points[i + 1]);
                segmentLengths.push(length);
                totalLength += length;
            }
            
            // Reset if reached end
            if (particle.progress >= 1) particle.progress = 0;
            
            // Find which segment the particle is on
            let targetDistance = particle.progress * totalLength;
            let currentDistance = 0;
            let segmentIndex = 0;
            
            for (let i = 0; i < segmentLengths.length; i++) {
                if (currentDistance + segmentLengths[i] >= targetDistance) {
                    segmentIndex = i;
                    break;
                }
                currentDistance += segmentLengths[i];
            }
            
            // Interpolate position within segment
            const segmentProgress = (targetDistance - currentDistance) / segmentLengths[segmentIndex];
            const start = particle.points[segmentIndex];
            const end = particle.points[segmentIndex + 1];
            
            particle.mesh.position.lerpVectors(start, end, segmentProgress);
            
            // Pulse effect
            const pulse = 1 + Math.sin(animationTime * 3 + particle.progress * Math.PI * 2) * 0.2;
            particle.mesh.scale.set(pulse, pulse, pulse);
        });
        
        // Animate blue markers with enhanced pulsing and ring effects
        waypointMarkers.forEach(marker => {
            if (marker.userData) {
                // Pulse the sphere
                const pulse = marker.userData.originalScale * (1 + Math.sin(animationTime * 2 + marker.userData.pulsePhase) * 0.2);
                if (marker.userData.sphere) {
                    marker.userData.sphere.scale.set(pulse, pulse, pulse);
                }
                
                // Animate inner ring
                if (marker.userData.ring1) {
                    const ring1Scale = 1 + 0.3 * Math.sin(animationTime * 1.5 + marker.userData.pulsePhase);
                    const ring1Opacity = 0.4 + 0.3 * Math.sin(animationTime * 1.5);
                    marker.userData.ring1.scale.set(ring1Scale, ring1Scale, 1);
                    marker.userData.ring1.material.opacity = ring1Opacity;
                }
                
                // Animate outer ripple ring
                if (marker.userData.ring2) {
                    const ring2Scale = 1 + 0.5 * Math.sin(animationTime + marker.userData.pulsePhase);
                    const ring2Opacity = 0.2 + 0.2 * Math.sin(animationTime);
                    marker.userData.ring2.scale.set(ring2Scale, ring2Scale, 1);
                    marker.userData.ring2.material.opacity = ring2Opacity;
                }
                
                // Gentle rotation
                marker.rotation.y += 0.005;
            }
        });
        
        // Animate location marker (main blue marker)
        if (locationMarker && locationMarker.userData) {
            const pulse = locationMarker.userData.originalScale * (1 + Math.sin(animationTime * 2) * 0.2);
            if (locationMarker.userData.sphere) {
                locationMarker.userData.sphere.scale.set(pulse, pulse, pulse);
            }
            
            if (locationMarker.userData.ring1) {
                const ring1Scale = 1 + 0.3 * Math.sin(animationTime * 1.5);
                const ring1Opacity = 0.4 + 0.3 * Math.sin(animationTime * 1.5);
                locationMarker.userData.ring1.scale.set(ring1Scale, ring1Scale, 1);
                locationMarker.userData.ring1.material.opacity = ring1Opacity;
            }
            
            if (locationMarker.userData.ring2) {
                const ring2Scale = 1 + 0.5 * Math.sin(animationTime);
                const ring2Opacity = 0.2 + 0.2 * Math.sin(animationTime);
                locationMarker.userData.ring2.scale.set(ring2Scale, ring2Scale, 1);
                locationMarker.userData.ring2.material.opacity = ring2Opacity;
            }
            
            locationMarker.rotation.y += 0.005;
        }
        
        renderer.render(scene, camera);
    }
    animate();
    
    // Handle resize
    window.addEventListener('resize', () => {
        if (container.clientWidth > 0) {
            camera.aspect = container.clientWidth / container.clientHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(container.clientWidth, container.clientHeight);
        }
    });
}

function onCanvasClick(event) {
    if (!campusModel) return;
    
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    
    raycaster.setFromCamera(mouse, camera);
    
    const intersects = raycaster.intersectObject(campusModel, true);
    
    if (intersects.length > 0) {
        const point = intersects[0].point;
        const coords = {
            x: Math.round(point.x * 10) / 10,
            y: Math.round(point.y * 10) / 10,
            z: Math.round(point.z * 10) / 10
        };
        
        updateCoordinateDisplay(coords);
        
        // If path building mode is active, add waypoint
        if (isPathBuilding) {
            addWaypointFromClick(coords);
        } else {
            // Otherwise, set main location coordinates
            updateLocationCoordinates(coords);
            
            // Show visual marker
            clearAllVisuals();
            locationMarker = createMarker(coords.x, coords.y, coords.z, 0x4A90E2, 2.0);
            scene.add(locationMarker);
        }
    }
}

function updateCoordinateDisplay(coords) {
    const display = document.getElementById('coordDisplay');
    display.textContent = `📍 X: ${coords.x.toFixed(1)}, Y: ${coords.y.toFixed(1)}, Z: ${coords.z.toFixed(1)}`;
}

function updateLocationCoordinates(coords) {
    // Update hidden form fields
    document.getElementById('loc_coord_x').value = coords.x;
    document.getElementById('loc_coord_y').value = coords.y;
    document.getElementById('loc_coord_z').value = coords.z;
    
    // Update display fields
    document.getElementById('display_coord_x').textContent = coords.x.toFixed(1);
    document.getElementById('display_coord_y').textContent = coords.y.toFixed(1);
    document.getElementById('display_coord_z').textContent = coords.z.toFixed(1);
}

// ========== CAMERA CONTROLS ==========

function resetCameraView() {
    if (!camera || !controls) return;
    camera.position.set(0, 150, -250);
    controls.target.set(0, 0, 0);
    controls.update();
}

function zoomIn() {
    if (!camera || !controls) return;
    const direction = new THREE.Vector3();
    camera.getWorldDirection(direction);
    camera.position.addScaledVector(direction, 20);
    controls.update();
}

function zoomOut() {
    if (!camera || !controls) return;
    const direction = new THREE.Vector3();
    camera.getWorldDirection(direction);
    camera.position.addScaledVector(direction, -20);
    controls.update();
}

// ========== FORM SUBMISSION ==========


// ========== PATH VALIDATION ==========
function validatePathData() {
    if (currentPathMode === 'none') {
        return { valid: true, message: '' }; // No path to validate
    }
    
    if (pathWaypoints.length < 2) {
        return { 
            valid: false, 
            message: '⚠️ Path must have at least 2 waypoints. Click on the map to add more waypoints.' 
        };
    }
    
    const pathName = document.getElementById('path_name').value;
    if (!pathName || pathName.trim() === '') {
        return { 
            valid: false, 
            message: '⚠️ Path name is required when creating a path. Please enter a descriptive name.' 
        };
    }
    
    const connectedLocationId = document.getElementById('path_connected_location').value;
    if (!connectedLocationId || connectedLocationId === '' || isNaN(parseInt(connectedLocationId))) {
        return { 
            valid: false, 
            message: '⚠️ Please select a connected location for the path from the dropdown.' 
        };
    }
    
    return { valid: true, message: '' };
}

async function handleLocationFormSubmit(e) {
    e.preventDefault();
    
    const locationData = {
        name: document.getElementById('loc_name').value,
        building: document.getElementById('loc_building').value,
        floor: parseInt(document.getElementById('loc_floor').value),
        type: document.getElementById('loc_type').value,
        icon: document.getElementById('loc_icon').value || null,
        capacity: parseInt(document.getElementById('loc_capacity').value) || null,
        description: document.getElementById('loc_description').value || null,
        coordinates: {
            x: parseFloat(document.getElementById('loc_coord_x').value) || 0,
            y: parseFloat(document.getElementById('loc_coord_y').value) || 0,
            z: parseFloat(document.getElementById('loc_coord_z').value) || 0
        }
    };
    
    // Validate coordinates
    if (locationData.coordinates.x === 0 && locationData.coordinates.y === 0 && locationData.coordinates.z === 0) {
        showAlert('navAlert', '⚠️ Please click on the 3D map to set location coordinates', 'error');
        return;
    }
    
    // Validate path data if path mode is active
    const pathValidation = validatePathData();
    if (!pathValidation.valid) {
        showAlert('navAlert', pathValidation.message, 'error');
        return;
    }
    
    try {
        console.log('=== SAVING LOCATION ===');
        console.log('Location data:', locationData);
        
        // Save location first
        const locResponse = await apiFetch('/locations', { method: 'POST', body: JSON.stringify(locationData) });
        
        if (!locResponse.ok) {
            const errorData = await locResponse.json().catch(() => ({}));
            throw new Error(`Failed to save location: ${errorData.detail || locResponse.statusText}`);
        }
        
        const savedLocation = await locResponse.json();
        const locationId = savedLocation.id;
        
        console.log('✅ Location saved successfully with ID:', locationId);
        
        // Save path if waypoints exist and mode is not 'none'
        if (currentPathMode !== 'none' && pathWaypoints.length > 0) {
            console.log('=== SAVING PATH ===');
            
            const pathName = document.getElementById('path_name').value.trim();
            const connectedLocationId = parseInt(document.getElementById('path_connected_location').value);
            const pathColor = document.getElementById('path_color').value || '#F4D03F';
            const isWheelchair = document.getElementById('path_wheelchair').checked;
            
            // Convert waypoints to simple coordinate array with explicit typing
            let waypointCoords = pathWaypoints.map(wp => ({
                x: parseFloat(wp.x),
                y: parseFloat(wp.y),
                z: parseFloat(wp.z)
            }));

            // Path FROM this location = opposite direction, so reverse the waypoints
            // so it draws from this location outward, not from entrance inward
            if (currentPathMode === 'from_location') {
                waypointCoords = waypointCoords.slice().reverse();
            }
            
            const routeData = {
                name: pathName,
                type: 'custom',
                start_location_id: parseInt(currentPathMode === 'to_location' ? connectedLocationId : locationId),
                end_location_id: parseInt(currentPathMode === 'to_location' ? locationId : connectedLocationId),
                is_wheelchair_accessible: Boolean(isWheelchair),
                path_color: String(pathColor),
                waypoints: waypointCoords
            };
            
            // Validate route data before sending
            console.log('=== ROUTE DATA VALIDATION ===');
            console.log('Path name:', pathName, '(empty?', !pathName, ')');
            console.log('Connected location ID:', connectedLocationId, '(type:', typeof connectedLocationId, ')');
            console.log('Current location ID:', locationId, '(type:', typeof locationId, ')');
            console.log('Path mode:', currentPathMode);
            console.log('Start location ID:', routeData.start_location_id, '(type:', typeof routeData.start_location_id, ')');
            console.log('End location ID:', routeData.end_location_id, '(type:', typeof routeData.end_location_id, ')');
            console.log('Number of waypoints:', waypointCoords.length);
            console.log('Waypoints sample:', waypointCoords[0]);
            console.log('Full route data:', JSON.stringify(routeData, null, 2));
            console.log('=== END VALIDATION ===');
            
            const routeResponse = await apiFetch('/routes', { method: 'POST', body: JSON.stringify(routeData) });
            
            if (!routeResponse.ok) {
                const errorData = await routeResponse.json().catch(() => ({}));
                console.error('❌ Route save failed with status:', routeResponse.status);
                console.error('❌ Error details:', JSON.stringify(errorData, null, 2));
                console.error('❌ Route data that was sent:', JSON.stringify(routeData, null, 2));
                
                // Show detailed error message
                let errorMsg = '⚠️ Location saved, but failed to save path: ';
                if (errorData.detail) {
                    if (Array.isArray(errorData.detail)) {
                        errorMsg += errorData.detail.map(e => `${e.loc?.join('.')} - ${e.msg}`).join('; ');
                    } else {
                        errorMsg += errorData.detail;
                    }
                } else {
                    errorMsg += 'Unknown error';
                }
                
                showAlert('navAlert', errorMsg, 'warning');
                // Don't return - location was saved successfully
            } else {
                const routeResult = await routeResponse.json();
                console.log('✅ Route saved successfully:', routeResult);
                showAlert('navAlert', '✅ Location and path saved successfully!', 'success');
            }
        } else {
            showAlert('navAlert', '✅ Location saved successfully!', 'success');
        }
        
        // Reset form and state
        document.getElementById('locationForm').reset();
        currentPathMode = 'none';
        document.querySelector('input[value="none"]').checked = true;
        changePathMode('none');
        clearAllVisuals();
        pathWaypoints = [];
        
        // Reload data
        await loadNavigationData();
        
    } catch (error) {
        console.error('❌ Error saving location:', error);
        showAlert('navAlert', `❌ Error: ${error.message}`, 'error');
    }
}

// ========== EVENT LISTENERS ==========

function setupEventListeners() {
    // Authority Form — multipart/form-data so photo file uploads correctly
document.getElementById('authorityForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const photoFile = document.getElementById('auth_photo')?.files[0];
    const submitBtn = e.target.querySelector('[type=submit]');
    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ Saving...';
    try {
        const fd = new FormData();
        fd.append('name', document.getElementById('auth_name').value);
        fd.append('position', document.getElementById('auth_position').value);
        fd.append('department', document.getElementById('auth_department').value);
        fd.append('email', document.getElementById('auth_email')?.value || '');
        fd.append('phone', document.getElementById('auth_phone')?.value || '');
        fd.append('office_location', document.getElementById('auth_office')?.value || '');
        fd.append('bio', document.getElementById('auth_bio')?.value || '');
        if (photoFile) fd.append('photo', photoFile);

        const editingId = document.getElementById('authorityForm').dataset.editingId;
        const url = editingId ? `/authorities/${editingId}` : '/authorities';
        const method = editingId ? 'PUT' : 'POST';
        if (editingId) fd.append('keep_existing_photo', 'true');

        const response = await apiFetchForm(url, { method, body: fd });
        if (response && response.ok) {
            showAlert('authoritiesAlert', editingId ? '✅ Authority updated!' : '✅ Authority added!', 'success');
            document.getElementById('authorityForm').reset();
            document.getElementById('authorityForm').removeAttribute('data-editing-id');
            document.getElementById('auth_photo_preview').style.display = 'none';
            submitBtn.textContent = '✓ Add Authority';
            loadData('authorities');
        } else if (response) {
            const err = await response.json().catch(() => ({}));
            showAlert('authoritiesAlert', `❌ ${err.detail || 'Error saving authority'}`, 'error');
        }
    } catch (error) {
        showAlert('authoritiesAlert', '❌ Error: ' + error.message, 'error');
    } finally {
        submitBtn.disabled = false;
    }
});
    // Authority photo preview
    document.getElementById('auth_photo')?.addEventListener('change', function() {
        const file = this.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                document.getElementById('auth_photo_img').src = e.target.result;
                document.getElementById('auth_photo_preview').style.display = 'block';
            };
            reader.readAsDataURL(file);
        } else {
            document.getElementById('auth_photo_preview').style.display = 'none';
        }
    });
    
    // History Form
    document.getElementById('historyForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = e.target.querySelector('[type=submit]');
        submitBtn.disabled = true;
        const editingId = document.getElementById('historyForm').dataset.editingId;
        
        const historyData = {
            year: parseInt(document.getElementById('hist_year').value),
            title: document.getElementById('hist_title').value,
            description: document.getElementById('hist_description').value,
            title_tl: document.getElementById('hist_title_tl').value.trim() || null,
            description_tl: document.getElementById('hist_description_tl').value.trim() || null
        };
        
        try {
            const url = editingId ? `/history/${editingId}` : '/history';
            const method = editingId ? 'PUT' : 'POST';
            const response = await apiFetch(url, { method, body: JSON.stringify(historyData) });
            
            if (response && response.ok) {
                showAlert('historyAlert', editingId ? '✅ Historical event updated!' : '✅ Historical event added!', 'success');
                document.getElementById('historyForm').reset();
                document.getElementById('historyForm').removeAttribute('data-editing-id');
                submitBtn.textContent = '✓ Add Historical Event';
                loadData('history');
            } else if (response) {
                const err = await response.json().catch(() => ({}));
                showAlert('historyAlert', `❌ ${err.detail || 'Error saving event'}`, 'error');
            }
        } catch (error) {
            showAlert('historyAlert', '❌ Error: ' + error.message, 'error');
        } finally {
            submitBtn.disabled = false;
        }
    });
    
    // Announcement Form
    document.getElementById('announcementForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = e.target.querySelector('[type=submit]');
        submitBtn.disabled = true;
        const editingId = document.getElementById('announcementForm').dataset.editingId;
        
        const announcementData = {
            title: document.getElementById('ann_title').value,
            content: document.getElementById('ann_content').value,
            category: document.getElementById('ann_category').value,
            date_posted: new Date().toISOString(),
            title_tl: document.getElementById('ann_title_tl').value.trim() || null,
            content_tl: document.getElementById('ann_content_tl').value.trim() || null
        };
        
        try {
            const url = editingId ? `/announcements/${editingId}` : '/announcements';
            const method = editingId ? 'PUT' : 'POST';
            const response = await apiFetch(url, { method, body: JSON.stringify(announcementData) });
            
            if (response && response.ok) {
                showAlert('announcementsAlert', editingId ? '✅ Announcement updated!' : '✅ Announcement posted!', 'success');
                document.getElementById('announcementForm').reset();
                document.getElementById('announcementForm').removeAttribute('data-editing-id');
                submitBtn.textContent = '✓ Post Announcement';
                loadData('announcements');
            } else if (response) {
                const err = await response.json().catch(() => ({}));
                showAlert('announcementsAlert', `❌ ${err.detail || 'Error saving announcement'}`, 'error');
            }
        } catch (error) {
            showAlert('announcementsAlert', '❌ Error: ' + error.message, 'error');
        } finally {
            submitBtn.disabled = false;
        }
    });
    
    // Intent Form
    document.getElementById('intentForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = e.target.querySelector('[type=submit]');
        submitBtn.disabled = true;
        const editingId = document.getElementById('intentsForm')?.dataset.editingId;
        
        const intentData = {
            intent_type: document.getElementById('intent_type').value,
            keywords: document.getElementById('intent_keywords').value,
            response_template: document.getElementById('intent_response').value,
            response_template_tl: document.getElementById('intent_response_tl').value.trim() || null
        };
        
        try {
            const url = editingId ? `/intents/${editingId}` : '/intents';
            const method = editingId ? 'PUT' : 'POST';
            const response = await apiFetch(url, { method, body: JSON.stringify(intentData) });
            
            if (response && response.ok) {
                showAlert('intentsAlert', editingId ? '✅ Response updated!' : '✅ Intent added!', 'success');
                document.getElementById('intentForm').reset();
                if (document.getElementById('intentsForm')) {
                    document.getElementById('intentsForm').removeAttribute('data-editing-id');
                }
                submitBtn.textContent = '✓ Add Custom Response';
                loadData('intents');
            } else if (response) {
                const err = await response.json().catch(() => ({}));
                showAlert('intentsAlert', `❌ ${err.detail || 'Error saving intent'}`, 'error');
            }
        } catch (error) {
            showAlert('intentsAlert', '❌ Error: ' + error.message, 'error');
        } finally {
            submitBtn.disabled = false;
        }
    });
    
    // Location Form
    document.getElementById('locationForm')?.addEventListener('submit', handleLocationFormSubmit);
    
    // 3D Model Upload Form
    document.getElementById('model3dForm')?.addEventListener('submit', handleModel3DUpload);
    
    // File upload area interactions
    const fileUploadArea = document.getElementById('fileUploadArea');
    const fileInput = document.getElementById('model3d_file');
    
    if (fileUploadArea && fileInput) {
        // Click to upload
        fileUploadArea.addEventListener('click', () => {
            if (!document.getElementById('fileUploadSelected').style.display || 
                document.getElementById('fileUploadSelected').style.display === 'none') {
                fileInput.click();
            }
        });
        
        // File selection
        fileInput.addEventListener('change', handleFileSelect);
        
        // Drag and drop
        fileUploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            fileUploadArea.classList.add('dragover');
        });
        
        fileUploadArea.addEventListener('dragleave', () => {
            fileUploadArea.classList.remove('dragover');
        });
        
        fileUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            fileUploadArea.classList.remove('dragover');
            
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                const file = files[0];
                if (file.name.endsWith('.glb') || file.name.endsWith('.gltf')) {
                    fileInput.files = files;
                    handleFileSelect({ target: { files: files } });
                } else {
                    alert('❌ Please upload a .GLB or .GLTF file');
                }
            }
        });
    }
}

// Icon preview update
function updateIconPreview() {
    const icon = document.getElementById('loc_icon').value;
    const preview = document.getElementById('icon_preview');
    if (icon) {
        preview.textContent = icon;
        preview.style.display = 'inline';
    } else {
        preview.style.display = 'none';
    }
}

// ========== 3D MODEL UPLOAD ==========

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const placeholder = document.getElementById('fileUploadPlaceholder');
    const selected = document.getElementById('fileUploadSelected');
    const fileName = document.getElementById('selectedFileName');
    const fileSize = document.getElementById('selectedFileSize');
    
    // Show selected file info
    placeholder.style.display = 'none';
    selected.style.display = 'block';
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
    
    // Validate file size (50MB limit)
    if (file.size > 50 * 1024 * 1024) {
        showAlert('model3dAlert', '⚠️ File is too large. Maximum size is 50MB.', 'warning');
    }
}

function clearFileSelection() {
    const fileInput = document.getElementById('model3d_file');
    const placeholder = document.getElementById('fileUploadPlaceholder');
    const selected = document.getElementById('fileUploadSelected');
    
    fileInput.value = '';
    placeholder.style.display = 'block';
    selected.style.display = 'none';
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

async function loadModelUploadHistory() {
    try {
        const response = await apiFetch('/model-upload-history');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const uploads = await response.json();
        displayModelUploadHistory(uploads);
    } catch (error) {
        console.error('Error loading upload history:', error);
        // Show error in table
        const tbody = document.querySelector('#modelHistoryTable tbody');
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; padding: 2rem; color: #ef4444;">
                        ❌ Error loading upload history
                    </td>
                </tr>
            `;
        }
    }
}

function displayModelUploadHistory(uploads) {
    const tbody = document.querySelector('#modelHistoryTable tbody');
    if (!tbody) return;
    
    if (!uploads || uploads.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align: center; padding: 2rem; color: #64748b;">
                    No upload history yet
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = '';
    uploads.forEach(upload => {
        const row = document.createElement('tr');
        const uploadDate = upload.uploaded_at ? new Date(upload.uploaded_at).toLocaleString() : 'N/A';
        const fileSize = formatFileSize(upload.file_size || 0);
        const status = upload.status === 'success' ? '✅ Success' : '❌ Failed';
        const statusClass = upload.status === 'success' ? 'success' : 'error';
        
        row.innerHTML = `
            <td>${uploadDate}</td>
            <td><strong>${upload.original_filename}</strong></td>
            <td>${fileSize}</td>
            <td>${upload.description || '-'}</td>
            <td><span class="badge badge-${statusClass}">${status}</span></td>
        `;
        tbody.appendChild(row);
    });
}

async function handleModel3DUpload(e) {
    e.preventDefault();
    
    const fileInput = document.getElementById('model3d_file');
    const file = fileInput.files[0];
    
    if (!file) {
        showAlert('model3dAlert', '⚠️ Please select a file to upload', 'error');
        return;
    }
    
    // Validate file type
    if (!file.name.endsWith('.glb') && !file.name.endsWith('.gltf')) {
        showAlert('model3dAlert', '❌ Only .GLB or .GLTF files are allowed', 'error');
        return;
    }
    
    // Validate file size (50MB)
    if (file.size > 50 * 1024 * 1024) {
        showAlert('model3dAlert', '❌ File is too large. Maximum size is 50MB.', 'error');
        return;
    }
    
    const description = document.getElementById('model3d_description').value || '';
    
    // Show upload progress
    const uploadProgress = document.getElementById('uploadProgress');
    const uploadProgressBar = document.getElementById('uploadProgressBar');
    const uploadPercent = document.getElementById('uploadPercent');
    uploadProgress.style.display = 'block';
    
    try {
        // Create FormData
        const formData = new FormData();
        formData.append('file', file);
        formData.append('description', description);
        
        // Upload with progress tracking
        const xhr = new XMLHttpRequest();
        
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentComplete = Math.round((e.loaded / e.total) * 100);
                uploadProgressBar.style.width = percentComplete + '%';
                uploadProgressBar.textContent = percentComplete + '%';
                uploadPercent.textContent = percentComplete + '%';
            }
        });
        
        xhr.addEventListener('load', () => {
            if (xhr.status === 401) {
                localStorage.removeItem('spartha_user');
                alert('⏰ Session expired. Please log in again.');
                showLoginOverlay();
                uploadProgress.style.display = 'none';
                return;
            }
            if (xhr.status === 200) {
                const response = JSON.parse(xhr.responseText);
                showAlert('model3dAlert', '✅ ' + response.message + ' Please refresh the page to see the new model.', 'success');
                
                // Update current model display
                document.getElementById('currentModelName').textContent = file.name;
                document.getElementById('currentModelDate').textContent = new Date().toLocaleString();
                
                // Reset form
                document.getElementById('model3dForm').reset();
                clearFileSelection();
                
                // Reload upload history
                loadModelUploadHistory();
                
                // Hide progress
                setTimeout(() => {
                    uploadProgress.style.display = 'none';
                    uploadProgressBar.style.width = '0%';
                }, 2000);
                
            } else {
                const error = JSON.parse(xhr.responseText);
                showAlert('model3dAlert', '❌ Upload failed: ' + (error.detail || 'Unknown error'), 'error');
                uploadProgress.style.display = 'none';
            }
        });
        
        xhr.addEventListener('error', () => {
            showAlert('model3dAlert', '❌ Network error during upload', 'error');
            uploadProgress.style.display = 'none';
        });
        
        xhr.open('POST', `${API_BASE}/upload-3d-model`);
        xhr.withCredentials = true;
        xhr.send(formData);
        
    } catch (error) {
        console.error('Upload error:', error);
        showAlert('model3dAlert', '❌ Error: ' + error.message, 'error');
        uploadProgress.style.display = 'none';
    }
}

// Logout
function logout() {
    if (confirm('Logout?')) {
        window.location.href = '/';
    }
}
// ========== ORGANIZATIONAL CHART MANAGEMENT ==========

// Global variable for selected organization
let selectedOrgId = null;

// Load all organizations
async function loadOrganizations() {
    try {
        const response = await apiFetch('/organizations');
        if (!response) return;
        const organizations = await response.json();
        displayOrganizations(organizations);
    } catch (error) {
        console.error('Error loading organizations:', error);
        showAlert('orgchartAlert', '❌ Error loading organizations', 'error');
    }
}

// Display organizations in table
function displayOrganizations(organizations) {
    const tbody = document.querySelector('#orgTable tbody');
    tbody.innerHTML = '';
    
    if (organizations.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2rem; color: #64748b;">No organizations yet</td></tr>';
        return;
    }
    
    organizations.forEach(org => {
        const row = document.createElement('tr');
        const createdDate = new Date(org.created_at).toLocaleDateString();
        const membersCount = org.member_count || 0;
        const description = org.description || '-';
        
        row.innerHTML = `
            <td><strong>${org.name}</strong></td>
            <td>${description}</td>
            <td>${membersCount}</td>
            <td>${createdDate}</td>
            <td>
                <button class="btn btn-small" onclick="selectOrganization(${org.id}, '${org.name.replace(/'/g, "\\'")}')">➕ Add Members</button>
                <button class="btn btn-small btn-edit" onclick="openEditOrgModal(${org.id}, '${org.name.replace(/'/g, "\\'")}', '${(org.description || '').replace(/'/g, "\\'").replace(/\n/g, ' ')}')">✏️ Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteOrganization(${org.id})">🗑️ Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

// Select organization to add members
async function selectOrganization(orgId, orgName) {
    selectedOrgId = orgId;
    document.getElementById('memberOrgId').value = orgId;
    document.getElementById('selectedOrgName').textContent = orgName;
    document.getElementById('selectedOrgNameMembers').textContent = orgName;
    document.getElementById('memberSection').style.display = 'block';
    
    // Scroll to member section
    document.getElementById('memberSection').scrollIntoView({ behavior: 'smooth' });
    
    // Load members for this organization
    await loadMembers(orgId);
}

// Close member section
function closeMemberSection() {
    selectedOrgId = null;
    document.getElementById('memberSection').style.display = 'none';
}

// Load members for selected organization
async function loadMembers(orgId) {
    try {
        const response = await apiFetch(`/organizations/${orgId}/members`);
        if (!response) return;
        const members = await response.json();
        displayMembers(members);
    } catch (error) {
        console.error('Error loading members:', error);
        showAlert('memberAlert', '❌ Error loading members', 'error');
    }
}

// Display members in table
function displayMembers(members) {
    const tbody = document.querySelector('#membersTable tbody');
    tbody.innerHTML = '';
    
    if (members.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; padding: 1.5rem; color: #64748b;">No members yet</td></tr>';
        return;
    }
    
    members.forEach(member => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${member.name}</strong></td>
            <td>${member.position}</td>
            <td>
                <button class="btn btn-small btn-edit" onclick="openEditMemberModal(${member.id}, '${member.name.replace(/'/g, "\\'")}', '${member.position.replace(/'/g, "\\'")}')">✏️ Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteMember(${member.id}, ${selectedOrgId})">🗑️ Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

// Delete organization
async function deleteOrganization(orgId) {
    if (!confirm('Are you sure you want to delete this organization? All members will also be deleted.')) return;
    
    try {
        const response = await apiFetch(`/organizations/${orgId}`, { method: 'DELETE' });
        
        if (response.ok) {
            showAlert('orgchartAlert', '✅ Organization deleted successfully!', 'success');
            loadOrganizations();
            closeMemberSection();
        } else {
            showAlert('orgchartAlert', '❌ Error deleting organization', 'error');
        }
    } catch (error) {
        console.error('Error deleting organization:', error);
        showAlert('orgchartAlert', '❌ Error deleting organization', 'error');
    }
}

// Delete member
async function deleteMember(memberId, orgId) {
    if (!confirm('Are you sure you want to delete this member?')) return;
    
    try {
        const response = await apiFetch(`/members/${memberId}`, { method: 'DELETE' });
        
        if (response.ok) {
            showAlert('memberAlert', '✅ Member deleted successfully!', 'success');
            loadMembers(orgId);
            loadOrganizations(); // Refresh to update member count
        } else {
            showAlert('memberAlert', '❌ Error deleting member', 'error');
        }
    } catch (error) {
        console.error('Error deleting member:', error);
        showAlert('memberAlert', '❌ Error deleting member', 'error');
    }
}

// Organization Form Handler
document.getElementById('orgForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const orgName = document.getElementById('org_name').value;
    const orgDescription = document.getElementById('org_description').value;
    
    try {
        const response = await apiFetch('/organizations', {
            method: 'POST',
            body: JSON.stringify({ 
                name: orgName,
                description: orgDescription || null
            })
        });
        
        if (response.ok) {
            showAlert('orgchartAlert', '✅ Organization added successfully!', 'success');
            document.getElementById('orgForm').reset();
            loadOrganizations();
        } else {
            const error = await response.json();
            showAlert('orgchartAlert', '❌ ' + (error.detail || 'Error adding organization'), 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showAlert('orgchartAlert', '❌ Error adding organization', 'error');
    }
});

// Member Form Handler
document.getElementById('memberForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const memberName = document.getElementById('member_name').value;
    const memberPosition = document.getElementById('member_position').value;
    const orgId = document.getElementById('memberOrgId').value;
    
    try {
        const response = await apiFetch(`/organizations/${orgId}/members`, {
            method: 'POST',
            body: JSON.stringify({
                name: memberName,
                position: memberPosition
            })
        });
        
        if (response.ok) {
            showAlert('memberAlert', '✅ Member added successfully!', 'success');
            document.getElementById('memberForm').reset();
            document.getElementById('memberOrgId').value = selectedOrgId;
            loadMembers(selectedOrgId);
            loadOrganizations(); // Refresh to update member count
        } else {
            const error = await response.json();
            showAlert('memberAlert', '❌ ' + (error.detail || 'Error adding member'), 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showAlert('memberAlert', '❌ Error adding member', 'error');
    }
});
// ========== ADMIN LOGIN / AUTH ==========

async function submitLogin() {
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const btn = document.getElementById('loginBtn');
    const btnText = document.getElementById('loginBtnText');

    if (!username || !password) {
        showLoginAlert('Please enter both username and password.', 'err');
        return;
    }

    btn.disabled = true;
    btnText.innerHTML = '&#9203;&nbsp; Logging in...';

    try {
        const response = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('spartha_user', data.username);
            btnText.innerHTML = '&#10003;&nbsp; Success!';
            const overlay = document.getElementById('loginOverlay');
            overlay.style.transition = 'opacity 0.55s ease, transform 0.55s ease';
            overlay.style.opacity = '0';
            overlay.style.transform = 'scale(1.02)';
            setTimeout(() => { overlay.style.display = 'none'; }, 560);
        } else {
            const err = await response.json();
            showLoginAlert('&#10060; ' + (err.detail || 'Invalid username or password'), 'err');
            btn.disabled = false;
            btnText.innerHTML = '&#128640;&nbsp; Login to Dashboard';
            // Shake animation on error
            const inputWrap = document.getElementById('loginPassword').closest('.lp-form-wrap');
            inputWrap.style.animation = 'none';
            document.getElementById('loginPassword').style.borderColor = '#c93030';
            setTimeout(() => { document.getElementById('loginPassword').style.borderColor = ''; }, 1200);
        }
    } catch (e) {
        showLoginAlert('&#10060; Could not connect to server. Is the backend running?', 'err');
        btn.disabled = false;
        btnText.innerHTML = '&#128640;&nbsp; Login to Dashboard';
    }
}

function showLoginAlert(message, type) {
    const el = document.getElementById('loginAlert');
    el.style.display = 'block';
    el.className = 'lp-alert ' + type;
    el.innerHTML = message;
}

function toggleLoginPassword() {
    const input = document.getElementById('loginPassword');
    const icon = document.getElementById('eyeIcon');
    if (input.type === 'password') {
        input.type = 'text';
        icon.innerHTML = '&#128683;';
    } else {
        input.type = 'password';
        icon.innerHTML = '&#128065;';
    }
}

// Check cookie validity on page load
document.addEventListener('DOMContentLoaded', async () => {
    const overlay = document.getElementById('loginOverlay');
    if (!overlay) return;
    try {
        const response = await fetch(`${API_BASE}/credentials`, { credentials: 'include' });
        if (response.ok) {
            overlay.style.display = 'none';
            loadStatistics(); 
        }
    } catch (e) { /* network error — show login */ }
});

// Logout — clears HttpOnly cookie via server
window.logout = function() {
    if (confirm('Are you sure you want to logout?')) {
        fetch(`${API_BASE}/logout`, { method: 'POST', credentials: 'include' })
            .finally(() => { localStorage.removeItem('spartha_user'); location.reload(); });
    }
};

// Change credentials modal
function openChangeCredModal() {
    const modal = document.getElementById('changeCredModal');
    modal.classList.add('open');
    document.getElementById('changeCredAlert').style.display = 'none';
    document.getElementById('cc_current_username').value = localStorage.getItem('spartha_user') || '';
    document.getElementById('cc_current_password').value = '';
    document.getElementById('cc_new_username').value = '';
    document.getElementById('cc_new_password').value = '';
}

function closeChangeCredModal() {
    document.getElementById('changeCredModal').classList.remove('open');
}

async function submitChangeCredentials() {
    const currentUsername = document.getElementById('cc_current_username').value.trim();
    const currentPassword = document.getElementById('cc_current_password').value;
    const newUsername = document.getElementById('cc_new_username').value.trim();
    const newPassword = document.getElementById('cc_new_password').value;
    const alertEl = document.getElementById('changeCredAlert');

    if (!currentUsername || !currentPassword) {
        alertEl.style.display = 'block';
        alertEl.className = 'alert alert-error';
        alertEl.textContent = 'Current username and password are required.';
        return;
    }
    if (!newUsername && !newPassword) {
        alertEl.style.display = 'block';
        alertEl.className = 'alert alert-error';
        alertEl.textContent = 'Provide a new username and/or new password to update.';
        return;
    }

    try {
        const response = await apiFetch('/credentials', {
            method: 'PUT',
            body: JSON.stringify({
                current_username: currentUsername,
                current_password: currentPassword,
                new_username: newUsername || null,
                new_password: newPassword || null
            })
        });

        if (response.ok) {
            alertEl.style.display = 'block';
            alertEl.className = 'alert alert-success';
            alertEl.textContent = '✅ Credentials updated! Please log in again.';
            setTimeout(() => {
                closeChangeCredModal();
                fetch(`${API_BASE}/logout`, { method: 'POST', credentials: 'include' })
                    .finally(() => { localStorage.removeItem('spartha_user'); location.reload(); });
            }, 1500);
        } else {
            const err = await response.json();
            alertEl.style.display = 'block';
            alertEl.className = 'alert alert-error';
            alertEl.textContent = '❌ ' + (err.detail || 'Failed to update credentials');
        }
    } catch (e) {
        alertEl.style.display = 'block';
        alertEl.className = 'alert alert-error';
        alertEl.textContent = '❌ Could not connect to server.';
    }
}
// =============================================
// POPUP ANNOUNCEMENTS MANAGEMENT
// =============================================

let editingPopupId = null;

async function loadPopupAnnouncements() {
    try {
        const response = await apiFetch('/announcement-popups');
        if (!response) return;
        if (!response.ok) throw new Error('Failed to fetch popup announcements');
        const data = await response.json();
        renderPopupTable(data);
    } catch (error) {
        console.error('Error loading popup announcements:', error);
        showAlert('popupAlert', '❌ Error loading popup announcements', 'error');
    }
}

function renderPopupTable(popups) {
    const tbody = document.getElementById('popupTableBody');
    if (!tbody) return;
    if (!popups || popups.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:2rem;color:#64748b;">No popup announcements yet. Create one above.</td></tr>`;
        return;
    }
    tbody.innerHTML = popups.map(p => {
        const dateStr = p.created_at
            ? new Date(p.created_at).toLocaleDateString('en-PH', { year: 'numeric', month: 'short', day: 'numeric' })
            : 'N/A';
        const statusBadge = p.is_active
            ? `<span style="background:#d1fae5;color:#065f46;padding:2px 10px;border-radius:20px;font-size:0.78rem;font-weight:700;">Active</span>`
            : `<span style="background:#f1f5f9;color:#64748b;padding:2px 10px;border-radius:20px;font-size:0.78rem;font-weight:700;">Inactive</span>`;
        const imgPreview = p.image_data
            ? `<img src="${p.image_data}" alt="" style="width:36px;height:36px;object-fit:cover;border-radius:6px;vertical-align:middle;margin-right:6px;">`
            : '';
        return `<tr>
            <td>${imgPreview}<strong>${escapeHtml(p.title)}</strong></td>
            <td>${escapeHtml(p.category)}</td>
            <td>${p.image_data ? '<span style="color:#065f46;">✅ Yes</span>' : '<span style="color:#94a3b8;">— No</span>'}</td>
            <td style="text-align:center;">${p.priority}</td>
            <td>${statusBadge}</td>
            <td style="font-size:0.82rem;color:#64748b;">${dateStr}</td>
            <td>
                <button class="btn btn-small" onclick="editPopupAnn(${p.id})" style="margin-right:4px;">✏️ Edit</button>
                <button class="btn btn-small" style="background:#6366f1;color:#fff;margin-right:4px;" onclick="togglePopupAnn(${p.id})">${p.is_active ? '🔕 Hide' : '🔔 Show'}</button>
                <button class="btn btn-small btn-danger" onclick="deletePopupAnn(${p.id})">🗑️</button>
            </td>
        </tr>`;
    }).join('');
}

async function submitPopupForm(event) {
    event.preventDefault();
    const fd = new FormData();
    fd.append('title', document.getElementById('popup_title').value.trim());
    fd.append('content', document.getElementById('popup_content').value.trim());
    fd.append('category', document.getElementById('popup_category').value);
    fd.append('is_active', document.getElementById('popup_is_active').value);
    fd.append('priority', document.getElementById('popup_priority').value || '0');
    const imgFile = document.getElementById('popup_image').files[0];
    if (imgFile) fd.append('image', imgFile);
    const url = editingPopupId ? `/announcement-popups/${editingPopupId}` : `/announcement-popups`;
    const method = editingPopupId ? 'PUT' : 'POST';
    try {
        const response = await apiFetchForm(url, { method, body: fd });
        if (!response) return;
        if (!response.ok) { const err = await response.json(); throw new Error(err.detail || 'Error saving popup'); }
        showAlert('popupAlert', editingPopupId ? '✅ Popup updated!' : '✅ Popup created!', 'success');
        resetPopupForm();
        loadPopupAnnouncements();
    } catch (error) {
        showAlert('popupAlert', '❌ ' + error.message, 'error');
    }
}

function resetPopupForm() {
    editingPopupId = null;
    document.getElementById('popupForm').reset();
    document.getElementById('popup_image_preview').style.display = 'none';
    const btn = document.querySelector('#popupForm .btn');
    if (btn) btn.textContent = '✓ Save Popup Announcement';
}

async function editPopupAnn(id) {
    try {
        const response = await apiFetch('/announcement-popups');
        if (!response) return;
        const all = await response.json();
        const popup = all.find(p => p.id === id);
        if (!popup) return;
        editingPopupId = id;
        document.getElementById('popup_title').value = popup.title || '';
        document.getElementById('popup_content').value = popup.content || '';
        document.getElementById('popup_category').value = popup.category || 'General';
        document.getElementById('popup_is_active').value = popup.is_active ? 'true' : 'false';
        document.getElementById('popup_priority').value = popup.priority || 0;
        if (popup.image_data) {
            document.getElementById('popup_preview_img').src = popup.image_data;
            document.getElementById('popup_image_preview').style.display = 'block';
        } else {
            document.getElementById('popup_image_preview').style.display = 'none';
        }
        const btn = document.querySelector('#popupForm .btn');
        if (btn) btn.textContent = '✓ Update Popup Announcement';
        document.getElementById('popupAnnouncements').scrollIntoView({ behavior: 'smooth' });
    } catch (error) { console.error('Error loading popup for edit:', error); }
}

async function togglePopupAnn(id) {
    try {
        const response = await apiFetch(`/announcement-popups/${id}/toggle`, { method: 'PATCH' });
        if (!response.ok) throw new Error('Toggle failed');
        loadPopupAnnouncements();
    } catch (error) { showAlert('popupAlert', '❌ Error toggling popup status', 'error'); }
}

async function deletePopupAnn(id) {
    if (!confirm('Delete this popup announcement? This cannot be undone.')) return;
    try {
        const response = await apiFetch(`/announcement-popups/${id}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Delete failed');
        loadPopupAnnouncements();
    } catch (error) { showAlert('popupAlert', '❌ Error deleting popup', 'error'); }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

document.addEventListener('DOMContentLoaded', function () {
    const imgInput = document.getElementById('popup_image');
    if (imgInput) {
        imgInput.addEventListener('change', function () {
            const file = this.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = e => {
                    document.getElementById('popup_preview_img').src = e.target.result;
                    document.getElementById('popup_image_preview').style.display = 'block';
                };
                reader.readAsDataURL(file);
            } else {
                document.getElementById('popup_image_preview').style.display = 'none';
            }
        });
    }
    const popupForm = document.getElementById('popupForm');
    if (popupForm) popupForm.addEventListener('submit', submitPopupForm);
});
// ========== AUTHORITY PHOTO HELPER ==========
function clearAuthorityPhoto() {
    document.getElementById('auth_photo').value = '';
    document.getElementById('auth_photo_preview').style.display = 'none';
}
window.clearAuthorityPhoto = clearAuthorityPhoto;

// ========== STATISTICS ==========
async function loadStatistics() {
    try {
        const response = await apiFetch('/statistics');
        if (!response || !response.ok) {
            showAlert('statsAlert', '❌ Could not load statistics. Make sure the /api/admin/statistics endpoint exists.', 'error');
            return;
        }
        const data = await response.json();

        // Summary cards
        document.getElementById('statTotalQueries').textContent = data.total_queries ?? '—';
        document.getElementById('statTodayQueries').textContent = data.today_queries ?? '—';
        const avgConf = data.avg_confidence != null ? (data.avg_confidence * 100).toFixed(0) + '%' : '—';
        document.getElementById('statAvgConf').textContent = avgConf;
        document.getElementById('statTopIntent').textContent =
            data.top_intent ? data.top_intent.replace('_query', '').replace('_', ' ') : '—';

        // Intent chart (horizontal bars)
        const intentDiv = document.getElementById('intentChart');
        if (data.intent_breakdown && data.intent_breakdown.length) {
            const max = Math.max(...data.intent_breakdown.map(i => i.count));
            intentDiv.innerHTML = data.intent_breakdown.map(item => {
                const pct = max > 0 ? (item.count / max * 100).toFixed(0) : 0;
                const label = item.intent.replace('_query','').replace(/_/g,' ');
                return `<div style="margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#475569;margin-bottom:3px;">
                        <span style="text-transform:capitalize;">${label}</span><span><strong>${item.count}</strong></span>
                    </div>
                    <div style="background:#e2e8f0;border-radius:99px;height:10px;overflow:hidden;">
                        <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#c41e3a,#9b1530);border-radius:99px;transition:width 0.6s ease;"></div>
                    </div>
                </div>`;
            }).join('');
        } else {
            intentDiv.innerHTML = '<p style="color:#94a3b8;font-size:0.85rem;">No data yet.</p>';
        }

        // Top entities chart
        const entityDiv = document.getElementById('entityChart');
        if (data.top_entities && data.top_entities.length) {
            const maxE = Math.max(...data.top_entities.map(e => e.count));
            entityDiv.innerHTML = data.top_entities.map(item => {
                const pct = maxE > 0 ? (item.count / maxE * 100).toFixed(0) : 0;
                return `<div style="margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#475569;margin-bottom:3px;">
                        <span>${item.entity}</span><span><strong>${item.count}</strong></span>
                    </div>
                    <div style="background:#e2e8f0;border-radius:99px;height:10px;overflow:hidden;">
                        <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#3b82f6,#1d4ed8);border-radius:99px;transition:width 0.6s ease;"></div>
                    </div>
                </div>`;
            }).join('');
        } else {
            entityDiv.innerHTML = '<p style="color:#94a3b8;font-size:0.85rem;">No data yet.</p>';
        }

        // Recent queries table
        const tbody = document.getElementById('recentQueriesBody');
        if (data.recent_queries && data.recent_queries.length) {
            tbody.innerHTML = data.recent_queries.map(q => {
                const conf = q.confidence != null ? (q.confidence * 100).toFixed(0) + '%' : '—';
                const confColor = q.confidence > 0.7 ? '#10b981' : q.confidence > 0.4 ? '#f59e0b' : '#ef4444';
                const intent = (q.intent || '—').replace('_query','').replace(/_/g,' ');
                const dt = q.searched_at ? new Date(q.searched_at).toLocaleString('en-PH', {
                    month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—';
                return `<tr>
                    <td>${escapeHtml(q.query)}</td>
                    <td style="text-transform:capitalize;">${intent}</td>
                    <td style="color:${confColor};font-weight:600;">${conf}</td>
                    <td>${q.language === 'tl' ? '🇵🇭 Filipino' : '🇺🇸 English'}</td>
                    <td style="color:#64748b;font-size:0.82rem;">${dt}</td>
                </tr>`;
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:2rem;">No queries logged yet.</td></tr>';
        }
    } catch (err) {
        console.error('Statistics error:', err);
        showAlert('statsAlert', '❌ Error loading statistics: ' + err.message, 'error');
    }
}
window.loadStatistics = loadStatistics;

// Load stats automatically when statistics tab is opened
const _origSwitchTab = window.switchTab;
window.switchTab = function(tabName, event) {
    if (_origSwitchTab) _origSwitchTab(tabName, event);
    if (tabName === 'statistics') {
        loadStatistics();
        loadNavigationStatistics();
    }
};
// ========== EDIT ORGANIZATION MODAL ==========

function openEditOrgModal(orgId, orgName, orgDescription) {
    // Remove existing modal if any
    const existing = document.getElementById('editOrgModal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'editOrgModal';
    modal.style.cssText = 'position:fixed;inset:0;z-index:10001;display:flex;align-items:center;justify-content:center;background:rgba(15,20,40,0.65);backdrop-filter:blur(5px);font-family:Poppins,sans-serif;';
    modal.innerHTML = `
        <div style="background:#fff;border-radius:20px;width:100%;max-width:500px;margin:1rem;box-shadow:0 20px 60px rgba(0,0,0,0.25);overflow:hidden;animation:cardSlideUp 0.35s cubic-bezier(0.22,1,0.36,1) both;">
            <!-- Header -->
            <div style="background:linear-gradient(135deg,#c93030 0%,#a32020 100%);padding:1.5rem 2rem;position:relative;overflow:hidden;">
                <div style="position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:repeating-linear-gradient(45deg,transparent,transparent 10px,rgba(255,255,255,0.04) 10px,rgba(255,255,255,0.04) 20px);animation:headerPattern 20s linear infinite;"></div>
                <div style="position:relative;z-index:1;display:flex;align-items:center;gap:1rem;">
                    <div style="width:44px;height:44px;border-radius:50%;background:rgba(255,255,255,0.15);border:2px solid rgba(255,255,255,0.3);display:flex;align-items:center;justify-content:center;font-size:1.3rem;flex-shrink:0;">✏️</div>
                    <div style="flex:1;">
                        <div style="font-family:'Bebas Neue',sans-serif;font-size:1.4rem;letter-spacing:2px;color:#fff;">Edit Organization</div>
                        <div style="font-size:0.8rem;color:rgba(255,255,255,0.8);">Update name and description</div>
                    </div>
                    <button onclick="closeEditOrgModal()" style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.25);border-radius:50%;width:34px;height:34px;color:#fff;cursor:pointer;font-size:0.9rem;display:flex;align-items:center;justify-content:center;transition:all 0.2s;flex-shrink:0;" onmouseover="this.style.background='rgba(255,255,255,0.25)'" onmouseout="this.style.background='rgba(255,255,255,0.15)'">✕</button>
                </div>
            </div>
            <!-- Body -->
            <div style="padding:2rem;">
                <div id="editOrgAlert" style="display:none;margin-bottom:1rem;padding:0.9rem 1.2rem;border-radius:10px;font-size:0.875rem;font-weight:500;"></div>
                <div style="margin-bottom:1.2rem;">
                    <label style="display:block;font-weight:600;font-size:0.875rem;color:#1a202c;margin-bottom:0.5rem;">Organization Name *</label>
                    <input id="editOrgName" type="text" value="${orgName.replace(/"/g, '&quot;')}" style="width:100%;padding:0.85rem 1.1rem;border:2px solid #e2e8f0;border-radius:12px;font-size:0.95rem;font-family:Poppins,sans-serif;color:#1a202c;outline:none;transition:all 0.3s;box-sizing:border-box;" onfocus="this.style.borderColor='#c93030';this.style.boxShadow='0 0 0 4px rgba(201,48,48,0.1)'" onblur="this.style.borderColor='#e2e8f0';this.style.boxShadow='none'">
                </div>
                <div style="margin-bottom:1.5rem;">
                    <label style="display:block;font-weight:600;font-size:0.875rem;color:#1a202c;margin-bottom:0.5rem;">Description</label>
                    <textarea id="editOrgDescription" rows="3" style="width:100%;padding:0.85rem 1.1rem;border:2px solid #e2e8f0;border-radius:12px;font-size:0.95rem;font-family:Poppins,sans-serif;color:#1a202c;outline:none;resize:vertical;transition:all 0.3s;box-sizing:border-box;" onfocus="this.style.borderColor='#c93030';this.style.boxShadow='0 0 0 4px rgba(201,48,48,0.1)'" onblur="this.style.borderColor='#e2e8f0';this.style.boxShadow='none'">${orgDescription}</textarea>
                </div>
                <div style="display:flex;gap:1rem;">
                    <button onclick="submitEditOrg(${orgId})" style="flex:1;padding:0.9rem;background:linear-gradient(135deg,#c93030,#a32020);color:#fff;border:none;border-radius:12px;font-size:0.95rem;font-weight:700;font-family:Poppins,sans-serif;cursor:pointer;box-shadow:0 4px 15px rgba(201,48,48,0.35);transition:all 0.3s;" onmouseover="this.style.transform='translateY(-2px)'" onmouseout="this.style.transform='none'">✓ Save Changes</button>
                    <button onclick="closeEditOrgModal()" style="flex:1;padding:0.9rem;background:#f1f5f9;color:#475569;border:2px solid #e2e8f0;border-radius:12px;font-size:0.95rem;font-weight:600;font-family:Poppins,sans-serif;cursor:pointer;transition:all 0.3s;" onmouseover="this.style.background='#e2e8f0'" onmouseout="this.style.background='#f1f5f9'">Cancel</button>
                </div>
            </div>
        </div>`;
    modal.addEventListener('click', e => { if (e.target === modal) closeEditOrgModal(); });
    document.body.appendChild(modal);
}

function closeEditOrgModal() {
    const m = document.getElementById('editOrgModal');
    if (m) m.remove();
}

async function submitEditOrg(orgId) {
    const name = document.getElementById('editOrgName').value.trim();
    const description = document.getElementById('editOrgDescription').value.trim();
    const alertEl = document.getElementById('editOrgAlert');

    if (!name) {
        alertEl.textContent = '❌ Organization name is required.';
        alertEl.style.display = 'block';
        alertEl.style.background = 'rgba(201,48,48,0.08)';
        alertEl.style.border = '1px solid rgba(201,48,48,0.25)';
        alertEl.style.color = '#a32020';
        return;
    }

    try {
        const response = await apiFetch(`/organizations/${orgId}`, {
            method: 'PUT',
            body: JSON.stringify({ name, description: description || null })
        });

        if (response && response.ok) {
            closeEditOrgModal();
            showAlert('orgchartAlert', '✅ Organization updated successfully!', 'success');
            loadOrganizations();
            // Refresh member section header if open
            if (selectedOrgId === orgId) {
                document.getElementById('selectedOrgName').textContent = name;
                document.getElementById('selectedOrgNameMembers').textContent = name;
            }
        } else {
            const err = response ? await response.json() : {};
            alertEl.textContent = '❌ ' + (err.detail || 'Error updating organization');
            alertEl.style.display = 'block';
            alertEl.style.background = 'rgba(201,48,48,0.08)';
            alertEl.style.border = '1px solid rgba(201,48,48,0.25)';
            alertEl.style.color = '#a32020';
        }
    } catch (e) {
        alertEl.textContent = '❌ Error updating organization';
        alertEl.style.display = 'block';
    }
}

// ========== EDIT MEMBER MODAL ==========

function openEditMemberModal(memberId, memberName, memberPosition) {
    const existing = document.getElementById('editMemberModal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'editMemberModal';
    modal.style.cssText = 'position:fixed;inset:0;z-index:10001;display:flex;align-items:center;justify-content:center;background:rgba(15,20,40,0.65);backdrop-filter:blur(5px);font-family:Poppins,sans-serif;';
    modal.innerHTML = `
        <div style="background:#fff;border-radius:20px;width:100%;max-width:460px;margin:1rem;box-shadow:0 20px 60px rgba(0,0,0,0.25);overflow:hidden;animation:cardSlideUp 0.35s cubic-bezier(0.22,1,0.36,1) both;">
            <div style="background:linear-gradient(135deg,#c93030 0%,#a32020 100%);padding:1.4rem 2rem;position:relative;overflow:hidden;">
                <div style="position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:repeating-linear-gradient(45deg,transparent,transparent 10px,rgba(255,255,255,0.04) 10px,rgba(255,255,255,0.04) 20px);animation:headerPattern 20s linear infinite;"></div>
                <div style="position:relative;z-index:1;display:flex;align-items:center;gap:1rem;">
                    <div style="width:44px;height:44px;border-radius:50%;background:rgba(255,255,255,0.15);border:2px solid rgba(255,255,255,0.3);display:flex;align-items:center;justify-content:center;font-size:1.3rem;flex-shrink:0;">👤</div>
                    <div style="flex:1;">
                        <div style="font-family:'Bebas Neue',sans-serif;font-size:1.4rem;letter-spacing:2px;color:#fff;">Edit Member</div>
                        <div style="font-size:0.8rem;color:rgba(255,255,255,0.8);">Update name and position</div>
                    </div>
                    <button onclick="closeEditMemberModal()" style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.25);border-radius:50%;width:34px;height:34px;color:#fff;cursor:pointer;font-size:0.9rem;display:flex;align-items:center;justify-content:center;transition:all 0.2s;flex-shrink:0;" onmouseover="this.style.background='rgba(255,255,255,0.25)'" onmouseout="this.style.background='rgba(255,255,255,0.15)'">✕</button>
                </div>
            </div>
            <div style="padding:2rem;">
                <div id="editMemberAlert" style="display:none;margin-bottom:1rem;padding:0.9rem 1.2rem;border-radius:10px;font-size:0.875rem;font-weight:500;"></div>
                <div style="margin-bottom:1.2rem;">
                    <label style="display:block;font-weight:600;font-size:0.875rem;color:#1a202c;margin-bottom:0.5rem;">Member Name *</label>
                    <input id="editMemberName" type="text" value="${memberName.replace(/"/g, '&quot;')}" style="width:100%;padding:0.85rem 1.1rem;border:2px solid #e2e8f0;border-radius:12px;font-size:0.95rem;font-family:Poppins,sans-serif;color:#1a202c;outline:none;transition:all 0.3s;box-sizing:border-box;" onfocus="this.style.borderColor='#c93030';this.style.boxShadow='0 0 0 4px rgba(201,48,48,0.1)'" onblur="this.style.borderColor='#e2e8f0';this.style.boxShadow='none'">
                </div>
                <div style="margin-bottom:1.5rem;">
                    <label style="display:block;font-weight:600;font-size:0.875rem;color:#1a202c;margin-bottom:0.5rem;">Position *</label>
                    <input id="editMemberPosition" type="text" value="${memberPosition.replace(/"/g, '&quot;')}" style="width:100%;padding:0.85rem 1.1rem;border:2px solid #e2e8f0;border-radius:12px;font-size:0.95rem;font-family:Poppins,sans-serif;color:#1a202c;outline:none;transition:all 0.3s;box-sizing:border-box;" onfocus="this.style.borderColor='#c93030';this.style.boxShadow='0 0 0 4px rgba(201,48,48,0.1)'" onblur="this.style.borderColor='#e2e8f0';this.style.boxShadow='none'">
                </div>
                <div style="display:flex;gap:1rem;">
                    <button onclick="submitEditMember(${memberId})" style="flex:1;padding:0.9rem;background:linear-gradient(135deg,#c93030,#a32020);color:#fff;border:none;border-radius:12px;font-size:0.95rem;font-weight:700;font-family:Poppins,sans-serif;cursor:pointer;box-shadow:0 4px 15px rgba(201,48,48,0.35);transition:all 0.3s;" onmouseover="this.style.transform='translateY(-2px)'" onmouseout="this.style.transform='none'">✓ Save Changes</button>
                    <button onclick="closeEditMemberModal()" style="flex:1;padding:0.9rem;background:#f1f5f9;color:#475569;border:2px solid #e2e8f0;border-radius:12px;font-size:0.95rem;font-weight:600;font-family:Poppins,sans-serif;cursor:pointer;transition:all 0.3s;" onmouseover="this.style.background='#e2e8f0'" onmouseout="this.style.background='#f1f5f9'">Cancel</button>
                </div>
            </div>
        </div>`;
    modal.addEventListener('click', e => { if (e.target === modal) closeEditMemberModal(); });
    document.body.appendChild(modal);
}

function closeEditMemberModal() {
    const m = document.getElementById('editMemberModal');
    if (m) m.remove();
}

async function submitEditMember(memberId) {
    const name = document.getElementById('editMemberName').value.trim();
    const position = document.getElementById('editMemberPosition').value.trim();
    const alertEl = document.getElementById('editMemberAlert');

    if (!name || !position) {
        alertEl.textContent = '❌ Name and position are required.';
        alertEl.style.display = 'block';
        alertEl.style.background = 'rgba(201,48,48,0.08)';
        alertEl.style.border = '1px solid rgba(201,48,48,0.25)';
        alertEl.style.color = '#a32020';
        return;
    }

    try {
        const response = await apiFetch(`/members/${memberId}`, {
            method: 'PUT',
            body: JSON.stringify({ name, position })
        });

        if (response && response.ok) {
            closeEditMemberModal();
            showAlert('memberAlert', '✅ Member updated successfully!', 'success');
            loadMembers(selectedOrgId);
            loadOrganizations();
        } else {
            const err = response ? await response.json() : {};
            alertEl.textContent = '❌ ' + (err.detail || 'Error updating member');
            alertEl.style.display = 'block';
            alertEl.style.background = 'rgba(201,48,48,0.08)';
            alertEl.style.border = '1px solid rgba(201,48,48,0.25)';
            alertEl.style.color = '#a32020';
        }
    } catch (e) {
        alertEl.textContent = '❌ Error updating member';
        alertEl.style.display = 'block';
    }
}