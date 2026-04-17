// ============ GLOBAL API HOST ============
const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const API_HOST = isLocal
    ? `http://localhost:8000`
    : `https://sparta-production-0acb.up.railway.app/api/chat`;

// ============ STATE ============
let locations = [];
let routes = [];
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
        ${location.description?`<div class="info-row"><span class="info-row-icon">📝</span><div><div class="info-label">Description</div><div class="info-value">${location.description}</div></div></div>`:''}
        <div class="info-row"><span class="info-row-icon">🗺️</span><div><div class="info-label">Coordinates</div><div class="info-value">X:${location.coordinates.x} Y:${location.coordinates.y} Z:${location.coordinates.z}</div></div></div>
        ${dirHtml}
    `;
    document.getElementById('infoPanel').classList.add('show');
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
        console.log(`   DB Coordinates: (${x.toFixed(1)}, ${y.toFixed(1)}, ${z.toFixed(1)})`);
        
        // Check coordinate validity
        const maxCoord = Math.max(Math.abs(x), Math.abs(y), Math.abs(z));
        if (maxCoord > 200) {
            console.warn(`   ⚠️ Large coordinates detected (max: ${maxCoord.toFixed(1)})`);
            console.warn('   May be in wrong coordinate space - recapture in admin panel');
        }
        
        // Clear previous paths and particles
        pathLines.forEach(line => scene.remove(line));
        pathLines = [];
        pathParticles.forEach(p => scene.remove(p.mesh));
        pathParticles = [];
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
    const sb=document.getElementById('sidebar'), mc=document.getElementById('mapContainer');
    sb.classList.toggle('open'); sb.classList.toggle('collapsed');
    if(window.innerWidth>768) mc.classList.toggle('expanded');
}
function closeInfo(){ document.getElementById('infoPanel').classList.remove('show'); }
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
    controls.minDistance=50; 
    controls.maxDistance=500;
    
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
            const modelPath = `/static/batangas_state_university-_the_neu_lipa_map.glb?v=${cacheBuster}`;
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
    pathParticles.forEach(p => scene.remove(p.mesh));
    pathParticles = [];
    
    clearEvacMarkers();
    
    const em = scene.getObjectByName('entrance-marker');
    if (em) scene.remove(em);
    
    document.getElementById('pathStats').classList.remove('show');
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
        const response = await fetch(`${API_HOST}/api/routes/for-location/${selectedLocation.id}`);
        
        console.log('Route fetch response status:', response.status);
        
        if (response.ok) {
            const routes = await response.json();
            console.log('Routes received:', routes);
            
            if (routes && routes.length > 0) {
                // Use the first available route
                const route = routes[0];
                console.log('Using saved route:', route.name);
                
                // Draw path using saved waypoints
                if (route.waypoints && route.waypoints.length > 0) {
                    console.log('Drawing saved route with', route.waypoints.length, 'waypoints');
                    drawSavedRoute(route);
                } else {
                    console.log('Route has no waypoints');
                    alert('⚠️ This route has no waypoints. Please recreate it in the admin panel.');
                    return;
                }
            } else {
                console.log('No routes found for this location');
                alert('⚠️ No Navigation Route Found\n\nThis location does not have a manually created navigation route yet.\n\nPlease ask the administrator to create a route in the admin panel:\nAdmin → Navigation → Add Location with Path');
                return;
            }
        } else {
            console.log('No routes found (HTTP', response.status, ')');
            alert('⚠️ No Navigation Route Found\n\nThis location does not have a manually created navigation route yet.\n\nPlease ask the administrator to create a route in the admin panel:\nAdmin → Navigation → Add Location with Path');
            return;
        }
        

        
    } catch (error) {
        console.error('Error fetching route:', error);
        alert('❌ Error loading route. Please try again or contact the administrator.');
    }
}

// Draw saved route using waypoints
async function drawSavedRoute(route) {
    // Clear old paths
    pathLines.forEach(line => scene.remove(line));
    pathLines = [];
    pathParticles.forEach(p => scene.remove(p.mesh));
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
    
    for (const waypoint of waypoints) {
        // Check if waypoint is a coordinate object {x, y, z}
        if (waypoint && typeof waypoint === 'object' && 
            'x' in waypoint && 'y' in waypoint && 'z' in waypoint) {
            const x = parseFloat(waypoint.x);
            const y = parseFloat(waypoint.y);
            const z = parseFloat(waypoint.z);
            
            if (!isNaN(x) && !isNaN(y) && !isNaN(z)) {
                waypointPositions.push(new THREE.Vector3(x, y, z));
                console.log(`Added waypoint: (${x}, ${y}, ${z})`);
            } else {
                console.warn('Invalid waypoint coordinates:', waypoint);
            }
        } 
        // Fallback: if waypoint is a location ID (for backward compatibility)
        else if (typeof waypoint === 'number') {
            const loc = locations.find(l => l.id === waypoint);
            if (loc && loc.coordinates) {
                waypointPositions.push(new THREE.Vector3(
                    loc.coordinates.x,
                    loc.coordinates.y,
                    loc.coordinates.z
                ));
                console.log(`Added waypoint from location ID ${waypoint}`);
            } else {
                console.warn('Location not found for waypoint ID:', waypoint);
            }
        } else {
            console.warn('Unknown waypoint format:', waypoint);
        }
    }
    
    if (waypointPositions.length < 2) {
        console.error('Not enough valid waypoints to draw route. Found:', waypointPositions.length);
        alert('⚠️ Not enough waypoints to draw path. At least 2 waypoints are required.\n\nPlease recreate the route in the admin panel with more waypoints.');
        return;
    }
    
    console.log('✅ Successfully created', waypointPositions.length, 'waypoint positions');
    
    // Create entrance marker at first waypoint
    if (waypointPositions.length > 0) {
        const old = scene.getObjectByName('entrance-marker');
        if (old) scene.remove(old);
        
        const eg = new THREE.Group();
        const ec = new THREE.Mesh(
            new THREE.ConeGeometry(1.4, 6, 8),
            new THREE.MeshStandardMaterial({
                color: 0x00FF00,
                emissive: 0x00FF00,
                emissiveIntensity: .5
            })
        );
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

    // For the TUBE we draw straight LineCurve3 segments — no bending at all.
    const TUBE_RADIUS      = 0.18;   // thin line
    const GLOW_RADIUS      = 0.36;   // soft halo around line
    const CORE_RADIUS      = 0.07;   // bright white core
    const TUBE_SEGMENTS    = 12;     // enough for smooth caps

    for (let i = 0; i < waypointPositions.length - 1; i++) {
        const seg = new THREE.LineCurve3(waypointPositions[i], waypointPositions[i + 1]);

        // Main glowing tube
        const tubeGeo  = new THREE.TubeGeometry(seg, TUBE_SEGMENTS, TUBE_RADIUS, 10, false);
        const tubeMat  = new THREE.MeshStandardMaterial({
            color: pathColor, emissive: pathColor,
            emissiveIntensity: 0.9,
            transparent: true, opacity: 0.85,
            metalness: 0, roughness: 0.5
        });
        const tube = new THREE.Mesh(tubeGeo, tubeMat);
        scene.add(tube);
        pathLines.push(tube);

        // Soft outer glow shell
        const glowGeo  = new THREE.TubeGeometry(seg, TUBE_SEGMENTS, GLOW_RADIUS, 10, false);
        const glowMat  = new THREE.MeshBasicMaterial({
            color: pathColor, transparent: true, opacity: 0.13
        });
        const glowMesh = new THREE.Mesh(glowGeo, glowMat);
        scene.add(glowMesh);
        pathLines.push(glowMesh);

        // Bright inner core
        const coreGeo  = new THREE.TubeGeometry(seg, TUBE_SEGMENTS, CORE_RADIUS, 8, false);
        const coreMat  = new THREE.MeshBasicMaterial({
            color: 0xFFFFFF, transparent: true, opacity: 0.55
        });
        const coreMesh = new THREE.Mesh(coreGeo, coreMat);
        scene.add(coreMesh);
        pathLines.push(coreMesh);

        // Animated pulse per segment (slightly offset phase each segment)
        let pulseT = i * 0.4;
        (function pulse(tMat, gMat) {
            if (!pathLines.includes(tube)) return;
            pulseT += 0.010;
            tMat.emissiveIntensity = 0.80 + 0.20 * Math.sin(pulseT);
            gMat.opacity           = 0.10 + 0.06 * Math.sin(pulseT * 0.8);
            requestAnimationFrame(() => pulse(tMat, gMat));
        })(tubeMat, glowMat);

        // Smooth joint sphere at each interior waypoint
        if (i > 0) {
            const jointGeo = new THREE.SphereGeometry(TUBE_RADIUS, 10, 10);
            const jointMat = new THREE.MeshStandardMaterial({
                color: pathColor, emissive: pathColor,
                emissiveIntensity: 0.9,
                transparent: true, opacity: 0.85
            });
            const joint = new THREE.Mesh(jointGeo, jointMat);
            joint.position.copy(waypointPositions[i]);
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
        const headMat = new THREE.MeshStandardMaterial({
            color: pathColor, emissive: pathColor,
            emissiveIntensity: 1.6,
            transparent: true, opacity: 0.98
        });
        const head = new THREE.Mesh(new THREE.SphereGeometry(PARTICLE_R, 14, 14), headMat);

        // Glow halo (child of head, no extra scene.add needed)
        const haloMat = new THREE.MeshBasicMaterial({
            color: pathColor, transparent: true, opacity: 0.20
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

// Add helpful startup message
console.log('%c🗺️ BSU Lipa Campus Navigator', 'font-size: 16px; font-weight: bold; color: #C93030;');
console.log('%cDebug Tools Available:', 'font-size: 12px; font-weight: bold;');
console.log('  → debugCoordinates() - Show all coordinate info');
console.log('  → Press F12 to see detailed loading logs');

// ============ INIT ============
window.onload = function() {
    loadLocationsFromAPI();
    loadRoutesFromAPI(); // Load navigation routes
    init3DScene();
};