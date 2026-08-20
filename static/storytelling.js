(() => {
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const safeUrl = (value) => { try { const u = new URL(String(value || ''), location.origin); return ['http:','https:'].includes(u.protocol) ? u.href : '#'; } catch (_) { return '#'; } };
  const dateLabel = (value) => {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return 'Recent';
    const now = new Date();
    const hours = Math.max(0, (now - d) / 36e5);
    if (hours < 1) return 'Less than an hour ago';
    if (hours < 24) return `${Math.max(1, Math.floor(hours))}h ago`;
    if (hours < 48) return 'Yesterday';
    return d.toLocaleDateString('en-US', {month:'short', day:'numeric'});
  };

  async function getSnapshot() {
    const response = await fetch('/api/bulletin', {headers:{Accept:'application/json'}, cache:'no-store'});
    if (!response.ok) return null;
    return response.json();
  }

  function notebook(story, compact=false) {
    const items = Array.isArray(story?.color_items) ? story.color_items.filter(Boolean).slice(0, compact ? 2 : 4) : [];
    if (!items.length && !story?.reader_hook && !story?.refresh_note) return '';
    return `<div class="story-notebook${compact ? ' compact' : ''}">
      ${items.length ? `<div class="story-notebook-items"><span>ON THE BLOCK</span>${items.map((x) => `<em>${esc(x)}</em>`).join('')}</div>` : ''}
      ${story?.reader_hook ? `<p><strong>Why it’s worth watching:</strong> ${esc(story.reader_hook)}</p>` : ''}
      ${story?.refresh_note ? `<p class="story-refresh-note"><strong>This edition:</strong> ${esc(story.refresh_note)}</p>` : ''}
    </div>`;
  }

  function enrichRenderedStories(data) {
    const path = location.pathname;
    if (path === '/') {
      (data.front_page || []).forEach((story) => {
        const selector = `[data-href="/neighborhood/${CSS.escape(story.slug || '')}#story-${CSS.escape(story.source || '')}"]`;
        const card = document.querySelector(selector);
        if (!card || card.querySelector('.story-notebook')) return;
        const actions = card.querySelector('.story-actions, .post-cue, .web-context');
        if (actions) actions.insertAdjacentHTML('beforebegin', notebook(story, true));
        else card.insertAdjacentHTML('beforeend', notebook(story, true));
      });
      document.querySelectorAll('[data-edition-card]').forEach((card) => {
        const source = card.dataset.source;
        const href = card.dataset.href || '';
        const slug = href.split('/').filter(Boolean).pop();
        const story = data?.editions?.[slug]?.stories?.find((x) => x.source === source);
        if (!story || card.querySelector('.story-notebook')) return;
        const foot = card.querySelector('.edition-card-foot');
        (foot || card).insertAdjacentHTML(foot ? 'beforebegin' : 'beforeend', notebook(story, true));
      });
    }

    const match = path.match(/^\/neighborhood\/([^/]+)/);
    if (!match) return;
    const edition = data?.editions?.[match[1]];
    if (!edition) return;
    const lead = edition.lead;
    const leadEl = document.querySelector('.lead-story');
    if (lead && leadEl && !leadEl.querySelector('.story-notebook')) {
      const actions = leadEl.querySelector('.story-actions');
      (actions || leadEl).insertAdjacentHTML(actions ? 'beforebegin' : 'beforeend', notebook(lead, false));
    }
    (edition.stories || []).forEach((story) => {
      if (lead && story.source === lead.source) return;
      const card = document.querySelector(`#story-${CSS.escape(story.source || '')}`);
      if (!card || card.querySelector('.story-notebook')) return;
      const details = card.querySelector('.story-details');
      (details || card).insertAdjacentHTML(details ? 'beforebegin' : 'beforeend', notebook(story, true));
    });
  }

  function renderRefreshStrip(data) {
    const match = location.pathname.match(/^\/neighborhood\/([^/]+)/);
    if (!match || document.querySelector('.edition-refresh-strip')) return;
    const edition = data?.editions?.[match[1]];
    if (!edition?.refresh_changes?.length) return;
    const changed = edition.refresh_changes.filter((x) => x.changed);
    const rows = (changed.length ? changed : edition.refresh_changes).slice(0, 4);
    const section = document.createElement('section');
    section.className = 'edition-refresh-strip';
    section.innerHTML = `<div class="edition-refresh-head"><p class="section-label">SINCE THE LAST EDITION</p><span>${esc(data?.storytelling?.edition_slot || 'latest')} refresh</span></div><div class="edition-refresh-grid">${rows.map((x) => `<div class="edition-refresh-item${x.changed ? ' changed' : ''}"><strong>${esc(x.label)}</strong><p>${esc(x.note)}</p></div>`).join('')}</div>`;
    const anchor = document.querySelector('.quick-read') || document.querySelector('.neighborhood-front');
    anchor?.insertAdjacentElement('afterend', section);
  }

  function renderLiveDigest(data) {
    if (location.pathname !== '/' || document.querySelector('.live-digest')) return;
    const items = data?.live_digest || [];
    if (!items.length) return;
    const section = document.createElement('section');
    section.className = 'live-digest';
    section.innerHTML = `<div class="live-digest-head"><div><p class="section-label">THE REFRESH</p><h2>New reporting around San Francisco</h2><p>Fresh local coverage, diversified by neighborhood and publisher. This wire changes as new reporting lands between Bulletin editions.</p></div><span>${esc(data?.storytelling?.edition_slot || 'Latest')} edition</span></div><div class="live-digest-grid">${items.map((item) => `<a class="live-digest-card" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer"><div class="live-digest-meta"><span class="${item.is_new_refresh ? 'is-new' : ''}">${item.is_new_refresh ? 'NEW THIS EDITION' : dateLabel(item.published)}</span><span>${esc(item.digest_neighborhood || 'San Francisco')}</span></div><h3>${esc(item.title)}</h3>${item.summary ? `<p>${esc(item.summary)}</p>` : ''}<footer><strong>${esc(item.publisher || 'Local reporting')}</strong><span>${dateLabel(item.published)} ↗</span></footer></a>`).join('')}</div>`;
    const anchor = document.querySelector('.front-grid') || document.querySelector('.date-line');
    anchor?.insertAdjacentElement('afterend', section);
  }

  async function run() {
    const data = await getSnapshot();
    if (!data) return;
    enrichRenderedStories(data);
    renderRefreshStrip(data);
    renderLiveDigest(data);
  }

  run().catch(() => {});
})();
