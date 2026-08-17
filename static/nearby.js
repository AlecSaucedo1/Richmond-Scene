(() => {
  const root = document.querySelector('[data-near-you]');
  if (!root) return;

  const locateButton = document.getElementById('locate-me');
  const picker = document.getElementById('nearby-edition-picker');
  const status = document.getElementById('nearby-status');
  const results = document.getElementById('nearby-results');
  const name = document.getElementById('nearby-name');
  const note = document.getElementById('nearby-location-note');
  const editionLink = document.getElementById('nearby-edition-link');
  const sections = document.getElementById('nearby-sections');
  const politics = document.getElementById('nearby-politics');
  const restaurant = document.getElementById('nearby-restaurant');

  const esc = (value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  const safeUrl = (value) => {
    try {
      const url = new URL(String(value || ''), window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
    } catch (_) {
      return '#';
    }
  };

  const formatDate = (value) => {
    if (!value) return 'Recent';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return esc(value);
    return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const trendText = (item) => {
    if (item.pct_change === null || item.pct_change === undefined) {
      return `${Number(item.baseline_week || 0).toFixed(1)} recent weekly average`;
    }
    const pct = Number(item.pct_change);
    if (Math.abs(pct) < 8) return 'roughly in line with the recent weekly average';
    return `${Math.abs(pct).toFixed(0)}% ${pct > 0 ? 'above' : 'below'} the recent weekly average`;
  };

  const notableText = (item) => {
    const title = item.title || item.category || 'Recent record';
    const details = [];
    if (item.address) details.push(item.address);
    if (item.count) details.push(`${item.count} reports`);
    if (item.cost) details.push(`$${Number(item.cost).toLocaleString()}`);
    if (item.status) details.push(item.status);
    return `<li><strong>${esc(title)}</strong>${details.length ? esc(details.join(' · ')) : ''}${item.description ? `<br>${esc(item.description)}` : ''}</li>`;
  };

  const renderSections = (items) => {
    sections.innerHTML = items.map((item) => {
      if (!item.available) {
        return `<article class="nearby-card"><p class="section-label">${esc(item.label)}</p><h3>${esc(item.headline)}</h3><p>${esc(item.dek)}</p></article>`;
      }
      const notable = (item.notable || []).length
        ? `<ul class="nearby-notable">${item.notable.map(notableText).join('')}</ul>`
        : '';
      return `<article class="nearby-card">
        <p class="section-label">${esc(item.label)}</p>
        <h3>${esc(item.headline)}</h3>
        <p>${esc(item.dek)}</p>
        <div class="nearby-metric"><strong>${esc(item.current)}</strong><span>${esc(trendText(item))}<br>Source current through ${esc(formatDate(item.latest))}</span></div>
        ${notable}
        <a class="source-link" href="${safeUrl(item.source_url)}" target="_blank" rel="noopener">Open source data →</a>
      </article>`;
    }).join('');
  };

  const renderPolitics = (items) => {
    if (!items.length) {
      politics.innerHTML = '<p class="nearby-empty">No current-year City Hall statement in the Bulletin is specific enough to test against this neighborhood yet.</p>';
      return;
    }
    politics.innerHTML = items.map((item) => `<article class="nearby-politics-card">
      <p class="section-label">${esc(item.relevance)} · ${esc(item.date)}</p>
      <blockquote>“${esc(item.quote)}”</blockquote>
      <h3>${esc(item.person)}</h3>
      <p>${esc(item.title)}</p>
      <span class="nearby-verdict">${esc(item.verdict)}</span>
      <p>${esc(item.analysis)}</p>
      <a class="source-link" href="${safeUrl(item.source_url)}" target="_blank" rel="noopener">Read source →</a>
    </article>`).join('');
  };

  const renderRestaurant = (item) => {
    if (!item) {
      restaurant.innerHTML = '<p class="nearby-empty">Restaurant-review coverage is temporarily unavailable. The feed will retry at the next scheduled Bulletin refresh.</p>';
      return;
    }
    restaurant.innerHTML = `<article class="nearby-review-card">
      <div>
        <p class="section-label">${esc(item.match || 'Recent San Francisco review')}</p>
        <h3>${esc(item.title)}</h3>
        ${item.summary ? `<p>${esc(item.summary)}</p>` : ''}
        <a class="source-link" href="${safeUrl(item.url)}" target="_blank" rel="noopener">Read the review →</a>
      </div>
      <div class="nearby-review-meta"><strong>${esc(item.publisher || 'Google News')}</strong><br>${esc(formatDate(item.published))}<br><br>The dining feed is refreshed with the rest of the Bulletin and favors coverage that names the selected neighborhood.</div>
    </article>`;
  };

  const render = (data) => {
    name.textContent = data.neighborhood.name;
    editionLink.href = `/neighborhood/${encodeURIComponent(data.neighborhood.slug)}`;
    if (data.location_mode === 'nearest') {
      const distance = data.distance_miles === null ? '' : ` about ${data.distance_miles} mi from your location`;
      note.textContent = data.outside_sf
        ? `You appear to be outside San Francisco. Showing the closest city edition:${distance}.`
        : `Selected as the closest Bulletin edition${distance}.`;
    } else {
      note.textContent = 'Showing the neighborhood edition you selected.';
    }
    renderSections(data.sections || []);
    renderPolitics(data.politics || []);
    renderRestaurant(data.restaurant_review);
    results.hidden = false;
    status.textContent = `Briefing ready for ${data.neighborhood.name}.`;
    results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const load = async (url) => {
    status.textContent = 'Building your local briefing…';
    locateButton.disabled = true;
    try {
      const response = await fetch(url, { credentials: 'same-origin' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.message || 'Unable to build the briefing');
      render(payload);
    } catch (error) {
      status.textContent = `${error.message}. Choose a neighborhood below to continue.`;
    } finally {
      locateButton.disabled = false;
    }
  };

  const locate = () => {
    if (!navigator.geolocation) {
      status.textContent = 'Location services are not available in this browser. Choose a neighborhood below.';
      return;
    }
    status.textContent = 'Requesting your location…';
    locateButton.disabled = true;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = encodeURIComponent(position.coords.latitude.toFixed(6));
        const lng = encodeURIComponent(position.coords.longitude.toFixed(6));
        load(`/api/happenings?lat=${lat}&lng=${lng}`);
      },
      () => {
        locateButton.disabled = false;
        status.textContent = 'Location permission was not available. Choose a neighborhood below, or try again.';
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
    );
  };

  locateButton.addEventListener('click', locate);
  picker.addEventListener('change', () => {
    if (picker.value) load(`/api/happenings?slug=${encodeURIComponent(picker.value)}`);
  });

  if (navigator.permissions?.query) {
    navigator.permissions.query({ name: 'geolocation' }).then((permission) => {
      if (permission.state === 'granted') locate();
    }).catch(() => {});
  }
})();
