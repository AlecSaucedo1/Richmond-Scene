(() => {
  const neighborhoodRoute = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
  const isHome = window.location.pathname === '/';
  if (!neighborhoodRoute && !isHome) return;

  const slug = neighborhoodRoute ? neighborhoodRoute[1] : '';
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const safeHref = (value) => {
    try {
      const url = new URL(String(value || ''), window.location.origin);
      return url.origin === window.location.origin && ['http:','https:'].includes(url.protocol) ? url.href : '#';
    } catch (_) { return '#'; }
  };
  const when = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
  };
  const labels = { permits:'Development', businesses:'Business', service_requests:'City services', police:'Public safety', real_estate:'Real estate', arts:'Arts & culture' };
  const categoryWeight = { permits:110, real_estate:100, businesses:86, arts:76, police:65, service_requests:50 };
  const CITY_MAX_PINS = 120;
  const CITY_HIGHLIGHTS = 18;

  let map = null;
  let snapshotStamp = '';

  function ensureLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (!document.querySelector('link[data-bulletin-leaflet]')) {
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      css.dataset.bulletinLeaflet = '';
      document.head.appendChild(css);
    }
    return new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-bulletin-leaflet]');
      if (existing) {
        existing.addEventListener('load', () => resolve(window.L), {once:true});
        existing.addEventListener('error', reject, {once:true});
        return;
      }
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      script.defer = true;
      script.dataset.bulletinLeaflet = '';
      script.onload = () => resolve(window.L);
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  async function fetchSnapshot() {
    const response = await fetch('/api/bulletin', {headers:{Accept:'application/json'}, cache:'no-store'});
    if (!response.ok) return null;
    return response.json();
  }

  function cityScore(pin) {
    let score = categoryWeight[pin.category] || 40;
    if (pin.highlight) score += 14;
    const detail = `${pin.detail || ''} ${pin.title || ''}`;
    const money = detail.match(/\$(\d+(?:\.\d+)?)M\b/i);
    if (money) score += Math.min(18, Number(money[1]) || 0);
    const units = detail.match(/([+]\d+)\s+proposed housing/i);
    if (units) score += Math.min(16, Number(units[1]) || 0);
    return score;
  }

  function buildCityActivity(data) {
    const editions = Object.values(data?.editions || {});
    const candidates = [];
    const boundaries = [];
    const seen = new Set();
    editions.forEach((edition) => {
      const activity = edition?.map_activity || {};
      if (activity.boundary) boundaries.push({name:edition.name, slug:edition.slug, geometry:activity.boundary});
      (activity.pins || []).forEach((pin, index) => {
        const lat = Number(pin.lat);
        const lon = Number(pin.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        const key = `${pin.category || 'other'}:${lat.toFixed(5)}:${lon.toFixed(5)}:${String(pin.title || '').toLowerCase()}`;
        if (seen.has(key)) return;
        seen.add(key);
        candidates.push({...pin, neighborhood:edition.name, neighborhood_slug:edition.slug, city_score:cityScore(pin) - index * 0.25});
      });
    });

    candidates.sort((a, b) => b.city_score - a.city_score);
    const selected = [];
    const perNeighborhood = new Map();
    const perCategory = new Map();
    for (const pin of candidates) {
      const hood = pin.neighborhood || '';
      const category = pin.category || 'other';
      if ((perNeighborhood.get(hood) || 0) >= 4) continue;
      if ((perCategory.get(category) || 0) >= 30) continue;
      selected.push(pin);
      perNeighborhood.set(hood, (perNeighborhood.get(hood) || 0) + 1);
      perCategory.set(category, (perCategory.get(category) || 0) + 1);
      if (selected.length >= CITY_MAX_PINS) break;
    }

    const highlightIndexes = new Set();
    const usedHoods = new Map();
    const categories = Object.keys(categoryWeight);
    for (let round = 0; round < 3 && highlightIndexes.size < CITY_HIGHLIGHTS; round += 1) {
      for (const category of categories) {
        const index = selected.findIndex((pin, i) => !highlightIndexes.has(i) && pin.category === category && (usedHoods.get(pin.neighborhood) || 0) < 1);
        if (index >= 0) {
          highlightIndexes.add(index);
          usedHoods.set(selected[index].neighborhood, (usedHoods.get(selected[index].neighborhood) || 0) + 1);
        }
        if (highlightIndexes.size >= CITY_HIGHLIGHTS) break;
      }
    }
    for (let i = 0; i < selected.length && highlightIndexes.size < CITY_HIGHLIGHTS; i += 1) {
      if (highlightIndexes.has(i)) continue;
      const hood = selected[i].neighborhood || '';
      if ((usedHoods.get(hood) || 0) >= 2) continue;
      highlightIndexes.add(i);
      usedHoods.set(hood, (usedHoods.get(hood) || 0) + 1);
    }

    const pins = selected.map((pin, index) => {
      const {city_score, ...clean} = pin;
      return {...clean, highlight:highlightIndexes.has(index)};
    });
    const counts = {};
    pins.forEach((pin) => { counts[pin.category] = (counts[pin.category] || 0) + 1; });

    return {
      name:'San Francisco', slug:'', citywide:true,
      updated_at:data.map_activity_updated_at || data.generated_at,
      pins, pin_count:pins.length,
      highlight_count:pins.filter((pin) => pin.highlight).length,
      counts, boundaries,
      neighborhood_count:new Set(pins.map((pin) => pin.neighborhood).filter(Boolean)).size,
      source_note:'The citywide explorer combines mapped layers from every neighborhood edition. Highlights are diversified across neighborhoods and beats; the expanded layer is capped to keep the map readable. Open any neighborhood boundary for its full block-level edition.'
    };
  }

  function pinIcon(L, pin) {
    const category = pin.category || 'other';
    return L.divIcon({
      className:`bulletin-map-marker${pin.highlight ? ' is-highlight' : ''}`,
      html:`<div class="bulletin-map-pin pin-${esc(category)}"></div>`,
      iconSize:pin.highlight ? [28,28] : [22,22],
      iconAnchor:pin.highlight ? [14,14] : [11,11],
      popupAnchor:[0,-12],
    });
  }

  function popup(pin, citywide) {
    const hood = citywide && pin.neighborhood ? `<p class="map-popup-neighborhood">${esc(pin.neighborhood)}</p>` : '';
    const address = pin.address ? `<p>${esc(pin.address)}</p>` : '';
    const detail = pin.detail ? `<p>${esc(pin.detail)}</p>` : '';
    return `<div class="map-popup"><span>${esc(pin.label || labels[pin.category] || 'Current activity')}</span>${hood}<strong>${esc(pin.title || 'Mapped activity')}</strong>${address}${detail}<a href="${safeHref(pin.href)}">Open related coverage →</a></div>`;
  }

  function sectionMarkup(scope, activity) {
    const pins = activity.pins || [];
    const categories = [...new Set(pins.map((pin) => pin.category).filter(Boolean))];
    const filters = categories.map((category) => {
      const count = pins.filter((pin) => pin.category === category).length;
      return `<button type="button" class="map-filter is-active" data-map-filter="${esc(category)}" aria-pressed="true"><span>${esc(labels[category] || category)}</span><b>${count}</b></button>`;
    }).join('');
    const list = pins.map((pin, index) => `
      <button type="button" class="map-activity-item${pin.highlight ? ' is-highlight' : ''}" data-map-item="${index}" data-map-category="${esc(pin.category)}" data-highlight="${pin.highlight ? 'true' : 'false'}">
        <i class="map-list-mark ${esc(pin.category)}" aria-hidden="true"></i>
        <span><span>${activity.citywide && pin.neighborhood ? `${esc(pin.neighborhood)} · ` : ''}${esc(pin.label || labels[pin.category] || 'Activity')}${pin.highlight ? ' · Highlight' : ''}</span><strong>${esc(pin.title)}</strong><small>${esc(pin.detail || pin.address || '')}</small></span>
      </button>`).join('');
    const neighborhoodOptions = activity.citywide
      ? [...new Set(pins.map((pin) => pin.neighborhood).filter(Boolean))].sort().map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join('')
      : '';

    return `
      <div class="neighborhood-map-head">
        <div><p class="section-label">MAPPED ACTIVITY</p><h2>${activity.citywide ? 'San Francisco right now' : `${esc(scope.name)} right now`}</h2><p>${activity.citywide ? 'Explore the strongest signals across the city, then open the broader layer or a neighborhood boundary to move from the citywide picture into a local edition.' : 'Start with the strongest signals in this edition, then open the broader mapped layer to explore what else is happening block by block.'}</p></div>
        <span class="neighborhood-map-updated">${activity.updated_at ? `Updated ${esc(when(activity.updated_at))}` : 'Current edition'}</span>
      </div>
      <div class="map-signal-summary" aria-label="Mapped activity summary">
        <div><strong>${Number(activity.highlight_count || pins.filter((pin) => pin.highlight).length)}</strong><span>highlighted signals</span></div>
        <div><strong>${pins.length}</strong><span>${activity.citywide ? 'city signals available' : 'mapped signals available'}</span></div>
        <div><strong>${activity.citywide ? Number(activity.neighborhood_count || 0) : categories.length}</strong><span>${activity.citywide ? 'neighborhoods represented' : 'active beats'}</span></div>
        <div><strong data-map-visible-count>${pins.filter((pin) => pin.highlight).length || pins.length}</strong><span>currently visible</span></div>
      </div>
      <div class="map-explorer-toolbar${activity.citywide ? ' is-citywide' : ''}" aria-label="Map controls">
        <div class="map-mode-switch" role="group" aria-label="Map signal density">
          <button type="button" class="map-mode is-active" data-map-mode="highlights" aria-pressed="true">Highlights</button>
          <button type="button" class="map-mode" data-map-mode="all" aria-pressed="false">${activity.citywide ? 'Citywide layer' : 'All mapped signals'}</button>
        </div>
        <label class="map-search"><span>Search map</span><input type="search" inputmode="search" placeholder="${activity.citywide ? 'Neighborhood, address, project…' : 'Address, business, project…'}" data-map-search></label>
        ${activity.citywide ? `<label class="map-neighborhood-select"><span>Neighborhood</span><select data-map-neighborhood><option value="">All neighborhoods</option>${neighborhoodOptions}</select></label>` : ''}
        <button type="button" class="map-tool" data-map-fit>Fit active signals</button>
        <button type="button" class="map-tool" data-map-reset>Reset filters</button>
      </div>
      <div class="map-legend" aria-label="Map filters">${filters}</div>
      <div class="neighborhood-map-layout${activity.citywide ? ' citywide-map-layout' : ''}">
        <div class="neighborhood-map-canvas${activity.citywide ? ' citywide-map-canvas' : ''}" data-neighborhood-map aria-label="${activity.citywide ? 'Map of current activity across San Francisco' : `Map of highlighted activity in ${esc(scope.name)}`}"></div>
        <aside class="neighborhood-map-side">
          <div class="map-signal-detail" data-map-detail aria-live="polite">
            <span>SELECT A SIGNAL</span>
            <strong>${activity.citywide ? 'Explore the city' : 'Explore the map or activity list'}</strong>
            <p>${activity.citywide ? 'Tap a pin or neighborhood boundary to move between the citywide view and a local edition.' : 'Tap a pin to keep its details here while you compare nearby activity.'}</p>
          </div>
          <div class="map-activity-list" data-map-list>${list || '<p class="map-empty">No current records have mappable coordinates yet.</p>'}</div>
        </aside>
      </div>
      <p class="neighborhood-map-note">${esc(activity.source_note || 'Selected locations from current public records.')}</p>`;
  }

  async function render(data) {
    const scope = isHome ? {name:'San Francisco', slug:''} : data?.editions?.[slug];
    const activity = isHome ? buildCityActivity(data) : scope?.map_activity;
    if (!scope || !activity || (!(activity.pins || []).length && !activity.boundary && !(activity.boundaries || []).length)) return;

    if (map) { map.remove(); map = null; }
    document.querySelector('.neighborhood-map-section')?.remove();

    const section = document.createElement('section');
    section.className = `neighborhood-map-section neighborhood-map-top${activity.citywide ? ' citywide-map-section' : ''}`;
    section.innerHTML = sectionMarkup(scope, activity);
    const anchor = activity.citywide ? document.querySelector('.date-line') : document.querySelector('.edition-heading');
    if (anchor) anchor.insertAdjacentElement('afterend', section);
    else document.querySelector('main')?.prepend(section);

    const canvas = section.querySelector('[data-neighborhood-map]');
    if (!canvas) return;

    let L;
    try { L = await ensureLeaflet(); }
    catch (_) {
      canvas.innerHTML = '<div class="map-empty">Interactive map tiles are temporarily unavailable. The activity list remains current.</div>';
      return;
    }
    if (!L) return;

    const pins = activity.pins || [];
    const state = {mode:'highlights', categories:new Set(pins.map((pin) => pin.category).filter(Boolean)), query:'', neighborhood:'', selected:null};

    map = L.map(canvas, {scrollWheelZoom:false, zoomControl:true, attributionControl:true, preferCanvas:true});
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; OpenStreetMap contributors'}).addTo(map);

    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#9b1c20';
    const homeBounds = L.latLngBounds([]);
    if (activity.citywide) {
      (activity.boundaries || []).forEach((boundary) => {
        try {
          const outline = L.geoJSON(boundary.geometry, {style:{color:'#77736c', weight:1, opacity:.58, fillColor:accent, fillOpacity:.01}}).addTo(map);
          outline.bindTooltip(boundary.name, {sticky:true, direction:'top', className:'city-neighborhood-tooltip'});
          outline.on('mouseover', () => outline.setStyle({color:accent, weight:2, opacity:.9, fillOpacity:.035}));
          outline.on('mouseout', () => outline.setStyle({color:'#77736c', weight:1, opacity:.58, fillOpacity:.01}));
          outline.on('click', () => { window.location.assign(`/neighborhood/${encodeURIComponent(boundary.slug)}`); });
          if (outline.getBounds?.().isValid()) homeBounds.extend(outline.getBounds());
        } catch (_) {}
      });
    } else if (activity.boundary) {
      try {
        const outline = L.geoJSON(activity.boundary, {style:{color:accent, weight:2, opacity:.9, fillColor:accent, fillOpacity:.025, dashArray:'6 5'}}).addTo(map);
        if (outline.getBounds?.().isValid()) homeBounds.extend(outline.getBounds());
      } catch (_) {}
    }

    const markers = [];
    pins.forEach((pin, index) => {
      const lat = Number(pin.lat);
      const lon = Number(pin.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const marker = L.marker([lat,lon], {icon:pinIcon(L, pin), title:pin.title || pin.label || 'Bulletin activity'}).bindPopup(popup(pin, activity.citywide), {maxWidth:310});
      marker.on('click', () => selectSignal(index, false));
      markers[index] = marker;
      homeBounds.extend([lat,lon]);
    });

    const searchable = (pin) => [pin.neighborhood, pin.title, pin.detail, pin.address, pin.label, labels[pin.category]].filter(Boolean).join(' ').toLowerCase();
    const isVisible = (pin) => {
      if (!state.categories.has(pin.category)) return false;
      if (state.mode === 'highlights' && !pin.highlight) return false;
      if (state.neighborhood && pin.neighborhood !== state.neighborhood) return false;
      if (state.query && !searchable(pin).includes(state.query)) return false;
      return true;
    };

    function visibleIndexes() {
      const result = [];
      pins.forEach((pin, index) => { if (isVisible(pin) && markers[index]) result.push(index); });
      return result;
    }

    function fitHome() {
      if (homeBounds.isValid()) map.fitBounds(homeBounds.pad(activity.citywide ? .015 : .08), {maxZoom:activity.citywide ? 13 : 15, padding:[20,20]});
      else map.setView([37.7749,-122.4194], activity.citywide ? 12 : 13);
    }

    function fitVisible() {
      const indexes = visibleIndexes();
      const bounds = L.latLngBounds([]);
      indexes.forEach((index) => bounds.extend(markers[index].getLatLng()));
      if (bounds.isValid()) map.fitBounds(bounds.pad(activity.citywide ? .08 : .12), {maxZoom:activity.citywide ? 14 : 16, padding:[24,24]});
      else fitHome();
    }

    function setDetail(index) {
      const detail = section.querySelector('[data-map-detail]');
      const pin = pins[index];
      if (!detail || !pin) return;
      const hood = activity.citywide && pin.neighborhood ? `<small>${esc(pin.neighborhood)}${pin.address ? ` · ${esc(pin.address)}` : ''}</small>` : (pin.address ? `<small>${esc(pin.address)}</small>` : '');
      detail.innerHTML = `<span>${esc(pin.label || labels[pin.category] || 'Mapped signal')}${pin.highlight ? ' · Highlight' : ''}</span><strong>${esc(pin.title || 'Mapped activity')}</strong>${hood}<p>${esc(pin.detail || 'Current mapped activity from this edition.')}</p><a href="${safeHref(pin.href)}">${activity.citywide && pin.neighborhood ? `Open ${esc(pin.neighborhood)} coverage` : 'Open related coverage'} →</a>`;
    }

    function selectSignal(index, pan=true) {
      const marker = markers[index];
      if (!marker) return;
      state.selected = index;
      section.querySelectorAll('[data-map-item]').forEach((item) => item.classList.toggle('is-selected', Number(item.dataset.mapItem) === index));
      setDetail(index);
      if (pan) map.panTo(marker.getLatLng(), {animate:true});
      marker.openPopup();
    }

    function applyVisibility({fit=false}={}) {
      let visible = 0;
      pins.forEach((pin, index) => {
        const marker = markers[index];
        if (!marker) return;
        const show = isVisible(pin);
        const onMap = map.hasLayer(marker);
        if (show && !onMap) marker.addTo(map);
        if (!show && onMap) map.removeLayer(marker);
        const item = section.querySelector(`[data-map-item="${index}"]`);
        if (item) item.hidden = !show;
        if (show) visible += 1;
      });
      const count = section.querySelector('[data-map-visible-count]');
      if (count) count.textContent = String(visible);
      if (state.selected !== null && !isVisible(pins[state.selected])) {
        state.selected = null;
        const detail = section.querySelector('[data-map-detail]');
        if (detail) detail.innerHTML = '<span>FILTERED VIEW</span><strong>Select a visible signal</strong><p>The detail pane follows the active map filters.</p>';
      }
      if (fit) fitVisible();
    }

    section.querySelectorAll('[data-map-item]').forEach((button) => button.addEventListener('click', () => selectSignal(Number(button.dataset.mapItem))));
    section.querySelectorAll('[data-map-filter]').forEach((button) => {
      button.addEventListener('click', () => {
        const category = button.dataset.mapFilter;
        if (!category) return;
        if (state.categories.has(category)) state.categories.delete(category); else state.categories.add(category);
        const active = state.categories.has(category);
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', String(active));
        applyVisibility({fit:true});
      });
    });
    section.querySelectorAll('[data-map-mode]').forEach((button) => {
      button.addEventListener('click', () => {
        state.mode = button.dataset.mapMode === 'all' ? 'all' : 'highlights';
        section.querySelectorAll('[data-map-mode]').forEach((item) => {
          const active = item === button;
          item.classList.toggle('is-active', active);
          item.setAttribute('aria-pressed', String(active));
        });
        applyVisibility({fit:!activity.citywide || state.mode === 'all'});
        if (activity.citywide && state.mode === 'highlights' && !state.query && !state.neighborhood) fitHome();
      });
    });

    const search = section.querySelector('[data-map-search]');
    search?.addEventListener('input', () => { state.query = String(search.value || '').trim().toLowerCase(); applyVisibility({fit:false}); });
    const neighborhoodSelect = section.querySelector('[data-map-neighborhood]');
    neighborhoodSelect?.addEventListener('change', () => { state.neighborhood = String(neighborhoodSelect.value || ''); applyVisibility({fit:true}); });
    section.querySelector('[data-map-fit]')?.addEventListener('click', fitVisible);
    section.querySelector('[data-map-reset]')?.addEventListener('click', () => {
      state.mode = 'highlights'; state.query = ''; state.neighborhood = '';
      state.categories = new Set(pins.map((pin) => pin.category).filter(Boolean));
      if (search) search.value = '';
      if (neighborhoodSelect) neighborhoodSelect.value = '';
      section.querySelectorAll('[data-map-filter]').forEach((button) => { button.classList.add('is-active'); button.setAttribute('aria-pressed','true'); });
      section.querySelectorAll('[data-map-mode]').forEach((button) => {
        const active = button.dataset.mapMode === 'highlights';
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', String(active));
      });
      applyVisibility({fit:false});
      fitHome();
    });

    applyVisibility({fit:false});
    fitHome();
    const firstHighlight = pins.findIndex((pin, index) => pin.highlight && markers[index]);
    if (firstHighlight >= 0) setDetail(firstHighlight);
    setTimeout(() => map?.invalidateSize(), 100);
  }

  async function refresh() {
    try {
      const data = await fetchSnapshot();
      if (!data?.generated_at) return;
      if (snapshotStamp && data.generated_at === snapshotStamp) return;
      snapshotStamp = data.generated_at;
      await render(data);
    } catch (_) {}
  }

  window.addEventListener('pagehide', () => map?.remove());
  refresh();
  window.setInterval(refresh, 5 * 60 * 1000);
})();