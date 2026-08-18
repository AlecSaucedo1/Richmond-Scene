(() => {
  const root = document.querySelector('[data-near-you]');
  if (!root) return;

  const $ = (selector) => document.querySelector(selector);
  const status = $('#nearby-status');
  const locateButton = $('#locate-me');
  const picker = $('#nearby-edition-picker');
  const results = $('#nearby-results');

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const safeUrl = (value) => {
    try {
      const url = new URL(String(value || ''), window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
    } catch (_) { return '#'; }
  };
  const money = (value) => Number(value || 0).toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
  const number = (value) => Number(value || 0).toLocaleString('en-US', {maximumFractionDigits:0});
  const formatDate = (value) => {
    if (!value) return 'Recent';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});
  };
  const trendText = (item) => item.pct_change === null || item.pct_change === undefined
    ? `${Number(item.baseline_week || 0).toFixed(1)} recent weekly average`
    : `${Number(item.pct_change) >= 0 ? '+' : ''}${Math.round(Number(item.pct_change))}% vs. recent weekly average`;

  const post = async (body) => {
    const response = await fetch('/api/near-you', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type':'application/json', 'Accept':'application/json'},
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.message || 'Unable to build the briefing');
    return payload;
  };

  const notableText = (item) => {
    const title = item.title || item.category || item.address || 'Recent record';
    const primary = [];
    if (item.address) primary.push(item.address);
    if (item.value_summary) primary.push(item.value_summary);
    else if (item.cost) primary.push(money(item.cost));
    if (item.filed_date) primary.push(`Filed ${item.filed_date}`);
    if (item.status_summary) primary.push(item.status_summary);
    else if (item.status) primary.push(item.status);

    const context = [];
    if (Array.isArray(item.project_context)) context.push(...item.project_context);
    if (Array.isArray(item.metadata)) context.push(...item.metadata);
    if (item.incident_number) context.push(`SFPD case ${item.incident_number}`);

    return `<li>
      <strong>${esc(title)}</strong>
      ${primary.length ? `<span>${esc(primary.join(' · '))}</span>` : ''}
      ${item.description ? `<span>${esc(item.description)}</span>` : ''}
      ${context.length ? `<span class="nearby-record-context">${esc(context.join(' · '))}</span>` : ''}
    </li>`;
  };

  const sectionCard = (item, slug) => {
    const localUrl = `/neighborhood/${encodeURIComponent(slug)}#story-${encodeURIComponent(item.source)}`;
    const notable = (item.notable || []).length ? `<ul class="nearby-notable">${item.notable.map(notableText).join('')}</ul>` : '';
    const facts = (item.facts || []).slice(0, 2).length ? `<ul class="fact-list compact">${item.facts.slice(0,2).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
    return `<article class="nearby-card">
      <p class="section-label">${esc(item.label)}</p>
      <h3><a href="${localUrl}">${esc(item.headline)}</a></h3>
      <p>${esc(item.dek)}</p>
      ${item.available ? `<div class="nearby-metric"><strong>${number(item.current)}</strong><span>${esc(trendText(item))}<br>Source current through ${esc(formatDate(item.latest))}</span></div>` : ''}
      ${facts}${notable}
      <div class="story-actions compact-actions">
        <a class="action-link" href="${localUrl}">Open local story →</a>
        ${item.source_url ? `<a class="action-link" href="${safeUrl(item.source_url)}" target="_blank" rel="noopener noreferrer">Data source ↗</a>` : ''}
      </div>
    </article>`;
  };

  const politicsCard = (item) => `<article class="nearby-politics-card">
    <p class="section-label">${esc(item.relevance || 'City Hall')} · ${esc(item.date || '')}</p>
    <blockquote>“${esc(item.quote)}”</blockquote>
    <h3>${esc(item.person)}</h3>
    <p>${esc(item.title)}</p>
    <span class="nearby-verdict">${esc(item.verdict)}</span>
    <p>${esc(item.analysis)}</p>
    <a class="source-link" href="${safeUrl(item.source_url)}" target="_blank" rel="noopener noreferrer">Read source →</a>
  </article>`;

  const coverageCard = (item) => `<article class="nearby-politics-card">
    <p class="section-label">${esc(item.publisher || 'Recent coverage')} · ${esc(formatDate(item.published))}</p>
    <h3><a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
    ${item.summary ? `<p>${esc(item.summary)}</p>` : ''}
    ${item.match_reason ? `<span class="nearby-verdict">${esc(item.match_reason)}</span>` : ''}
  </article>`;

  const saleCard = (sale) => {
    const search = `https://www.google.com/search?q=${encodeURIComponent(`${sale.address || ''} San Francisco real estate sale`)}`;
    return `<article class="nearby-card">
      <p class="section-label">${sale.property_group === 'commercial' ? 'Commercial / multifamily' : 'Residential'}</p>
      <h3><a href="${search}" target="_blank" rel="noopener noreferrer">${esc(sale.address_line || sale.address)}</a></h3>
      <div class="nearby-metric"><strong>${money(sale.sale_price)}</strong><span>${sale.price_per_sqft ? `${money(sale.price_per_sqft)}/sf` : 'Recorded sale'}</span></div>
      <p>${esc([sale.property_type, sale.square_feet ? `${number(sale.square_feet)} sf` : null, formatDate(sale.sale_date)].filter(Boolean).join(' · '))}</p>
    </article>`;
  };

  const renderRestaurant = (item, neighborhoodName) => {
    const container = $('#nearby-restaurant');
    if (!item) {
      container.innerHTML = `<p class="nearby-empty">No recent restaurant article could be verified for ${esc(neighborhoodName)}. The Bulletin will leave this space empty rather than substitute dining coverage from another neighborhood.</p>`;
      return;
    }
    container.innerHTML = `<article class="nearby-review-card">
      <div>
        <p class="section-label">${esc(item.match || `Neighborhood dining · verified for ${neighborhoodName}`)}</p>
        <h3><a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
        ${item.summary ? `<p>${esc(item.summary)}</p>` : ''}
        <a class="source-link" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">Read restaurant coverage →</a>
      </div>
      <div class="nearby-review-meta"><strong>${esc(item.publisher || 'Google News')}</strong><br>${esc(formatDate(item.published))}<br><br>Reviews, openings, closures, chef/menu stories and other restaurant reporting can appear here, but only when the article itself names this neighborhood or an approved neighborhood alias.</div>
    </article>`;
  };

  const render = (data) => {
    const hood = data.neighborhood;
    $('#nearby-name').textContent = hood.name;
    $('#nearby-edition-link').href = `/neighborhood/${encodeURIComponent(hood.slug)}`;
    $('#nearby-location-note').textContent = data.location_mode === 'boundary'
      ? `Your location falls inside the ${hood.name} Analysis Neighborhood.`
      : data.location_mode === 'selected'
        ? 'Showing the neighborhood edition you selected.'
        : `Showing the closest Bulletin edition${data.distance_miles !== null ? `, about ${data.distance_miles} miles away` : ''}.`;

    $('#nearby-sections').innerHTML = (data.sections || []).map((item) => sectionCard(item, hood.slug)).join('');

    const sales = data.real_estate || [];
    $('#nearby-real-estate-section').hidden = !sales.length;
    $('#nearby-real-estate').innerHTML = sales.map(saleCard).join('');

    const coverage = data.coverage || [];
    $('#nearby-coverage').innerHTML = coverage.length ? coverage.map(coverageCard).join('') : '<p class="nearby-empty">No recent local-news crossover cleared the Bulletin’s match threshold for this neighborhood.</p>';

    const politics = data.politics || [];
    $('#nearby-politics').innerHTML = politics.length ? politics.map(politicsCard).join('') : '<p class="nearby-empty">No current-year City Hall statement is specific enough to add useful local context right now.</p>';

    renderRestaurant(data.restaurant_review, hood.name);
    results.hidden = false;
    picker.value = hood.slug;
    status.textContent = `Briefing ready for ${hood.name}. Updated ${formatDate(data.generated_at)}.`;
  };

  const load = async (body) => {
    status.textContent = 'Building your local briefing…';
    locateButton.disabled = true;
    try {
      render(await post(body));
    } catch (error) {
      status.textContent = `${error.message}. Choose a neighborhood below to continue.`;
      results.hidden = true;
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
      (position) => load({lat: position.coords.latitude, lon: position.coords.longitude}),
      () => {
        locateButton.disabled = false;
        status.textContent = 'Location permission was not available. Choose a neighborhood below, or try again.';
      },
      {enableHighAccuracy:false, timeout:10000, maximumAge:300000}
    );
  };

  locateButton.addEventListener('click', locate);
  picker.addEventListener('change', () => { if (picker.value) load({slug: picker.value}); });

  // Ask once when the tab opens. The browser controls the permission prompt and remembers its state.
  locate();
})();
