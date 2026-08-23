(() => {
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const safeUrl = (value) => {
    try {
      const url = new URL(String(value || ''), window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
    } catch (_) { return '#'; }
  };

  async function post(body) {
    const response = await fetch('/api/near-you', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type':'application/json', 'Accept':'application/json'},
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.message || 'Unable to resolve the neighborhood');
    return payload;
  }

  function canonicalEditionUrl(slug) {
    return `/neighborhood/${encodeURIComponent(String(slug || '').trim())}`;
  }

  function setupNearYouGateway() {
    const root = document.querySelector('[data-near-you]');
    if (!root) return;
    const status = document.querySelector('#nearby-status');
    const locateButton = document.querySelector('#locate-me');
    const picker = document.querySelector('#nearby-edition-picker');
    if (!status || !locateButton || !picker) return;

    const openEdition = (slug) => {
      if (!slug) return;
      status.textContent = 'Opening the complete neighborhood Bulletin…';
      window.location.assign(canonicalEditionUrl(slug));
    };

    const locate = () => {
      if (!navigator.geolocation) {
        status.textContent = 'Location services are not available in this browser. Choose a neighborhood below.';
        return;
      }
      status.textContent = 'Requesting your location…';
      locateButton.disabled = true;
      navigator.geolocation.getCurrentPosition(
        async (position) => {
          try {
            status.textContent = 'Matching your location to a San Francisco neighborhood…';
            const data = await post({lat: position.coords.latitude, lon: position.coords.longitude});
            const slug = data?.neighborhood?.slug;
            if (!slug) throw new Error('The neighborhood could not be resolved');
            openEdition(slug);
          } catch (error) {
            locateButton.disabled = false;
            status.textContent = `${error.message}. Choose a neighborhood below to continue.`;
          }
        },
        () => {
          locateButton.disabled = false;
          status.textContent = 'Location permission was not available. Choose a neighborhood below, or try again.';
        },
        {enableHighAccuracy:false, timeout:10000, maximumAge:300000}
      );
    };

    locateButton.addEventListener('click', locate);
    picker.addEventListener('change', () => openEdition(picker.value));
    locate();
  }

  function metricList(metrics) {
    if (!Array.isArray(metrics) || !metrics.length) return '';
    return `<ul class="fact-list compact">${metrics.map((item) => `<li><strong>${esc(item.label)}:</strong> ${esc(item.value)}</li>`).join('')}</ul>`;
  }

  function politicsCard(item) {
    return `<article class="nearby-politics-card">
      <p class="section-label">${esc(item.relevance || 'Citywide')} · ${esc(item.date || '')}</p>
      <blockquote>“${esc(item.quote || '')}”</blockquote>
      <h3>${esc(item.person || '')}</h3>
      <p>${esc(item.title || '')}</p>
      <span class="nearby-verdict">${esc(item.verdict || 'Context')}</span>
      ${metricList(item.metrics)}
      <p>${esc(item.analysis || '')}</p>
      ${item.wrinkle ? `<p><strong>Important caveat:</strong> ${esc(item.wrinkle)}</p>` : ''}
      ${item.source_url ? `<a class="source-link" href="${safeUrl(item.source_url)}" target="_blank" rel="noopener noreferrer">Read source →</a>` : ''}
    </article>`;
  }

  async function renderNeighborhoodCityHall() {
    const match = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
    if (!match || document.querySelector('.neighborhood-city-hall')) return;
    let data;
    try {
      data = await post({slug: match[1]});
    } catch (_) {
      return;
    }
    const politics = data?.politics || [];
    const section = document.createElement('section');
    section.className = 'neighborhood-city-hall';
    section.id = 'city-hall-context';
    section.innerHTML = `
      <div class="section-rule"><h2>City Hall near you</h2><p>Current-year statements the Bulletin’s existing public-record feeds can meaningfully put in local context.</p></div>
      <div class="nearby-politics">${politics.length ? politics.map(politicsCard).join('') : '<p class="nearby-empty">No current-year City Hall statement is specific enough to add useful local context to this edition right now.</p>'}</div>`;
    const methodology = document.querySelector('.methodology');
    if (methodology) methodology.insertAdjacentElement('beforebegin', section);
    else document.querySelector('main')?.appendChild(section);
  }

  setupNearYouGateway();
  renderNeighborhoodCityHall().catch(() => {});
})();
