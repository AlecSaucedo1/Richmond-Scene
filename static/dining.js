(() => {
  const match = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
  if (!match) return;

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const norm = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
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
  const ageDays = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 999;
    return Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
  };
  const recency = (days) => days <= 7 ? 52 : days <= 30 ? 42 : days <= 90 ? 31 : days <= 180 ? 21 : days <= 270 ? 13 : days <= 365 ? 7 : -30;
  const publisherScore = (publisher) => {
    const name = norm(publisher);
    const weights = [
      ['san francisco chronicle',24],['kqed',23],['sf standard',22],['mission local',21],
      ['eater',20],['san francisco examiner',19],['sfist',17],['ingleside light',17],
      ['richmond review',17],['sunset beacon',17],['potrero view',17],['marina times',16],
      ['48 hills',14],['abc7',13],['nbc bay area',13],['cbs bay area',13],['ktvu',13],['kron4',12],['hoodline',10]
    ];
    return weights.find(([term]) => name.includes(term))?.[1] || (name ? 4 : 0);
  };
  const confidenceScore = (item, neighborhood) => {
    const confidence = item?.neighborhood_confidence?.[neighborhood] || (item.verified_neighborhoods?.includes(neighborhood) ? 'explicit' : '');
    return {explicit:42,targeted_notable:29,targeted_sf:22,targeted_search:12}[confidence] || 0;
  };

  const select = (items, neighborhood) => {
    const candidates = (items || []).filter((item) =>
      (item.restaurant_verified || item.review_verified) &&
      Array.isArray(item.verified_neighborhoods) &&
      item.verified_neighborhoods.includes(neighborhood) &&
      ageDays(item.published) <= 365
    );
    const ranked = candidates.map((item) => {
      const evidence = item?.neighborhood_evidence?.[neighborhood] || neighborhood;
      const days = ageDays(item.published);
      let score = confidenceScore(item, neighborhood) + publisherScore(item.publisher) + recency(days);
      const title = ` ${norm(item.title)} `;
      if (norm(evidence) && title.includes(` ${norm(evidence)} `)) score += 9;
      if (['Restaurant opening','Restaurant closure','Restaurant review'].includes(item.restaurant_story_type)) score += 5;
      return {item, score, days};
    });
    ranked.sort((a, b) => b.score - a.score || String(b.item.published || '').localeCompare(String(a.item.published || '')));
    return ranked[0] ? {...ranked[0].item, restaurant_rank: ranked[0].score, restaurant_age_days: ranked[0].days} : null;
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
      const confidence = item?.neighborhood_confidence?.[edition.name] || 'explicit';
      const evidence = item?.neighborhood_evidence?.[edition.name] || edition.name;
      const why = confidence === 'explicit'
        ? `The article names ${evidence} and was matched to the ${edition.name} edition.`
        : `This article surfaced in a targeted ${edition.name} search and passed the Bulletin’s San Francisco location checks.`;
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
          <aside class="dining-note"><strong>Why it’s here</strong><span>${esc(why)} Newer reporting is weighted more heavily, while credible coverage up to a year old remains eligible when a neighborhood has less frequent dining news.</span></aside>
        </article>`;
    } else {
      section.innerHTML = `
        <div class="dining-heading"><div><p class="section-label">NEIGHBORHOOD DINING</p><h2>At the table in ${esc(edition.name)}</h2></div></div>
        <div class="dining-empty"><strong>Neighborhood dining coverage is being refreshed.</strong><span>The Bulletin searches a full year of local reporting and favors the newest credible match for this edition.</span></div>`;
    }

    const firstRule = document.querySelector('.section-rule');
    if (firstRule) firstRule.insertAdjacentElement('beforebegin', section);
    else document.querySelector('main')?.appendChild(section);
  }

  render().catch(() => {});
})();
