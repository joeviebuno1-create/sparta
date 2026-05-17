// ============ GLOBAL API HOST ============
const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const API_HOST = isLocal
    ? `http://localhost:8000`
    : `https://sparta-production-0acb.up.railway.app`;

// ============ STATE ============
let locations = [];
let routes = [];
let allPathMeshes = []; // persistent — all manually created paths shown on load
let favorites = JSON.parse(localStorage.getItem('spartha_favs') || '[]');
let activeTypeFilter = 'all';
let activeFloorFilter = 'all';
let selectedLocation = null;

// Store model transformation info for debugging
let modelTransformation = {
    center: null,
    scale: 1,
    originalBounds: null
};

// ============ 3D
let scene, camera, renderer, controls, campusModel;
let currentMarker = null;
let pathLines = [];
let pathParticles = [];
let evacMarkers = [], evacPathLines = [];
let animationFrameId = null;

// ============ WAYPOINTS - Define strategic points for pathfinding ============
// These are sample waypoints - you should adjust these based on your actual campus layout
const campusWaypoints = [
    { id: 'entrance', pos: new THREE.Vector3(0, 0, -80), name: 'Main Entrance' },
    { id: 'plaza', pos: new THREE.Vector3(0, 0, -20), name: 'Central Plaza' },
    { id: 'north-corridor', pos: new THREE.Vector3(0, 0, 30), name: 'North Corridor' },
    { id: 'east-wing', pos: new THREE.Vector3(40, 0, 0), name: 'East Wing' },
    { id: 'west-wing', pos: new THREE.Vector3(-40, 0, 0), name: 'West Wing' },
    { id: 'south-corridor', pos: new THREE.Vector3(0, 0, -50), name: 'South Corridor' }
];

// ============ WAYPOINT PARSER ============
// Handles every format the admin panel stores: {x,y,z}, {x,z}, null-y, arrays, strings.
// y is always optional — defaults to 0 (flat campus ground plane).
function _parseWaypoint(wp) {
    if (wp == null) return null;
    // Unwrap common wrapper keys
    if (typeof wp === 'object' && !Array.isArray(wp)) {
        if (wp.position && typeof wp.position === 'object') wp = wp.position;
        else if (wp.point && typeof wp.point === 'object') wp = wp.point;
    }
    let x, y = 0, z;
    if (Array.isArray(wp)) {
        x = parseFloat(wp[0]);
        if (wp.length >= 3) { y = isNaN(parseFloat(wp[1])) ? 0 : parseFloat(wp[1]); z = parseFloat(wp[2]); }
        else { z = parseFloat(wp[1]); }
    } else if (typeof wp === 'object') {
        x = parseFloat(wp.x);
        z = parseFloat(wp.z);
        const rawY = parseFloat(wp.y);
        y = isNaN(rawY) ? 0 : rawY;
    } else if (typeof wp === 'number') {
        const loc = locations.find(l => l.id === wp);
        if (loc && loc.coordinates) return new THREE.Vector3(parseFloat(loc.coordinates.x)||0, parseFloat(loc.coordinates.y)||0, parseFloat(loc.coordinates.z)||0);
        return null;
    } else if (typeof wp === 'string') {
        try { return _parseWaypoint(JSON.parse(wp)); } catch(e) { return null; }
    } else { return null; }
    if (isNaN(x) || isNaN(z)) return null;
    return new THREE.Vector3(x, y, z);
}

// Parse a raw waypoints value (string, array, object-with-numeric-keys) into Vector3[].
function _parseWaypointArray(raw) {
    if (!raw) return [];
    let arr = raw;
    for (let i = 0; i < 2; i++) {
        if (typeof arr === 'string') { try { arr = JSON.parse(arr); } catch(e) { return []; } }
        else break;
    }
    if (!Array.isArray(arr)) {
        if (typeof arr === 'object') arr = Object.keys(arr).sort((a,b)=>+a-+b).map(k=>arr[k]);
        else return [];
    }
    const pts = [];
    for (const wp of arr) {
        const v = _parseWaypoint(wp);
        if (v) pts.push(v);
        else console.warn('[navigator] Skipped waypoint:', JSON.stringify(wp));
    }
    return pts;
}

// Return waypoint count from a raw route.waypoints (handles string or array).
function _waypointCount(raw) {
    if (!raw) return 0;
    if (Array.isArray(raw)) return raw.length;
    if (typeof raw === 'string') { try { const p = JSON.parse(raw); return Array.isArray(p) ? p.length : 0; } catch(e) { return 0; } }
    return 0;
}

// ============ PATHFINDING - Simple A* implementation ============

// ============ LOAD DATA ============
async function loadLocationsFromAPI() {
    try {
        const res = await fetch(`${API_HOST}/room-locations`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        locations = data.map(loc => {
            // Parse coordinates properly - handle both string JSON and object formats
            let coords = { x: 0, y: 0, z: 0 };
            if (loc.coordinates) {
                if (typeof loc.coordinates === 'string') {
                    try {
                        coords = JSON.parse(loc.coordinates);
                    } catch(e) {
                        console.warn(`Failed to parse coordinates for ${loc.name}:`, e);
                    }
                } else if (typeof loc.coordinates === 'object') {
                    coords = {
                        x: parseFloat(loc.coordinates.x) || 0,
                        y: parseFloat(loc.coordinates.y) || 0,
                        z: parseFloat(loc.coordinates.z) || 0
                    };
                }
            }
            
            return {
                id: loc.id, 
                name: loc.name, 
                building: loc.building,
                floor: loc.floor, 
                type: loc.type, 
                icon: loc.icon || '📍',
                coordinates: coords,
                capacity: loc.capacity, 
                description: loc.description,
                accessible: loc.description && loc.description.toLowerCase().includes('accessible'),
                isExit: loc.type && (loc.type.toLowerCase().includes('exit') || loc.type.toLowerCase().includes('entrance') || loc.name.toLowerCase().includes('gate') || loc.name.toLowerCase().includes('entrance') || loc.name.toLowerCase().includes('exit'))
            };
        });
        console.log(`✅ Loaded ${locations.length} locations from /room-locations`);
        console.log('Sample location with coords:', locations[0]);
        buildFilterPills();
        buildFloorPills();
        renderLocationsList();
        renderFavorites();
        renderEvacExits();
        renderNearby();
    } catch(e) {
        console.error('Error loading locations:', e);
        locations = [];
        renderLocationsList();
    }
    
}

async function loadRoutesFromAPI() {
    try {
        const res = await fetch(`${API_HOST}/navigation-routes`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        routes = data;
        console.log(`✅ Loaded ${routes.length} navigation routes from /navigation-routes`);
    } catch(e) {
        console.error('Error loading routes:', e);
        routes = [];
    }
}

// ============ FORMAT DESCRIPTION ============
function formatDescription(text) {
    if (!text) return '';

    // Detect org-chart style: "Role: Name" pairs separated by colons
    const hasRolePairs = /(?<![A-Za-z]\.):\s*(?:Dr|Mr|Ms|Engr|Asst|Assoc|Prof|Atty|Arch)\./.test(text);

    if (!hasRolePairs) {
        // Plain text — split into sentences
        const sentences = text.match(/[^.!?]+[.!?]?/g)?.map(s => s.trim()).filter(Boolean) || [text];
        if (sentences.length <= 1) return `<span>${text}</span>`;
        return sentences.map(s => `<div class="desc-sentence">${s}</div>`).join('');
    }

    // ── Org-chart mode ──────────────────────────────────────────────────────
    // Split on ':' that immediately precede a name-prefix abbreviation,
    // but NOT when the character before ':' is itself an abbreviation dot.
    // Each chunk after split = "Name [NextRoleLabel]"
    const SPLIT_RE = /(?<![A-Za-z]\.):\s*(?=(?:Dr|Mr|Ms|Engr|Asst|Assoc|Prof|Atty|Arch)\.)/g;
    const SECTION_HEADERS = ['Top Administration', 'College Leadership', 'Coordinators'];

    // Extract a person's name from the START of a chunk.
    // Name = [Title(s)] [FirstName] [SecondFirstName?] [MiddleInitial?] [Particle?] [LastName]
    function extractName(chunk) {
        const tokens = chunk.split(/\s+/);
        let i = 0, nameTokens = [];

        // Title abbreviations (end with '.')
        while (i < tokens.length && /^(?:Asst|Assoc|Prof|Engr|Dr|Mr|Ms|Atty|Arch|Sr|Jr)\.$/.test(tokens[i])) {
            nameTokens.push(tokens[i++]);
        }

        // First name(s): up to 2 purely capitalized words (e.g. "Rey Anthony")
        let firstNames = 0;
        while (i < tokens.length && firstNames < 2) {
            if (/^[A-Z][a-z]+$/.test(tokens[i])) { nameTokens.push(tokens[i++]); firstNames++; }
            else break;
        }
        if (firstNames === 0) return { name: nameTokens.join(' '), rest: tokens.slice(i).join(' ') };

        // Middle initial (single capital + dot, e.g. "A.")
        if (i < tokens.length && /^[A-Z]\.$/.test(tokens[i])) {
            nameTokens.push(tokens[i++]);
        }

        // Name particle (de, van, del, la, etc.)
        if (i < tokens.length && /^(?:de|van|del|der|den|la|le)$/i.test(tokens[i])) {
            nameTokens.push(tokens[i++]);
        }

        // Last name (capitalized, possibly hyphenated like "Ramirez-Latade")
        if (i < tokens.length && /^[A-Z][a-zA-Z']+(-[A-Z][a-zA-Z]+)?$/.test(tokens[i])) {
            nameTokens.push(tokens[i++]);
        }

        return { name: nameTokens.join(' '), rest: tokens.slice(i).join(' ') };
    }

    const parts = text.split(SPLIT_RE);

    // part[0] = intro sentences + first role label
    let p0 = parts[0], introText = p0, firstRole = null;
    for (const hdr of SECTION_HEADERS) {
        const idx = p0.indexOf(hdr);
        if (idx >= 0) {
            introText = p0.substring(0, idx).trim().replace(/\.$/, '');
            firstRole = p0.substring(idx).trim();
            break;
        }
    }
    if (!firstRole) {
        const lp = p0.lastIndexOf('. ');
        if (lp > 0) {
            introText = p0.substring(0, lp + 1).trim();
            firstRole = p0.substring(lp + 2).trim();
        } else {
            introText = '';
            firstRole = p0.trim();
        }
    }

    const entries = [];
    if (introText) entries.push({ type: 'intro', text: introText });

    let pendingRole = firstRole;
    for (let i = 1; i < parts.length; i++) {
        const { name, rest } = extractName(parts[i].trim());
        entries.push({ type: 'entry', role: pendingRole || '', name });
        pendingRole = rest || null;
    }
    if (pendingRole) entries.push({ type: 'entry', role: pendingRole, name: '' });

    return entries.map(e => {
        if (e.type === 'intro') {
            return e.text ? `<div class="desc-sentence">${e.text}</div>` : '';
        }
        return `<div class="desc-role-row">
            <span class="desc-role-label">${e.role}</span>
            <span class="desc-role-name">${e.name}</span>
        </div>`;
    }).join('');
}

// ============ FILTER PILLS ============
function buildFilterPills() {
    const types = [...new Set(locations.map(l => l.type))].sort();
    const bar = document.getElementById('filterBar');
    let html = '<button class="filter-pill active" data-filter="all" onclick="applyFilter(\'all\',this)">All</button>';
    types.forEach(t => {
        html += `<button class="filter-pill" data-filter="${t}" onclick="applyFilter('${t}',this)">${t.charAt(0).toUpperCase()+t.slice(1)}</button>`;
    });
    bar.innerHTML = html;
}

function applyFilter(val, btn) {
    activeTypeFilter = val;
    document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    renderLocationsList();
}

// ============ FLOOR PILLS ============
function buildFloorPills() {
    const floors = [...new Set(locations.map(l => l.floor))].sort((a,b) => a-b);
    const bar = document.getElementById('floorBar');
    let html = '<button class="floor-pill active" data-floor="all" onclick="applyFloor(\'all\',this)">All Floors</button>';
    floors.forEach(f => {
        html += `<button class="floor-pill" data-floor="${f}" onclick="applyFloor('${f}',this)">Floor ${f}</button>`;
    });
    bar.innerHTML = html;
}

function applyFloor(val, btn) {
    activeFloorFilter = val;
    document.querySelectorAll('.floor-pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    renderLocationsList();
}

// ============ RENDER LOCATIONS ============
function getFilteredLocations() {
    return locations.filter(l => {
        if (activeTypeFilter !== 'all' && l.type !== activeTypeFilter) return false;
        if (activeFloorFilter !== 'all' && l.floor != activeFloorFilter) return false;
        return true;
    });
}

function renderLocationsList() {
    const filtered = getFilteredLocations();
    const container = document.getElementById('locationsListContent');
    if (!filtered.length) {
        container.innerHTML = '<div class="empty-state"><div class="es-icon">📍</div><p>No locations match your filters</p><p class="es-sub">Try adjusting filters above</p></div>';
        return;
    }
    const grouped = {};
    filtered.forEach(l => { (grouped[l.building] = grouped[l.building] || []).push(l); });

    let html = '';
    Object.keys(grouped).sort().forEach(building => {
        html += `<div class="building-group"><div class="building-label">🏢 ${building}</div>`;
        grouped[building].sort((a,b) => a.floor - b.floor).forEach(loc => {
            const isFav = favorites.includes(loc.id);
            const a11y = loc.accessible ? '<span class="a11y-badge">♿ Accessible</span>' : '';
            html += `<div class="loc-item" data-id="${loc.id}" onclick="selectLocation(${loc.id},this)">
                <span class="loc-icon">${loc.icon}</span>
                <div style="flex:1;min-width:0;">
                    <div class="loc-name" style="display:flex;align-items:center;flex-wrap:wrap;gap:.2rem;">${loc.name}${a11y}</div>
                    <div class="loc-sub">Floor ${loc.floor} · ${loc.type}</div>
                </div>
                <span class="loc-fav ${isFav?'active':''}" onclick="event.stopPropagation();toggleFav(${loc.id})">${isFav?'⭐':'☆'}</span>
            </div>`;
        });
        html += '</div>';
    });
    container.innerHTML = html;
}

// ============ NEARBY (simulated from entrance) ============
function renderNearby() {
    const entrance = locations.find(l => l.isExit);
    if (!entrance) return;
    const sorted = locations.filter(l => l.id !== entrance.id).sort((a,b) => {
        const da = Math.sqrt(Math.pow(a.coordinates.x-entrance.coordinates.x,2)+Math.pow(a.coordinates.y-entrance.coordinates.y,2)+Math.pow(a.coordinates.z-entrance.coordinates.z,2));
        const db = Math.sqrt(Math.pow(b.coordinates.x-entrance.coordinates.x,2)+Math.pow(b.coordinates.y-entrance.coordinates.y,2)+Math.pow(b.coordinates.z-entrance.coordinates.z,2));
        return da - db;
    }).slice(0, 4);

    if (!sorted.length) return;
    document.getElementById('nearbySection').style.display = 'block';
    let html = '';
    sorted.forEach(loc => {
        html += `<div class="loc-item" style="margin-bottom:.25rem;" onclick="selectLocation(${loc.id},this)">
            <span class="loc-icon">${loc.icon}</span>
            <div><div class="loc-name">${loc.name}</div><div class="loc-sub">Floor ${loc.floor} · ${loc.type}</div></div>
        </div>`;
    });
    document.getElementById('nearbyList').innerHTML = html;
}

// ============ FAVORITES ============
function toggleFav(id) {
    const idx = favorites.indexOf(id);
    if (idx > -1) favorites.splice(idx, 1);
    else favorites.push(id);
    localStorage.setItem('spartha_favs', JSON.stringify(favorites));
    renderLocationsList();
    renderFavorites();
}

function renderFavorites() {
    const container = document.getElementById('favoritesContent');
    const favLocs = locations.filter(l => favorites.includes(l.id));
    if (!favLocs.length) {
        container.innerHTML = '<div class="empty-state"><div class="es-icon">⭐</div><p>No favorites yet</p><p class="es-sub">Tap ☆ on any location to save it here</p></div>';
        return;
    }
    let html = '';
    favLocs.forEach(loc => {
        const a11y = loc.accessible ? '<span class="a11y-badge">♿ Accessible</span>' : '';
        html += `<div class="loc-item" onclick="selectLocation(${loc.id},this)">
            <span class="loc-icon">${loc.icon}</span>
            <div style="flex:1;min-width:0;">
                <div class="loc-name" style="display:flex;align-items:center;flex-wrap:wrap;gap:.2rem;">${loc.name}${a11y}</div>
                <div class="loc-sub">Floor ${loc.floor} · ${loc.type}</div>
            </div>
            <span class="loc-fav active" onclick="event.stopPropagation();toggleFav(${loc.id})">⭐</span>
        </div>`;
    });
    container.innerHTML = html;
}

// ============ EVACUATION ============
function renderEvacExits() {
    const exits = locations.filter(l => l.isExit);
    const container = document.getElementById('emergencyExitsList');
    if (!container) return; // Tab might not be loaded yet
    
    if (!exits.length) {
        container.innerHTML = `<div class="empty-state" style="padding:1.5rem;">
            <div class="es-icon">🚪</div>
            <p>No emergency exits configured</p>
            <p class="es-sub">Add exit locations via Admin Dashboard<br>(Use type: "Exit" or "Entrance")</p>
        </div>`;
        return;
    }
    
    let html = '';
    exits.forEach((loc, index) => {
        const accessible = loc.accessible ? '<span class="evac-exit-badge">♿ Accessible</span>' : '';
        const isPrimary = index === 0 || loc.name.toLowerCase().includes('main');
        const badge = isPrimary 
            ? '<span class="evac-exit-badge">🟢 Primary Exit</span>' 
            : '<span class="evac-exit-badge">🟡 Secondary Exit</span>';
        
        html += `<div class="evac-exit-item" onclick="selectLocation(${loc.id}, this)">
            <div class="evac-exit-icon">${index + 1}</div>
            <div class="evac-exit-info">
                <div class="evac-exit-name">${loc.name}</div>
                <div class="evac-exit-details">${loc.building || ''} ${loc.floor ? '· Floor ' + loc.floor : ''} ${loc.description ? '· ' + loc.description : ''}</div>
                ${badge}${accessible}
            </div>
        </div>`;
    });
    container.innerHTML = html;
}

function openEvacModal() { 
    document.getElementById("evacOverlay").classList.add("show"); 
    if(scene) drawAllEvacRoutes(); 
}

function closeEvacModal(e) {
    if (!e || e.target === document.getElementById('evacOverlay'))
        document.getElementById('evacOverlay').classList.remove('show');
}

function pinEvacExit(id) {
    const loc = locations.find(l => l.id === id);
    if (!loc) return;
    closeEvacModal();
    selectLocation(loc.id);
    if (loc.coordinates && scene) {
        clearEvacMarkers();
        drawEvacRoute(new THREE.Vector3(loc.coordinates.x, loc.coordinates.y, loc.coordinates.z));
        createEvacMarker(new THREE.Vector3(loc.coordinates.x, loc.coordinates.y, loc.coordinates.z));
    }
}

// ============ SEARCH ============
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('searchInput').addEventListener('input', handleSearch);
    document.addEventListener('click', e => { if (!e.target.closest('.search-wrap')) document.getElementById('searchResults').classList.remove('show'); });
});

function handleSearch(e) {
    const q = e.target.value.toLowerCase().trim();
    const rd = document.getElementById('searchResults');
    if (q.length < 2) { rd.classList.remove('show'); return; }
    if (!locations.length) { rd.innerHTML='<div class="sr-item" style="text-align:center;padding:1.2rem;color:#999;font-size:.78rem;">No locations available</div>'; rd.classList.add('show'); return; }
    const hits = locations.filter(l => l.name.toLowerCase().includes(q)||l.building.toLowerCase().includes(q)||l.type.toLowerCase().includes(q));
    rd.innerHTML = hits.length
        ? hits.map(l=>`<div class="sr-item" onclick="selectLocation(${l.id})">${l.accessible?'<span class="a11y-badge" style="float:right;">♿</span>':''}<div class="sr-name">${l.icon} ${l.name}</div><div class="sr-sub">${l.building} · Floor ${l.floor}</div></div>`).join('')
        : `<div class="sr-item" style="text-align:center;padding:1rem;color:#999;"><div style="font-size:1.3rem;">🔍</div><div style="font-size:.76rem;margin-top:.25rem;">No results for "${e.target.value}"</div></div>`;
    rd.classList.add('show');
}

function searchLocation() {
    const q = document.getElementById('searchInput').value.toLowerCase().trim();
    const hit = locations.find(l => l.name.toLowerCase().includes(q));
    if (hit) selectLocation(hit.id);
}

// ============ SELECT LOCATION ============
function selectLocation(idOrObj, clickedEl) {
    const location = typeof idOrObj === 'object' ? idOrObj : locations.find(l => l.id === idOrObj);
    if (!location) return;
    selectedLocation = location;
    document.getElementById('currentLocation').textContent = location.name;

    document.querySelectorAll('.loc-item').forEach(el => el.classList.remove('active'));
    if (clickedEl) clickedEl.classList.add('active');
    else { const m = document.querySelector(`.loc-item[data-id="${location.id}"]`); if(m) m.classList.add('active'); }

    document.getElementById('vsName').textContent = location.name;
    document.getElementById('vsSub').textContent = location.building + ' · Floor ' + location.floor;
    document.getElementById('viewingStrip').classList.add('show');

    document.getElementById('infoTitle').textContent = location.name;

    const entrance = locations.find(l => l.isExit);
    let dirHtml = '';
    if (entrance) {
        dirHtml = `<div class="directions-steps">
            <div style="font-size:.62rem;font-weight:700;color:var(--red);text-transform:uppercase;letter-spacing:.4px;margin-bottom:.3rem;">How to Get There</div>
            <div class="dir-step"><div class="dir-step-num">1</div><div class="dir-step-text">Click <strong style="color:var(--gold-dark);">"Get Directions"</strong> button below to see the path</div></div>
            <div class="dir-step"><div class="dir-step-num">2</div><div class="dir-step-text">Follow the animated golden path on the 3D map</div></div>
            <div class="dir-step"><div class="dir-step-num">3</div><div class="dir-step-text">Arrive at <strong>${location.name}</strong> — Floor ${location.floor}, ${location.building}</div></div>
        </div>`;
    }

    document.getElementById('infoContent').innerHTML = `
        <div class="info-row"><span class="info-row-icon">🏢</span><div><div class="info-label">Building</div><div class="info-value">${location.building}</div></div></div>
        <div class="info-row"><span class="info-row-icon">📍</span><div><div class="info-label">Floor</div><div class="info-value">Floor ${location.floor}</div></div></div>
        <div class="info-row"><span class="info-row-icon">🏷️</span><div><div class="info-label">Type</div><div class="info-value">${location.type.charAt(0).toUpperCase()+location.type.slice(1)}</div></div></div>
        ${location.capacity?`<div class="info-row"><span class="info-row-icon">👥</span><div><div class="info-label">Capacity</div><div class="info-value">${location.capacity} people</div></div></div>`:''}
        ${location.accessible?`<div class="info-row"><span class="info-row-icon">♿</span><div><div class="info-label">Accessibility</div><div class="info-value" style="color:#16a34a;font-weight:600;">Wheelchair Accessible</div></div></div>`:''}
        ${location.description?`<div class="info-row"><span class="info-row-icon">📝</span><div style="flex:1;"><div class="info-label">Description</div><div class="info-value desc-formatted">${formatDescription(location.description)}</div></div></div>`:''}
        <div class="info-row"><span class="info-row-icon">🗺️</span><div><div class="info-label">Coordinates</div><div class="info-value">X:${location.coordinates.x} Y:${location.coordinates.y} Z:${location.coordinates.z}</div></div></div>
        ${dirHtml}
    `;
    const panel = document.getElementById('infoPanel');
    panel.classList.add('show');

    // Dynamically position panel below the actual top-nav height (important on mobile)
    const nav = document.querySelector('.top-nav');
    if (nav && window.innerWidth <= 768) {
        const navBottom = nav.getBoundingClientRect().bottom;
        panel.style.top = (navBottom + 6) + 'px';
    } else {
        panel.style.top = '';
    }

    document.getElementById('searchResults').classList.remove('show');

    if (location.coordinates && scene) {
        // Validate coordinates
        const x = parseFloat(location.coordinates.x);
        const y = parseFloat(location.coordinates.y);
        const z = parseFloat(location.coordinates.z);
        
        if (isNaN(x) || isNaN(y) || isNaN(z)) {
            console.error('Invalid coordinates for location:', location.name, location.coordinates);
            alert('⚠️ This location has invalid coordinates. Please update them in the admin panel.');
            return;
        }
        
        console.log(`\n📍 Selecting: ${location.name}`);
    // Hide idle hint when a location is selected
    const hint = document.getElementById('mapIdleHint');
    if (hint) hint.style.opacity = '0';
        console.log(`   DB Coordinates: (${x.toFixed(1)}, ${y.toFixed(1)}, ${z.toFixed(1)})`);
        
        // Check coordinate validity
        const maxCoord = Math.max(Math.abs(x), Math.abs(y), Math.abs(z));
        if (maxCoord > 200) {
            console.warn(`   ⚠️ Large coordinates detected (max: ${maxCoord.toFixed(1)})`);
            console.warn('   May be in wrong coordinate space - recapture in admin panel');
        }
        
        // Clear any existing path from a previous selection
        pathLines.forEach(line => scene.remove(line));
        pathLines = [];
        pathParticles.forEach(p => { scene.remove(p.mesh); if (p.tail) p.tail.forEach(b => scene.remove(b)); });
        pathParticles = [];
        document.getElementById('pathStats').classList.remove('show');
        const em = scene.getObjectByName('entrance-marker');
        if (em) scene.remove(em);
        document.getElementById('pathStats').classList.remove('show');
        
        // Place marker at exact database coordinates - NO TRANSFORMATION
        const pos = new THREE.Vector3(x, y, z);
        createMarker(pos, 0xC93030);
        animateCamera(pos);
        
        console.log('   ✓ Marker placed\n');
    } else {
        console.warn('No coordinates or scene not ready for location:', location.name);
    }
}

// ============ TABS ============
function switchTab(name, btn) {
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-'+name).classList.add('active');
    if (name === 'favorites') renderFavorites();
    if (name === 'evacuation') renderEvacExits();
}


// ============ VIEWING STRIP ============
function clearViewingStrip() {
    document.getElementById('viewingStrip').classList.remove('show');
    document.querySelectorAll('.loc-item').forEach(el=>el.classList.remove('active'));
    closeInfo(); 
    resetOrientation(); 
    selectedLocation=null;
    document.getElementById('currentLocation').textContent='Main Building';
    document.getElementById('pathStats').classList.remove('show');
}

// ============ SIDEBAR ============
function toggleSidebar() {
    const sb  = document.getElementById('sidebar');
    const mc  = document.getElementById('mapContainer');
    const tab = document.getElementById('sidebarEdgeTab');
    const isMobile = window.innerWidth <= 768;

    sb.classList.toggle('open');
    sb.classList.toggle('collapsed');

    const isNowCollapsed = sb.classList.contains('collapsed');

    // Desktop: shift map container
    if (!isMobile) mc.classList.toggle('expanded', isNowCollapsed);

    // Show/hide edge tab on both mobile and desktop
    if (tab) tab.classList.toggle('edge-tab-visible', isNowCollapsed);

    // Resize renderer after sidebar CSS transition completes
    setTimeout(() => {
        if (renderer && camera) {
            const container = renderer.domElement.parentElement;
            const w = container.clientWidth;
            const h = container.clientHeight;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h);
        }
    }, 320);
}
function closeInfo(){
    document.getElementById('infoPanel').classList.remove('show');
    document.getElementById('pathStats').classList.remove('show');
    // Clear path when user dismisses the panel
    if (scene) {
        pathLines.forEach(line => scene.remove(line));
        pathLines = [];
        pathParticles.forEach(p => { scene.remove(p.mesh); if (p.tail) p.tail.forEach(b => scene.remove(b)); });
        pathParticles = [];
    }
    selectedLocation = null;
    // Show idle hint again
    const hint = document.getElementById('mapIdleHint');
    if (hint) hint.style.opacity = '1';
}
function resetView(){ 
    selectedLocation=null; 
    document.getElementById('currentLocation').textContent='Main Building'; 
    closeInfo(); 
    clearViewingStrip(); 
}
function showFullScreen(){ 
    const e=document.documentElement; 
    (e.requestFullscreen||e.webkitRequestFullscreen||e.msRequestFullscreen).call(e); 
}

// ============ 3D SCENE ============

// ─── Draw ALL manually created navigation paths on map load ──────────────────
// Draws the exact waypoints stored in the DB — no fallbacks, no interpolation.
// Uses allPathMeshes[] separately from pathLines[] so "Get Directions" won't
// erase these persistent background paths.
async function drawAllSavedPaths() {
    // Clear previous persistent paths
    allPathMeshes.forEach(m => scene && scene.remove(m));
    allPathMeshes = [];

    if (!scene) return;

    // Always fetch fresh from API so we get the latest saved routes
    let allRoutes = [];
    try {
        const res = await fetch(`${API_HOST}/navigation-routes`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        allRoutes = await res.json();
        routes = allRoutes; // keep global in sync
    } catch(e) {
        console.warn('[drawAllSavedPaths] Could not fetch routes:', e);
        return;
    }

    if (!allRoutes || allRoutes.length === 0) {
        console.log('[drawAllSavedPaths] No routes found');
        return;
    }

    // ── Deduplicate: keep only the route with the MOST waypoints per location pair ──
    // The admin always POSTs a new route on save, so old saves stack up.
    // We only want the richest (latest) route for each pair.
    const bestRouteMap = new Map();
    for (const route of allRoutes) {
        const a = Math.min(route.start_location_id, route.end_location_id);
        const b = Math.max(route.start_location_id, route.end_location_id);
        const key = `${a}-${b}`;
        const existing = bestRouteMap.get(key);
        if (!existing || _waypointCount(route.waypoints) > _waypointCount(existing.waypoints)) {
            bestRouteMap.set(key, route);
        }
    }
    allRoutes = [...bestRouteMap.values()];
    console.log(`[drawAllSavedPaths] After dedup: ${allRoutes.length} unique route(s) to draw`);

    let drawn = 0;
    const PATH_ORDER = 998;
    const TUBE_R     = 0.50;
    const GLOW_R     = 1.00;

    for (const route of allRoutes) {
        // ── Parse the stored waypoints ──────────────────────────────────────
        let wps = route.waypoints || [];
        if (typeof wps === 'string') {
            try { wps = JSON.parse(wps); } catch(e) { wps = []; }
        }
        if (!Array.isArray(wps)) wps = [];

        // Parse via shared helper — handles null-y, missing keys, string encoding
        const pts = _parseWaypointArray(wps);

        // Need at least 2 points to draw a line
        if (pts.length < 2) {
            console.log(`[drawAllSavedPaths] Route "${route.name}" has ${pts.length} valid waypoint(s) — skipping`);
            continue;
        }

        // ── Resolve color ───────────────────────────────────────────────────
        let color = 0xF4D03F; // default gold
        if (route.path_color) {
            const parsed = parseInt(route.path_color.replace('#', ''), 16);
            if (!isNaN(parsed)) color = parsed;
        }
        if (route.type === 'emergency' || route.type === 'evacuation') color = 0xFF8C00;

        // ── Draw segment-by-segment tubes through every waypoint ────────────
        for (let i = 0; i < pts.length - 1; i++) {
            const seg = new THREE.LineCurve3(pts[i], pts[i + 1]);

            // Main tube
            const tube = new THREE.Mesh(
                new THREE.TubeGeometry(seg, 12, TUBE_R, 8, false),
                new THREE.MeshBasicMaterial({
                    color, transparent: true, opacity: 0.82,
                    depthTest: false, depthWrite: false,
                })
            );
            tube.renderOrder = PATH_ORDER;
            scene.add(tube);
            allPathMeshes.push(tube);

            // Outer glow
            const glow = new THREE.Mesh(
                new THREE.TubeGeometry(seg, 12, GLOW_R, 8, false),
                new THREE.MeshBasicMaterial({
                    color, transparent: true, opacity: 0.12,
                    depthTest: false, depthWrite: false,
                })
            );
            glow.renderOrder = PATH_ORDER - 1;
            scene.add(glow);
            allPathMeshes.push(glow);

            // White core
            const core = new THREE.Mesh(
                new THREE.TubeGeometry(seg, 12, TUBE_R * 0.35, 6, false),
                new THREE.MeshBasicMaterial({
                    color: 0xFFFFFF, transparent: true, opacity: 0.45,
                    depthTest: false, depthWrite: false,
                })
            );
            core.renderOrder = PATH_ORDER + 1;
            scene.add(core);
            allPathMeshes.push(core);
        }

        // Joint spheres at each interior waypoint for smooth connections
        for (let i = 1; i < pts.length - 1; i++) {
            const joint = new THREE.Mesh(
                new THREE.SphereGeometry(TUBE_R, 8, 8),
                new THREE.MeshBasicMaterial({
                    color, transparent: true, opacity: 0.82,
                    depthTest: false, depthWrite: false,
                })
            );
            joint.position.copy(pts[i]);
            joint.renderOrder = PATH_ORDER;
            scene.add(joint);
            allPathMeshes.push(joint);
        }

        drawn++;
        console.log(`[drawAllSavedPaths] ✓ "${route.name}" — ${pts.length} waypoints`);
    }

    console.log(`[drawAllSavedPaths] Drew ${drawn}/${allRoutes.length} routes (${allPathMeshes.length} meshes total)`);
}

function init3DScene() {
    const canvas=document.getElementById('map3dCanvas'), container=canvas.parentElement;
    scene=new THREE.Scene(); 
    scene.background=new THREE.Color(0xf0f1f3);
    
    const aspect=container.clientWidth/container.clientHeight;
    camera=new THREE.PerspectiveCamera(30,aspect,0.1,10000);
    camera.position.set(0,150,-250);
    
    renderer=new THREE.WebGLRenderer({canvas,antialias:true});
    renderer.setSize(container.clientWidth,container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio); 
    renderer.shadowMap.enabled=true;
    
    controls=new THREE.OrbitControls(camera,renderer.domElement);
    controls.enableDamping=true; 
    controls.dampingFactor=.05; 
    controls.minDistance=1;
    controls.maxDistance=Infinity;
    
    scene.add(new THREE.AmbientLight(0xffffff,.6));
    const dl=new THREE.DirectionalLight(0xffffff,.8); 
    dl.position.set(100,200,100); 
    dl.castShadow=true; 
    scene.add(dl);
    scene.add(new THREE.HemisphereLight(0xffffff,0x444444,.4));
    
    // Grid helper removed - no gridlines

    // Load active 3D model from API
    console.log('Fetching active 3D model information...');
    fetch('/api/active-3d-model')
        .then(response => response.json())
        .then(modelInfo => {
            console.log('Active model info:', modelInfo);
            const modelPath = modelInfo.cache_buster 
                ? `${modelInfo.path}?v=${modelInfo.cache_buster}`
                : modelInfo.path;
            
            console.log('Loading 3D model from:', modelPath);
            loadModel(modelPath);
        })
        .catch(error => {
            console.error('Failed to fetch model info, using default:', error);
            // Fallback to default with cache buster
            const cacheBuster = new Date().getTime();
            const modelPath = `https://sparta-production-0acb.up.railway.app/static/batangas_state_university-_the_neu_lipa_map.glb?v=${cacheBuster}`;
            loadModel(modelPath);
        });
    
    function loadModel(modelPath) {
        new THREE.GLTFLoader().load(modelPath,
        gltf=>{ 
            campusModel=gltf.scene; 
            const box=new THREE.Box3().setFromObject(campusModel); 
            const c=box.getCenter(new THREE.Vector3()), s=box.getSize(new THREE.Vector3()); 
            
            // Store transformation info
            modelTransformation.originalBounds = {
                min: { x: box.min.x, y: box.min.y, z: box.min.z },
                max: { x: box.max.x, y: box.max.y, z: box.max.z },
                center: { x: c.x, y: c.y, z: c.z },
                size: { x: s.x, y: s.y, z: s.z }
            };
            
            campusModel.position.sub(c);
            modelTransformation.center = c;
            
            const sc=100/Math.max(s.x,s.y,s.z); 
            campusModel.scale.set(sc,sc,sc);
            modelTransformation.scale = sc;
            
            scene.add(campusModel); 
            document.getElementById('mapLoading').style.display='none'; 
            canvas.style.display='block';
            console.log('✓ 3D model loaded successfully');
            console.log('📊 Model Transformation:', {
                center: { x: c.x.toFixed(2), y: c.y.toFixed(2), z: c.z.toFixed(2) },
                scale: sc.toFixed(2),
                note: 'All coordinates should be in this transformed space'
            });
            
            // Verify coordinates after model loads
            setTimeout(() => verifyLocationCoordinates(), 500);
            // NOTE: paths are NOT drawn on load — they appear only when
            // the user selects a location and clicks "Get Directions".
        },
        xhr=>console.log('Loading model: '+(xhr.loaded/xhr.total*100).toFixed(0)+'%'),
        err=>{ 
            console.error('Failed to load 3D model:', err); 
            document.getElementById('mapLoading').innerHTML='<div style="color:#dc3545;text-align:center;"><div style="font-size:2.5rem;margin-bottom:.6rem;">⚠️</div><p style="font-size:.82rem;">Failed to load 3D map</p><p style="font-size:.7rem;margin-top:.3rem;">Please upload a 3D model in the Admin panel (Admin → Navigation → 3D Map Upload)</p></div>'; 
        }
    );
    } // End loadModel function
    
    animate();
    
    window.addEventListener('resize',()=>{ 
        const w=container.clientWidth,h=container.clientHeight; 
        camera.aspect=w/h; 
        camera.updateProjectionMatrix(); 
        renderer.setSize(w,h); 
    });
}

function animate() {
    animationFrameId = requestAnimationFrame(animate);
    
    // Update path particles — slow comet-trail style
    pathParticles.forEach(particle => {
        // Advance progress very slowly — feels like walking pace
        particle.progress += particle.speed;
        if (particle.progress >= 1) particle.progress = 0;

        // Position along the curve (CatmullRom tension=0 → straight lines)
        const pos = particle.isLinear
            ? new THREE.Vector3().lerpVectors(particle.start, particle.end, particle.progress)
            : particle.curve.getPoint(particle.progress);
        particle.mesh.position.copy(pos);

        // Slow breath — gentle scale pulse, no jitter
        particle.breathTime = (particle.breathTime || 0) + 0.014;
        const breathScale = 1.0 + 0.10 * Math.sin(particle.breathTime);
        particle.mesh.scale.setScalar(breathScale);

        // Fade edges: ramp in first 5%, ramp out last 5%
        const fadeIn  = Math.min(1, particle.progress / 0.05);
        const fadeOut = Math.min(1, (1 - particle.progress) / 0.05);
        const edgeFade = Math.min(fadeIn, fadeOut);
        particle.mesh.material.opacity = (particle.baseOpacity || 0.98) * edgeFade;

        // Comet tail beads — follow behind on the curve
        if (particle.tail) {
            const tailLen = particle.tail.length;
            for (let t = 0; t < tailLen; t++) {
                const tailOffset = (t + 1) * particle.tailSpacing;
                let tp = particle.progress - tailOffset;
                if (tp < 0) tp += 1;
                tp = Math.max(0, Math.min(1, tp));

                const tailPos = particle.isLinear
                    ? new THREE.Vector3().lerpVectors(particle.start, particle.end, tp)
                    : particle.curve.getPoint(tp);
                particle.tail[t].position.copy(tailPos);

                // Shrink + fade with distance from head
                const ratio = 1 - (t + 1) / (tailLen + 1);
                particle.tail[t].scale.setScalar(Math.max(0.05, ratio * breathScale * 0.72));
                particle.tail[t].material.opacity = ratio * 0.50 * edgeFade;
            }
        }

        // Glow halo: slow soft pulse
        if (particle.glow) {
            const glowScale = 1.0 + 0.18 * Math.sin(particle.breathTime * 0.6);
            particle.glow.scale.setScalar(glowScale);
            particle.glow.material.opacity = 0.18 * edgeFade;
        }
    });
    
    controls.update();
    renderer.render(scene, camera);
}

// ============ ENHANCED BLUE MARKER WITH ANIMATION ============
function createMarker(position, color=0x1E90FF) {
    if(currentMarker) scene.remove(currentMarker);
    
    const g=new THREE.Group();
    
    // Blue cone marker - matching professional navigation apps
    const cone=new THREE.Mesh(
        new THREE.ConeGeometry(1.0, 4, 8), 
        new THREE.MeshStandardMaterial({
            color: 0x1E90FF,  // Dodger Blue
            emissive: 0x1E90FF,
            emissiveIntensity: 0.7,
            metalness: 0.6,
            roughness: 0.2
        })
    );
    cone.position.y=2; 
    g.add(cone);
    
    // Glowing blue sphere on top
    const sphere=new THREE.Mesh(
        new THREE.SphereGeometry(0.7, 16, 16), 
        new THREE.MeshStandardMaterial({
            color: 0x4169E1,  // Royal Blue
            emissive: 0x1E90FF,
            emissiveIntensity: 1.0,
            metalness: 0.7,
            roughness: 0.1
        })
    );
    sphere.position.y=4.5; 
    g.add(sphere);
    
    // Inner blue glow ring
    const ring1 = new THREE.Mesh(
        new THREE.RingGeometry(1.5, 2.0, 32),
        new THREE.MeshBasicMaterial({
            color: 0x4A90E2,  // Soft Blue
            transparent: true,
            opacity: 0.5,
            side: THREE.DoubleSide
        })
    );
    ring1.rotation.x = -Math.PI / 2;
    ring1.position.y = 0.1;
    g.add(ring1);
    
    // Outer ripple ring
    const ring2 = new THREE.Mesh(
        new THREE.RingGeometry(2.2, 2.6, 32),
        new THREE.MeshBasicMaterial({
            color: 0x87CEEB,  // Sky Blue
            transparent: true,
            opacity: 0.3,
            side: THREE.DoubleSide
        })
    );
    ring2.rotation.x = -Math.PI / 2;
    ring2.position.y = 0.05;
    g.add(ring2);
    
    // Enhanced animation with multiple effects
    let time = 0;
    (function pulse(){ 
        if (currentMarker !== g) return;
        
        time += 0.025;
        
        // Pulsing sphere with smooth sine wave
        const s = 1 + 0.2 * Math.sin(time * 2);
        sphere.scale.set(s, s, s);
        
        // Inner ring pulse
        const ring1Scale = 1 + 0.3 * Math.sin(time * 1.5);
        const ring1Opacity = 0.4 + 0.3 * Math.sin(time * 1.5);
        ring1.scale.set(ring1Scale, ring1Scale, 1);
        ring1.material.opacity = ring1Opacity;
        
        // Outer ring ripple effect
        const ring2Scale = 1 + 0.5 * Math.sin(time);
        const ring2Opacity = 0.2 + 0.2 * Math.sin(time);
        ring2.scale.set(ring2Scale, ring2Scale, 1);
        ring2.material.opacity = ring2Opacity;
        
        // Gentle rotation for visual interest
        g.rotation.y += 0.005;
        
        requestAnimationFrame(pulse); 
    })();
    
    g.position.copy(position); 
    scene.add(g); 
    currentMarker=g;
}

// ============ ENHANCED PATH with ANIMATION ============
// DEPRECATED: This function is no longer used. All paths must be manually created in admin panel.
function drawEnhancedPath(end) {
    console.error('❌ drawEnhancedPath is DEPRECATED. All navigation paths must be manually created in the admin panel.');
    console.error('Please create a route for this location in the admin panel under Navigation tab.');
    
    alert('⚠️ No Manual Route Found\n\nThis location does not have a manually created navigation route yet.\n\nPlease ask the administrator to create a route in the admin panel:\nAdmin → Navigation → Add Location with Path');
    
    // Clear any existing paths
    pathLines.forEach(line => scene.remove(line));
    pathLines = [];
    pathParticles.forEach(p => scene.remove(p.mesh));
    pathParticles = [];
}

// ============ EVACUATION HELPERS ============
function clearEvacMarkers() {
    evacMarkers.forEach(m => scene.remove(m));
    evacMarkers = [];
    evacPathLines.forEach(l => scene.remove(l));
    evacPathLines = [];
}

function createEvacMarker(position) {
    const g = new THREE.Group();
    const cone = new THREE.Mesh(
        new THREE.ConeGeometry(2.8, 11, 8),
        new THREE.MeshStandardMaterial({ 
            color: 0xE67E22, 
            emissive: 0xE67E22, 
            emissiveIntensity: 0.4 
        })
    );
    cone.position.y = 5.5;
    g.add(cone);
    
    const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(1.8, 16, 16),
        new THREE.MeshStandardMaterial({ 
            color: 0xE67E22, 
            emissive: 0xE67E22, 
            emissiveIntensity: 0.6 
        })
    );
    sphere.position.y = 12;
    g.add(sphere);
    
    let s = 1, growing = true;
    (function pulse() {
        if (!evacMarkers.includes(g)) return;
        growing ? (s += 0.015, s >= 1.3 && (growing = false)) : (s -= 0.015, s <= 1 && (growing = true));
        sphere.scale.set(s, s, s);
        requestAnimationFrame(pulse);
    })();
    
    g.position.copy(position);
    scene.add(g);
    evacMarkers.push(g);
}

function drawEvacRoute(exitPos) {
    const center = new THREE.Vector3(0, 0, 0);
    const mid = new THREE.Vector3(
        (center.x + exitPos.x) / 2,
        Math.max(center.y, exitPos.y) + 18,
        (center.z + exitPos.z) / 2
    );
    const curve = new THREE.QuadraticBezierCurve3(center, mid, exitPos);
    const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(50));
    const line = new THREE.Line(geo, new THREE.LineDashedMaterial({ 
        color: 0xE67E22, 
        dashSize: 3, 
        gapSize: 1 
    }));
    line.computeLineDistances();
    scene.add(line);
    evacPathLines.push(line);
}

function drawAllEvacRoutes() {
    clearEvacMarkers();
    const exits = locations.filter(l => l.isExit);
    exits.forEach(loc => {
        if (loc.coordinates && (loc.coordinates.x || loc.coordinates.y || loc.coordinates.z)) {
            const pos = new THREE.Vector3(loc.coordinates.x, loc.coordinates.y, loc.coordinates.z);
            drawEvacRoute(pos);
            createEvacMarker(pos);
        }
    });
    
    if (camera && controls) {
        const startPos = camera.position.clone();
        const endPos = new THREE.Vector3(0, 250, -350);
        const startTime = Date.now();
        const duration = 1800;
        (function anim() {
            const p = Math.min((Date.now() - startTime) / duration, 1);
            const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
            camera.position.lerpVectors(startPos, endPos, e);
            controls.target.lerp(new THREE.Vector3(0, 0, 0), e);
            controls.update();
            if (p < 1) requestAnimationFrame(anim);
        })();
    }
}


// ============ CAMERA ANIMATION ============
function animateCamera(pos) {
    if (!camera || !controls) return;
    const startCamPos    = camera.position.clone();
    const startTarget    = controls.target.clone();
    const endTarget      = pos.clone();
    // Pull back and up so the location is nicely framed
    const endCamPos = new THREE.Vector3(pos.x, pos.y + 60, pos.z - 100);
    const startTime = Date.now();
    const duration  = 900;
    (function step() {
        const raw  = Math.min((Date.now() - startTime) / duration, 1);
        const ease = raw < 0.5 ? 2*raw*raw : 1 - Math.pow(-2*raw+2, 2)/2;
        camera.position.lerpVectors(startCamPos, endCamPos, ease);
        controls.target.lerpVectors(startTarget, endTarget, ease);
        controls.update();
        if (raw < 1) requestAnimationFrame(step);
    })();
}

// ============ CONTROLS ============
function zoomIn() {
    if (!controls) return;
    const dir = camera.position.clone().sub(controls.target).normalize();
    const d = camera.position.distanceTo(controls.target);
    camera.position.copy(controls.target).add(dir.multiplyScalar(d * 0.8));
    controls.update();
}

function zoomOut() {
    if (!controls) return;
    const dir = camera.position.clone().sub(controls.target).normalize();
    const d = camera.position.distanceTo(controls.target);
    camera.position.copy(controls.target).add(dir.multiplyScalar(d * 1.2));
    controls.update();
}

function rotate() {
    if (controls) {
        controls.autoRotate = !controls.autoRotate;
        controls.autoRotateSpeed = 2;
    }
}

function resetOrientation() {
    if (!camera || !controls) return;
    camera.position.set(0, 150, -250);
    controls.target.set(0, 0, 0);
    controls.autoRotate = false;
    controls.update();
    
    if (currentMarker) {
        scene.remove(currentMarker);
        currentMarker = null;
    }
    
    pathLines.forEach(line => scene.remove(line));
    pathLines = [];
    pathParticles.forEach(p => { scene.remove(p.mesh); if (p.tail) p.tail.forEach(b => scene.remove(b)); });
    pathParticles = [];
    
    clearEvacMarkers();
    
    const em = scene.getObjectByName('entrance-marker');
    if (em) scene.remove(em);
    
    document.getElementById('pathStats').classList.remove('show');
    // Path cleared — user must select a location and Get Directions to redraw
}

function focusOn3D() {
    // Close the info panel
    document.getElementById('infoPanel').classList.remove('show');

    const sb  = document.getElementById('sidebar');
    const mc  = document.getElementById('mapContainer');
    const tab = document.getElementById('sidebarEdgeTab');
    const isMobile = window.innerWidth <= 768;

    // Collapse the sidebar if not already
    if (!sb.classList.contains('collapsed')) {
        sb.classList.remove('open');
        sb.classList.add('collapsed');
        if (!isMobile) mc.classList.add('expanded');
    }

    // Always show the edge tab after directing — works on mobile & desktop
    if (tab) tab.classList.add('edge-tab-visible');

    // Resize renderer after sidebar transition completes
    setTimeout(() => {
        if (renderer && camera) {
            const container = renderer.domElement.parentElement;
            const w = container.clientWidth;
            const h = container.clientHeight;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h);
        }
    }, 320);
}

// Show a friendly non-blocking "no route" message in the info panel
function _showNoRouteUI() {
    const infoContent = document.getElementById('infoContent');
    if (infoContent) {
        const noRoute = document.createElement('div');
        noRoute.style.cssText = 'margin-top:10px;padding:10px 12px;background:#fff7ee;border:1.5px solid rgba(230,126,34,0.3);border-radius:8px;font-size:0.75rem;color:#92400e;line-height:1.5;';
        noRoute.innerHTML = '<strong style="display:block;margin-bottom:4px;">📍 No navigation path yet</strong>' +
            'This location does not have a mapped route. Ask an admin to add one via Admin → Navigation Paths.';
        // Remove any existing no-route message first
        const old = infoContent.querySelector('.no-route-msg');
        if (old) old.remove();
        noRoute.classList.add('no-route-msg');
        infoContent.appendChild(noRoute);
    }
}

async function getDirections() {
    if (!selectedLocation || !selectedLocation.coordinates) {
        console.warn('No location selected or location has no coordinates');
        alert('⚠️ Please select a location first');
        return;
    }
    
    console.log('Getting directions to:', selectedLocation.name, 'ID:', selectedLocation.id);
    
    try {
        // Fetch ALL routes for this location
        const btn = document.getElementById('directionsBtn');
        const btnIcon = document.getElementById('directionsBtnIcon');
        if (btn) { btn.disabled = true; btn.style.opacity = '0.7'; }
        if (btnIcon) btnIcon.textContent = '⏳';

        const response = await fetch(`${API_HOST}/api/routes/for-location/${selectedLocation.id}`);
        
        console.log('Route fetch response status:', response.status);
        
        if (response.ok) {
            const apiData = await response.json();
            // Normalize: backend may return a plain array OR { routes, count, has_waypoints }
            const routeList = Array.isArray(apiData) ? apiData : (apiData.routes || []);
            console.log(`[getDirections] ${routeList.length} route(s) found for location ${selectedLocation.id}`);

            if (routeList && routeList.length > 0) {
                // ── Pick the route with the MOST waypoints ──────────────────────────
                // The admin always POSTs new routes on save (never updates), so multiple
                // records may exist. The newest/richest one has the most waypoints.
                const route = routeList.reduce((best, r) =>
                    _waypointCount(r.waypoints) > _waypointCount(best.waypoints) ? r : best
                , routeList[0]);

                console.log(`[getDirections] Using route "${route.name}" — raw waypoints: ${_waypointCount(route.waypoints)}`);

                // ── Robust parse ────────────────────────────────────────────────────
                const pts = _parseWaypointArray(route.waypoints);
                console.log(`[getDirections] Parsed ${pts.length} valid waypoints`);

                if (pts.length >= 2) {
                    // ── Best case: route has full waypoints ──
                    route.waypoints = pts.map(v => ({ x: v.x, y: v.y, z: v.z }));
                    drawSavedRoute(route);
                    focusOn3D();
                } else {
                    // ── Fallback: no intermediate waypoints stored ──
                    // Build a minimal 2-point path using start + end location coords.
                    console.log('Route has no waypoints — building from location coords');

                    const startLoc = locations.find(l => l.id === route.start_location_id);
                    const endLoc   = locations.find(l => l.id === route.end_location_id)
                                  || selectedLocation;

                    // Attempt to build 2-point waypoints from location coordinates
                    const builtWps = [];

                    if (startLoc && startLoc.coordinates) {
                        const sx = parseFloat(startLoc.coordinates.x);
                        const sy = parseFloat(startLoc.coordinates.y);
                        const sz = parseFloat(startLoc.coordinates.z);
                        if (!isNaN(sx)) builtWps.push({ x: sx, y: sy, z: sz });
                    } else {
                        // No start location — try to find entrance/gate in locations list
                        const gate = locations.find(l =>
                            l.type === 'entrance' ||
                            (l.name && (l.name.toLowerCase().includes('entrance') ||
                                        l.name.toLowerCase().includes('gate') ||
                                        l.name.toLowerCase().includes('main')))
                        );
                        if (gate && gate.coordinates) {
                            const gx = parseFloat(gate.coordinates.x);
                            const gy = parseFloat(gate.coordinates.y);
                            const gz = parseFloat(gate.coordinates.z);
                            if (!isNaN(gx)) builtWps.push({ x: gx, y: gy, z: gz });
                        }
                    }

                    if (endLoc && endLoc.coordinates) {
                        const ex = parseFloat(endLoc.coordinates.x);
                        const ey = parseFloat(endLoc.coordinates.y);
                        const ez = parseFloat(endLoc.coordinates.z);
                        if (!isNaN(ex)) builtWps.push({ x: ex, y: ey, z: ez });
                    }

                    if (builtWps.length >= 2) {
                        console.log('Built', builtWps.length, 'waypoints from location coords');
                        route.waypoints = builtWps;
                        drawSavedRoute(route);
                        focusOn3D();
                    } else if (builtWps.length === 1 && selectedLocation && selectedLocation.coordinates) {
                        // At minimum draw from the single point to the selected destination
                        const dx = parseFloat(selectedLocation.coordinates.x);
                        const dy = parseFloat(selectedLocation.coordinates.y);
                        const dz = parseFloat(selectedLocation.coordinates.z);
                        if (!isNaN(dx)) {
                            builtWps.push({ x: dx, y: dy, z: dz });
                            route.waypoints = builtWps;
                            drawSavedRoute(route);
                            focusOn3D();
                        } else {
                            _showNoRouteUI();
                        }
                    } else {
                        console.warn('Could not build waypoints — location coordinates missing');
                        _showNoRouteUI();
                    }
                }
            } else {
                console.log('No routes found for this location — trying direct coord path');
                // Attempt to draw a direct line to the selected location anyway
                if (selectedLocation && selectedLocation.coordinates) {
                    const dx = parseFloat(selectedLocation.coordinates.x);
                    const dy = parseFloat(selectedLocation.coordinates.y);
                    const dz = parseFloat(selectedLocation.coordinates.z);
                    const gate = locations.find(l =>
                        l.type === 'entrance' ||
                        (l.name && (l.name.toLowerCase().includes('entrance') ||
                                    l.name.toLowerCase().includes('gate') ||
                                    l.name.toLowerCase().includes('main')))
                    );
                    const syntheticRoute = {
                        name: 'Direct path',
                        type: 'standard',
                        path_color: '#F4D03F',
                        waypoints: []
                    };
                    if (gate && gate.coordinates && !isNaN(parseFloat(gate.coordinates.x))) {
                        syntheticRoute.waypoints.push({
                            x: parseFloat(gate.coordinates.x),
                            y: parseFloat(gate.coordinates.y),
                            z: parseFloat(gate.coordinates.z)
                        });
                    }
                    if (!isNaN(dx)) {
                        syntheticRoute.waypoints.push({ x: dx, y: dy, z: dz });
                    }
                    if (syntheticRoute.waypoints.length >= 2) {
                        drawSavedRoute(syntheticRoute);
                        focusOn3D();
                    } else {
                        _showNoRouteUI();
                    }
                } else {
                    _showNoRouteUI();
                }
                return;
            }
        } else {
            console.log('No routes found (HTTP', response.status, ')');
            _showNoRouteUI();
            return;
        }
        

        
    } catch (error) {
        console.error('Error fetching route:', error);
        alert('❌ Error loading route. Please try again or contact the administrator.');
    } finally {
        // Always re-enable the directions button
        const btn = document.getElementById('directionsBtn');
        const btnIcon = document.getElementById('directionsBtnIcon');
        if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
        if (btnIcon) btnIcon.textContent = '📍';
    }
}

// Draw saved route using waypoints
async function drawSavedRoute(route) {
    // Clear old paths before drawing the new one
    pathLines.forEach(line => scene.remove(line));
    pathLines = [];
    pathParticles.forEach(p => { scene.remove(p.mesh); if (p.tail) p.tail.forEach(b => scene.remove(b)); });
    pathParticles = [];
    
    // Convert waypoints to THREE.Vector3 positions
    const waypointPositions = [];
    
    console.log('Drawing route with waypoints:', route.waypoints);
    console.log('Waypoints type:', typeof route.waypoints);
    
    // Parse waypoints - handle both array and JSON string
    let waypoints = route.waypoints;
    if (typeof waypoints === 'string') {
        try {
            waypoints = JSON.parse(waypoints);
            console.log('Parsed waypoints from JSON string');
        } catch(e) {
            console.error('Failed to parse waypoints JSON:', e);
            alert('❌ Invalid waypoint data. Please recreate the route in admin panel.');
            return;
        }
    }
    
    if (!Array.isArray(waypoints)) {
        console.error('Waypoints is not an array:', waypoints);
        alert('❌ Invalid waypoint format. Please recreate the route in admin panel.');
        return;
    }
    
    // Shared parser handles all formats — null-y defaults to 0, no points silently dropped
    const parsedPts = _parseWaypointArray(waypoints);
    console.log(`[drawSavedRoute] ${parsedPts.length} / ${Array.isArray(waypoints) ? waypoints.length : '?'} waypoints parsed`);
    parsedPts.forEach((v, i) => {
        waypointPositions.push(v);
        console.log(`  [${i}] (${v.x.toFixed(2)}, ${v.y.toFixed(2)}, ${v.z.toFixed(2)})`);
    });
    
    if (waypointPositions.length < 2) {
        console.error('Not enough valid waypoints:', waypointPositions.length, '— attempting fallback to location coords');
        // Try one final fallback: use the selected location's own coordinates
        if (waypointPositions.length === 1 && selectedLocation && selectedLocation.coordinates) {
            const dx = parseFloat(selectedLocation.coordinates.x);
            const dy = parseFloat(selectedLocation.coordinates.y);
            const dz = parseFloat(selectedLocation.coordinates.z);
            if (!isNaN(dx)) waypointPositions.push(new THREE.Vector3(dx, dy, dz));
        }
        if (waypointPositions.length < 2) {
            console.error('Cannot draw path — not enough coords. Aborting.');
            _showNoRouteUI();
            return;
        }
    }
    
    console.log('✅ Successfully created', waypointPositions.length, 'waypoint positions');

    // ── Visible debug sphere at every waypoint ──────────────────────────────
    // Makes it immediately obvious how many waypoints are being drawn and where.
    // White = start, orange = intermediate, green = end.
    waypointPositions.forEach((v, i) => {
        const isFirst = i === 0;
        const isLast  = i === waypointPositions.length - 1;
        const col = isFirst ? 0xFFFFFF : (isLast ? 0x00FF88 : 0xFFAA00);
        const r   = isFirst || isLast ? 1.4 : 0.9;
        const dot = new THREE.Mesh(
            new THREE.SphereGeometry(r, 10, 10),
            new THREE.MeshBasicMaterial({ color: col, depthTest: false, depthWrite: false })
        );
        dot.position.copy(v);
        dot.renderOrder = 1002;
        scene.add(dot);
        pathLines.push(dot); // tracked so it's cleaned up on next call
    });
    
    // Create entrance marker at first waypoint
    if (waypointPositions.length > 0) {
        const old = scene.getObjectByName('entrance-marker');
        if (old) scene.remove(old);
        
        const eg = new THREE.Group();
        const ec = new THREE.Mesh(
            new THREE.ConeGeometry(1.4, 6, 8),
            new THREE.MeshBasicMaterial({
                color: 0x00FF00,
                depthTest: false, depthWrite: false,
            })
        );
        ec.renderOrder = 1000;
        ec.position.y = 3;
        eg.add(ec);
        
        const es = new THREE.Mesh(
            new THREE.SphereGeometry(0.9, 16, 16),
            new THREE.MeshStandardMaterial({
                color: 0x00FF00,
                emissive: 0x00FF00,
                emissiveIntensity: .7
            })
        );
        es.position.y = 6.5;
        eg.add(es);
        
        eg.position.copy(waypointPositions[0]);
        eg.name = 'entrance-marker';
        scene.add(eg);
    }
    
    // ── PATH RENDERING ──────────────────────────────────────────────────────
    console.log('🎨 Drawing path with', waypointPositions.length, 'waypoints');

    // Resolve color
    let pathColor = 0xF4D03F;
    if (route.path_color) pathColor = parseInt(route.path_color.replace('#', '0x'));
    const isEmergency = route.type === 'emergency' ||
                        route.path_color === '#FF8C00' ||
                        route.path_color === '#E67E22';
    if (isEmergency) pathColor = 0xFF8C00;

    // Build a multi-segment "straight but smoothed at joints" curve.
    // We use LineCurve3 per segment but insert a tiny rounded corner at each
    // interior waypoint so adjacent tubes connect seamlessly.
    // The particles will travel the whole path using a single CatmullRom with
    // tension=0 (which is effectively straight between evenly-spaced points).

    // Tube sizing — must be large enough to be visible over the 100-unit campus model.
    // depthTest: false ensures the path always renders on top of building geometry.
    const TUBE_RADIUS   = 0.55;   // visible over the building
    const GLOW_RADIUS   = 1.1;    // soft halo
    const CORE_RADIUS   = 0.22;   // bright white center
    const TUBE_SEGMENTS = 14;
    const PATH_ORDER    = 999;    // renderOrder — draw after everything else

    for (let i = 0; i < waypointPositions.length - 1; i++) {
        const seg = new THREE.LineCurve3(waypointPositions[i], waypointPositions[i + 1]);

        // Main glowing tube — depthTest:false so it shows over the building
        const tubeGeo = new THREE.TubeGeometry(seg, TUBE_SEGMENTS, TUBE_RADIUS, 10, false);
        const tubeMat = new THREE.MeshBasicMaterial({
            color: pathColor,
            transparent: true, opacity: 0.92,
            depthTest: false,
            depthWrite: false,
        });
        const tube = new THREE.Mesh(tubeGeo, tubeMat);
        tube.renderOrder = PATH_ORDER;
        scene.add(tube);
        pathLines.push(tube);

        // Soft outer glow
        const glowGeo = new THREE.TubeGeometry(seg, TUBE_SEGMENTS, GLOW_RADIUS, 10, false);
        const glowMat = new THREE.MeshBasicMaterial({
            color: pathColor,
            transparent: true, opacity: 0.18,
            depthTest: false, depthWrite: false,
        });
        const glowMesh = new THREE.Mesh(glowGeo, glowMat);
        glowMesh.renderOrder = PATH_ORDER - 1;
        scene.add(glowMesh);
        pathLines.push(glowMesh);

        // Bright white core
        const coreGeo = new THREE.TubeGeometry(seg, TUBE_SEGMENTS, CORE_RADIUS, 8, false);
        const coreMat = new THREE.MeshBasicMaterial({
            color: 0xFFFFFF,
            transparent: true, opacity: 0.7,
            depthTest: false, depthWrite: false,
        });
        const coreMesh = new THREE.Mesh(coreGeo, coreMat);
        coreMesh.renderOrder = PATH_ORDER + 1;
        scene.add(coreMesh);
        pathLines.push(coreMesh);

        // Animated pulse
        let pulseT = i * 0.4;
        (function pulse(tMat, gMat) {
            if (!pathLines.includes(tube)) return;
            pulseT += 0.012;
            tMat.opacity = 0.82 + 0.15 * Math.sin(pulseT);
            gMat.opacity = 0.12 + 0.08 * Math.sin(pulseT * 0.8);
            requestAnimationFrame(() => pulse(tMat, gMat));
        })(tubeMat, glowMat);

        // Joint sphere at each interior waypoint
        if (i > 0) {
            const jointMat = new THREE.MeshBasicMaterial({
                color: pathColor,
                transparent: true, opacity: 0.92,
                depthTest: false, depthWrite: false,
            });
            const joint = new THREE.Mesh(new THREE.SphereGeometry(TUBE_RADIUS * 1.1, 10, 10), jointMat);
            joint.position.copy(waypointPositions[i]);
            joint.renderOrder = PATH_ORDER;
            scene.add(joint);
            pathLines.push(joint);
        }
    }

    // ── PARTICLES ───────────────────────────────────────────────────────────
    // One unified CatmullRom with tension=0 → straight segments, smooth wrapping
    // so particles flow continuously across all segments without jumping.
    const pathCurve   = new THREE.CatmullRomCurve3(waypointPositions, false, 'catmullrom', 0.0);
    const NUM_PARTICLES = isEmergency ? 9 : 7;
    const BASE_SPEED    = isEmergency ? 0.00055 : 0.00038; // very slow
    const PARTICLE_R    = 0.55;  // noticeably bigger than the tube
    const GLOW_R        = 1.0;   // wide soft halo
    const TAIL_COUNT    = 8;     // tail beads per particle
    const TAIL_GAP      = 0.022; // curve-space gap between beads

    for (let j = 0; j < NUM_PARTICLES; j++) {

        // Head
        const headMat = new THREE.MeshBasicMaterial({
            color: 0xFFFFFF,
            transparent: true, opacity: 0.98,
            depthTest: false, depthWrite: false,
        });
        const head = new THREE.Mesh(new THREE.SphereGeometry(PARTICLE_R, 14, 14), headMat);
        head.renderOrder = 1001;

        // Glow halo
        const haloMat = new THREE.MeshBasicMaterial({
            color: pathColor,
            transparent: true, opacity: 0.30,
            depthTest: false, depthWrite: false,
        });
        const halo = new THREE.Mesh(new THREE.SphereGeometry(GLOW_R, 14, 14), haloMat);
        head.add(halo);
        scene.add(head);

        // Comet tail beads
        const tailBeads = [];
        for (let t = 0; t < TAIL_COUNT; t++) {
            const fade    = 1 - (t + 1) / (TAIL_COUNT + 1);
            const bRadius = Math.max(0.06, PARTICLE_R * fade * 0.65);
            const bMat    = new THREE.MeshBasicMaterial({
                color: pathColor, transparent: true, opacity: fade * 0.50
            });
            const bead = new THREE.Mesh(new THREE.SphereGeometry(bRadius, 8, 8), bMat);
            scene.add(bead);
            tailBeads.push(bead);
        }

        pathParticles.push({
            mesh:        head,
            glow:        halo,
            tail:        tailBeads,
            tailSpacing: TAIL_GAP,
            curve:       pathCurve,
            progress:    j / NUM_PARTICLES,   // evenly spaced on path
            speed:       BASE_SPEED + Math.random() * 0.00006,
            isLinear:    false,
            baseOpacity: 0.98,
            breathTime:  (j / NUM_PARTICLES) * Math.PI * 2
        });
    }

    // Register tail beads with pathLines so they're cleaned up on clear
    pathParticles.forEach(p => {
        if (p.tail) p.tail.forEach(b => pathLines.push(b));
    });

    // ── DIRECTIONAL ARROWS ───────────────────────────────────────────────────
    // Small, subtle — one per interior segment midpoint
    const arrowSegments = waypointPositions.length - 1;
    for (let i = 0; i < arrowSegments; i++) {
        const mid = new THREE.Vector3().lerpVectors(
            waypointPositions[i], waypointPositions[i + 1], 0.5
        );
        const dir = new THREE.Vector3()
            .subVectors(waypointPositions[i + 1], waypointPositions[i])
            .normalize();

        const arrowMat = new THREE.MeshStandardMaterial({
            color: pathColor, emissive: pathColor,
            emissiveIntensity: 1.0,
            transparent: true, opacity: 0.70
        });
        const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.60, 7), arrowMat);
        arrow.position.copy(mid);
        arrow.position.y += 0.55;
        arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
        arrow.rotateX(Math.PI / 2);
        scene.add(arrow);
        pathLines.push(arrow);

        // Gentle float up/down
        const baseY = mid.y + 0.55;
        let aTime   = (i / arrowSegments) * Math.PI * 2;
        (function floatArrow(arw, mat, by) {
            if (!pathLines.includes(arw)) return;
            aTime += 0.022;
            arw.position.y      = by + 0.14 * Math.sin(aTime);
            mat.opacity         = 0.55 + 0.18 * Math.sin(aTime * 1.2);
            requestAnimationFrame(() => floatArrow(arw, mat, by));
        })(arrow, arrowMat, baseY);
    }
    
    // Calculate total distance
    let totalDist = 0;
    for (let i = 0; i < waypointPositions.length - 1; i++) {
        totalDist += waypointPositions[i].distanceTo(waypointPositions[i + 1]);
    }
    
    // Calculate estimated time (assuming 1.4 m/s walking speed)
    const estimatedTime = Math.round(totalDist / 1.4); // seconds
    const minutes = Math.floor(estimatedTime / 60);
    const seconds = estimatedTime % 60;
    
    // Show path stats
    const pathStats = document.getElementById('pathStats');
    document.getElementById('pathDistance').textContent = Math.round(totalDist) + 'm';
    document.getElementById('pathTime').textContent = minutes > 0 
        ? `${minutes}m ${seconds}s` 
        : `${seconds}s`;
    document.getElementById('pathWaypoints').textContent = waypointPositions.length;
    pathStats.classList.add('show');
}

// ============ COORDINATE VERIFICATION ============
function verifyLocationCoordinates() {
    if (locations.length === 0) {
        console.warn('⚠️ No locations loaded to verify');
        return;
    }
    
    console.log('🔍 Verifying location coordinates...');
    
    const issues = [];
    const warnings = [];
    
    locations.forEach(loc => {
        const coords = loc.coordinates;
        
        // Check if coordinates are all zeros
        if (coords.x === 0 && coords.y === 0 && coords.z === 0) {
            warnings.push({
                location: loc.name,
                issue: 'Coordinates are at origin (0,0,0)',
                suggestion: 'If this is not the main entrance, set coordinates in admin panel'
            });
        }
        
        // Check if coordinates are outside reasonable bounds
        const maxCoord = Math.max(Math.abs(coords.x), Math.abs(coords.y), Math.abs(coords.z));
        if (maxCoord > 200) {
            issues.push({
                location: loc.name,
                coords: `(${coords.x.toFixed(1)}, ${coords.y.toFixed(1)}, ${coords.z.toFixed(1)})`,
                issue: 'Coordinates seem too large - may be in wrong coordinate space',
                suggestion: 'Click this location on 3D map in admin panel to update coordinates'
            });
        }
    });
    
    if (issues.length > 0) {
        console.error('❌ Found', issues.length, 'location(s) with coordinate issues:');
        issues.forEach(issue => {
            console.error(`  • ${issue.location}: ${issue.coords}`);
            console.error(`    ${issue.issue}`);
            console.error(`    → Solution: ${issue.suggestion}`);
        });
    }
    
    if (warnings.length > 0) {
        console.warn('⚠️  Found', warnings.length, 'location(s) with coordinate warnings:');
        warnings.forEach(warn => {
            console.warn(`  • ${warn.location}: ${warn.issue}`);
            console.warn(`    → ${warn.suggestion}`);
        });
    }
    
    if (issues.length === 0 && warnings.length === 0) {
        console.log('✅ All location coordinates appear valid');
    }
    
    // Log sample for verification
    if (locations.length > 0) {
        console.log('📍 Sample location coordinates:');
        console.log(`   ${locations[0].name}:`, locations[0].coordinates);
        console.log('   These should match coordinates shown when clicking the same spot in admin panel');
    }
}

// Debug utility - can be called from browser console
window.debugCoordinates = function() {
    console.log('========== COORDINATE DEBUG INFO ==========');
    console.log('\n🗺️  Model Transformation:');
    console.log('   Original Center:', modelTransformation.originalBounds?.center);
    console.log('   Scale Factor:', modelTransformation.scale);
    console.log('   Note: All coordinates should be transformed to this space');
    
    console.log('\n📍 All Locations (' + locations.length + '):');
    locations.forEach((loc, i) => {
        console.log(`   ${i + 1}. ${loc.name}:`, loc.coordinates);
    });
    
    console.log('\n🛤️  All Routes (' + routes.length + '):');
    routes.forEach((route, i) => {
        console.log(`   ${i + 1}. ${route.name}:`);
        console.log('      Start Location ID:', route.start_location_id);
        console.log('      End Location ID:', route.end_location_id);
        console.log('      Waypoints:', route.waypoints?.length || 0);
        if (route.waypoints && route.waypoints.length > 0) {
            console.log('      First waypoint:', route.waypoints[0]);
            console.log('      Last waypoint:', route.waypoints[route.waypoints.length - 1]);
        }
    });
    
    console.log('\n💡 Tips:');
    console.log('   • Coordinates should typically be between -100 and 100 after transformation');
    console.log('   • If markers appear wrong, re-click locations in admin panel 3D map');
    console.log('   • Admin panel and navigator use the SAME transformation');
    console.log('========================================\n');
};

// ============ DEBUG: VISUALIZE EVERY WAYPOINT ============
// Call window.debugPaths() from the browser console to:
//   1. Print every route + every raw waypoint from the DB
//   2. Place a visible yellow sphere at each parsed waypoint on the 3D map
window.debugPaths = async function() {
    console.log('%c🛤️ debugPaths — fetching all routes...', 'font-weight:bold;color:#F4D03F;');

    // Remove previous debug spheres
    (window._debugSpheres || []).forEach(s => scene && scene.remove(s));
    window._debugSpheres = [];

    let allRoutes = [];
    try {
        const res = await fetch(`${API_HOST}/navigation-routes`);
        allRoutes = await res.json();
    } catch(e) {
        console.error('Failed to fetch routes:', e);
        return;
    }

    console.log(`Found ${allRoutes.length} route(s) in DB:`);

    for (const route of allRoutes) {
        const rawWps = route.waypoints;
        const rawCount = _waypointCount(rawWps);
        const parsed   = _parseWaypointArray(rawWps);

        console.group(`Route #${route.id} "${route.name}" | start:${route.start_location_id} → end:${route.end_location_id}`);
        console.log('  Raw waypoints count :', rawCount);
        console.log('  Parsed count        :', parsed.length);
        console.log('  Raw data            :', JSON.stringify(rawWps).slice(0, 300));
        parsed.forEach((v, i) => console.log(`  [${i}] x:${v.x.toFixed(2)}  y:${v.y.toFixed(2)}  z:${v.z.toFixed(2)}`));
        console.groupEnd();

        // Place a visible yellow sphere at every parsed waypoint
        if (scene) {
            parsed.forEach((v, i) => {
                const mat = new THREE.MeshBasicMaterial({
                    color: i === 0 ? 0x00ff00 : (i === parsed.length - 1 ? 0xff0000 : 0xffff00),
                    depthTest: false
                });
                const sphere = new THREE.Mesh(new THREE.SphereGeometry(1.5, 8, 8), mat);
                sphere.position.copy(v);
                sphere.renderOrder = 2000;
                scene.add(sphere);
                window._debugSpheres.push(sphere);
            });
        }
    }

    console.log('%c✅ Done — green=start, red=end, yellow=intermediate. Call debugPaths() again to refresh.', 'color:#0f0;');
};

// Also expose a quick route check for a specific location
window.debugLocation = async function(locationId) {
    console.log(`%c🔍 Routes for location ${locationId}`, 'font-weight:bold;color:#4A90E2;');
    try {
        const res = await fetch(`${API_HOST}/api/routes/for-location/${locationId}`);
        const data = await res.json();
        const routeList = Array.isArray(data) ? data : (data.routes || []);
        console.log(`Found ${routeList.length} route(s):`);
        routeList.forEach(r => {
            const count = _waypointCount(r.waypoints);
            const parsed = _parseWaypointArray(r.waypoints);
            console.log(`  #${r.id} "${r.name}" — DB waypoints: ${count}, parsed: ${parsed.length}`);
            console.log('  Raw:', JSON.stringify(r.waypoints).slice(0, 200));
        });
    } catch(e) {
        console.error('Error:', e);
    }
};

// Add helpful startup message
console.log('%c🗺️ BSU Lipa Campus Navigator', 'font-size: 16px; font-weight: bold; color: #C93030;');
console.log('%cDebug Tools Available:', 'font-size: 12px; font-weight: bold;');
console.log('  → debugCoordinates() - Show all coordinate info');
console.log('  → debugPaths()        - Visualize ALL route waypoints as colored spheres on the map');
console.log('  → debugLocation(id)   - Check exact DB data for a specific location ID');
console.log('  → Press F12 to see detailed loading logs');

// ============ INIT ============
window.onload = function() {
    loadLocationsFromAPI();
    loadRoutesFromAPI(); // Load navigation routes
    init3DScene();
};