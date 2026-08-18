(() => {
  const match = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
  if (!match) return;

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const safeUrl = (value) => {
    try {
      const url = new URL(String(value || ''), window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
    } catch (_) { return '#'; }
  };
  const dateLabel = (value) => {
    if (!value) return 'Recent';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});
  };

  const select = (items, neighborhood) => {
    const candidates = (items || []).filter((item) =>
      (item.restaurant_verified || item.review_verified) &&
      Array.isArray(item.verified_neighborhoods) &&
      item.verified_neighborhoods.includes(neighborhood)
    );
    candidates.sort((a, b) => String(b.published || '').localeCompare(String(a.published || '')));
    return candidates[0] || null;
  };

  async function render() {
    const response = await fetch('/api/bulletin', {headers:{Accept:'application/json'}});
    if (!response.ok) return;
    const snapshot = await response.json();
    const edition = snapshot?.editions?.[match[1]];
    if (!edition) return;

    const item = select(snapshot.restaurant_reviews, edition.name);
    const section = document.createElement('section');
    section.className = 'neighborhood-dining';
    section.id = 'dining';

    if (item) {
      const evidence = item?.neighborhood_evidence?.[edition.name] || edition.name;
      section.innerHTML = `
        <div class="dining-heading">
          <div><p class="section-label">NEIGHBORHOOD DINING</p><h2>At the table in ${esc(edition.name)}</h2></div>
          <span>${esc(item.restaurant_story_type || 'Restaurant news')}</span>
        </div>
        <article class="dining-story">
          <div class="dining-copy">
            <p class="dining-meta">${esc(item.publisher || 'Recent coverage')} · ${esc(dateLabel(item.published))}</p>
            <h3><a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
            ${item.summary ? `<p>${esc(item.summary)}</p>` : ''}
            <a class="action-link primary" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">Read restaurant coverage ↗</a>
          </div>
          <aside class="dining-note"><strong>Why it’s here</strong><span>The article explicitly names ${esc(evidence)} and was matched to the ${esc(edition.name)} edition. The Bulletin does not substitute restaurant stories from other neighborhoods.</span></aside>
        </article>`;
    } else {
      section.innerHTML = `
        <div class="dining-heading"><div><p class="section-label">NEIGHBORHOOD DINING</p><h2>At the table in ${esc(edition.name)}</h2></div></div>
        <div class="dining-empty"><strong>No recent restaurant article verified for this neighborhood.</strong><span>The Bulletin will leave this section open rather than fill it with dining coverage from elsewhere in San Francisco or the Bay Area.</span></div>`;
    }

    const firstRule = document.querySelector('.section-rule');
    if (firstRule) firstRule.insertAdjacentElement('beforebegin', section);
    else document.querySelector('main')?.appendChild(section);
  }

  render().catch(() => {});
})();
