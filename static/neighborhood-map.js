(() => {
  const route = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
  if (!route) return;

  const slug = route[1];
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const safeHref = (value) => {
    try {
      const url = new URL(String(value || ''), window.location.origin);
      return url.origin === window.location.origin && ['http:','https:'].includes(url.protocol) ? url.href : '#';
    } catch (_) {
      return '#';
    }
  };
  const when = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
  };

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

  function pinIcon(L, category) {
    return L.divIcon({
      className: 'bulletin-map-marker',
      html: `<div class="bulletin-map-pin pin-${esc(category)}"></div>`,
      iconSize: [24,24],
      iconAnchor: [12,12],
      popupAnchor: [0,-12],
    });
  }

  function popup(pin) {
    const address = pin.address ? `<p>${esc(pin.address)}</p>` : '';
    const detail = pin.detail ? `<p>${esc(pin.detail)}</p>` : '';
    return `<div class="map-popup"><span>${esc(pin.label || 'Current activity')}</span><strong>${esc(pin.title || 'Neighborhood activity')}</strong>${address}${detail}<a href="${safeHref(pin.href)}">Open the underlying beat →</a></div>`;
  }

  function sectionMarkup(edition, activity) {
    const pins = activity.pins || [];
    const categories = [...new Set(pins.map((pin) => pin.category).filter(Boolean))];
    const labels = {permits:'Development', businesses:'Business', service_requests:'City services', police:'Public safety'};
    const list = pins.map((pin, index) => `
      <button type="button" class="map-activity-item" data-map-item="${index}" data-map-category="${esc(pin.category)}">
        <i class="map-list-mark ${esc(pin.category)}" aria-hidden="true"></i>
        <span><span>${esc(pin.label || labels[pin.category] || 'Activity')}</span><strong>${esc(pin.title)}</strong><small>${esc(pin.detail || pin.address || '')}</small></span>
      </button>`).join('');
    const filters = categories.map((category) => `<button type="button" class="map-filter is-active" data-map-filter="${esc(category)}" aria-pressed="true">${esc(labels[category] || category)}</button>`).join('');
    return `
      <div class="neighborhood-map-head">
        <div><p class="section-label">MAPPED ACTIVITY</p><h2>${esc(edition.name)} right now</h2><p>A street-level view of selected records driving this edition. The map redraws from the same refreshed public-record snapshot as the stories around it.</p></div>
        <span class="neighborhood-map-updated">${activity.updated_at ? `Updated ${esc(when(activity.updated_at))}` : 'Current edition'}</span>
      </div>
      <div class="neighborhood-map-layout">
        <div class="neighborhood-map-canvas" data-neighborhood-map aria-label="Map of highlighted activity in ${esc(edition.name)}"></div>
        <aside class="neighborhood-map-side">
          ${filters ? `<div class="map-legend" aria-label="Map filters">${filters}</div>` : ''}
          <div class="map-activity-list">${list || '<p class="map-empty">No highlighted records in the current source window have mappable coordinates yet.</p>'}</div>
        </aside>
      </div>
      <p class="neighborhood-map-note">${esc(activity.source_note || 'Selected locations from current public records.')}</p>`;
  }

  async function render(data) {
    const edition = data?.editions?.[slug];
    const activity = edition?.map_activity;
    if (!edition || !activity || (!(activity.pins || []).length && !activity.boundary)) return;

    if (map) {
      map.remove();
      map = null;
    }
    document.querySelector('.neighborhood-map-section')?.remove();

    const section = document.createElement('section');
    section.className = 'neighborhood-map-section';
    section.innerHTML = sectionMarkup(edition, activity);
    const anchor = document.querySelector('.quick-read') || document.querySelector('.neighborhood-front') || document.querySelector('.edition-heading');
    anchor?.insertAdjacentElement('afterend', section);

    const canvas = section.querySelector('[data-neighborhood-map]');
    if (!canvas) return;

    let L;
    try {
      L = await ensureLeaflet();
    } catch (_) {
      canvas.innerHTML = '<div class="map-empty">Interactive map tiles are temporarily unavailable. The highlighted activity list remains current.</div>';
      return;
    }
    if (!L) return;

    map = L.map(canvas, {scrollWheelZoom:false, zoomControl:true, attributionControl:true, preferCanvas:true});
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#9b1c20';
    const bounds = L.latLngBounds([]);
    if (activity.boundary) {
      try {
        const outline = L.geoJSON(activity.boundary, {style:{color:accent, weight:2, opacity:.88, fillColor:accent, fillOpacity:.025, dashArray:'6 5'}}).addTo(map);
        if (outline.getBounds?.().isValid()) bounds.extend(outline.getBounds());
      } catch (_) {}
    }

    const groups = new Map();
    const markers = [];
    (activity.pins || []).forEach((pin, index) => {
      const lat = Number(pin.lat);
      const lon = Number(pin.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const category = pin.category || 'other';
      if (!groups.has(category)) groups.set(category, L.layerGroup().addTo(map));
      const marker = L.marker([lat,lon], {icon:pinIcon(L, category), title:pin.title || pin.label || 'Bulletin activity'}).bindPopup(popup(pin), {maxWidth:300});
      marker.addTo(groups.get(category));
      markers[index] = marker;
      bounds.extend([lat,lon]);
    });

    if (bounds.isValid()) map.fitBounds(bounds.pad(.08), {maxZoom:16, padding:[18,18]});
    else map.setView([37.7749,-122.4194], 12);

    section.querySelectorAll('[data-map-item]').forEach((button) => {
      button.addEventListener('click', () => {
        const marker = markers[Number(button.dataset.mapItem)];
        if (!marker) return;
        map.panTo(marker.getLatLng(), {animate:true});
        marker.openPopup();
      });
    });

    section.querySelectorAll('[data-map-filter]').forEach((button) => {
      button.addEventListener('click', () => {
        const category = button.dataset.mapFilter;
        const group = groups.get(category);
        if (!group) return;
        const active = button.classList.toggle('is-active');
        button.setAttribute('aria-pressed', String(active));
        if (active) group.addTo(map); else map.removeLayer(group);
        section.querySelectorAll(`[data-map-category="${CSS.escape(category)}"]`).forEach((item) => { item.hidden = !active; });
      });
    });

    setTimeout(() => map?.invalidateSize(), 80);
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
