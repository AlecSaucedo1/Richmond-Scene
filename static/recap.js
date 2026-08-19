(() => {
  const root = document.querySelector('[data-bulletin-recap]');
  if (!root) return;

  const play = root.querySelector('[data-recap-play]');
  const status = root.querySelector('[data-recap-status]');
  const duration = root.querySelector('[data-recap-duration]');
  const updated = root.querySelector('[data-recap-updated]');
  const transcript = root.querySelector('[data-recap-transcript]');
  const progress = root.querySelector('[data-recap-progress]');
  const transcriptToggle = root.querySelector('[data-recap-toggle]');

  let snapshotGeneratedAt = '';
  let recapText = '';
  let utterance = null;
  let speaking = false;
  let paused = false;

  const escText = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
  const words = (value) => escText(value).split(/\s+/).filter(Boolean);
  const wordCount = (value) => words(value).length;
  const firstSentence = (value, maxWords = 26) => {
    const clean = escText(value);
    if (!clean) return '';
    const sentence = clean.match(/^.*?[.!?](?:\s|$)/)?.[0] || clean;
    const parts = words(sentence);
    return parts.length <= maxWords ? sentence : `${parts.slice(0, maxWords).join(' ')}.`;
  };
  const cleanHeadline = (value) => escText(value).replace(/\s+-\s+[^-]{2,45}$/,'');
  const formatDate = (value, options = {}) => {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US', {month:'long', day:'numeric', ...options});
  };
  const formatUpdated = (value) => {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
  };
  const shortMoney = (value) => {
    const n = Number(value || 0);
    if (!n) return '';
    if (n >= 1000000) return `$${(n / 1000000).toFixed(n >= 10000000 ? 0 : 1)} million`;
    if (n >= 1000) return `$${Math.round(n / 1000)} thousand`;
    return `$${Math.round(n)}`;
  };
  const timeLabel = (seconds) => {
    const rounded = Math.max(1, Math.round(seconds / 5) * 5);
    const mins = Math.floor(rounded / 60);
    const secs = rounded % 60;
    return `${mins}:${String(secs).padStart(2, '0')}`;
  };

  function storySelection(data) {
    const picked = [];
    const usedHoods = new Set();
    const usedSources = new Set();
    const candidates = [...(data.front_page || [])].sort((a,b) => Number(b.interest || 0) - Number(a.interest || 0));
    for (const item of candidates) {
      if (!item?.headline || usedHoods.has(item.name)) continue;
      const source = item.source || '';
      if (usedSources.has(source) && picked.length < 2) continue;
      picked.push(item);
      usedHoods.add(item.name);
      if (source) usedSources.add(source);
      if (picked.length >= 3) break;
    }
    return picked;
  }

  function diningSelection(data) {
    const items = (data.restaurant_reviews || []).filter((item) =>
      (item.restaurant_verified || item.review_verified) &&
      Array.isArray(item.verified_neighborhoods) && item.verified_neighborhoods.length
    );
    items.sort((a,b) => String(b.published || '').localeCompare(String(a.published || '')));
    return items[0] || null;
  }

  function artsSelection(data) {
    const arts = data.arts || {};
    const exhibit = (arts.exhibitions || []).find((x) => x.status === 'On view') || (arts.exhibitions || [])[0] || null;
    const event = (arts.events || [])[0] || null;
    return {exhibit, event};
  }

  function realEstateSelection(data) {
    const city = data?.real_estate?.city || {};
    return (city.largest || city.largest_residential || city.largest_commercial || [])[0] || null;
  }

  function buildRecap(data) {
    const generated = data.generated_at ? new Date(data.generated_at) : new Date();
    const day = generated.toLocaleDateString('en-US', {weekday:'long', month:'long', day:'numeric'});
    const parts = [`You're listening to the San Francisco Bulletin Brief for ${day}. Here's what stands out across the city.`];

    const stories = storySelection(data);
    stories.forEach((item, index) => {
      const lead = index === 0 ? 'First' : index === 1 ? 'Elsewhere' : 'Also worth watching';
      const detail = firstSentence(item.dek, index === 0 ? 30 : 24);
      parts.push(`${lead}, in ${item.name}: ${cleanHeadline(item.headline)}.${detail ? ` ${detail}` : ''}`);
    });

    const dining = diningSelection(data);
    if (dining) {
      const hood = dining.verified_neighborhoods?.[0] || 'San Francisco';
      const publisher = escText(dining.publisher || 'local reporting');
      parts.push(`On the dining desk, ${publisher} has recent coverage in ${hood}: ${cleanHeadline(dining.title)}.`);
    }

    const {exhibit, event} = artsSelection(data);
    if (exhibit) {
      const end = exhibit.end_date ? ` through ${formatDate(exhibit.end_date)}` : '';
      parts.push(`In arts, ${cleanHeadline(exhibit.title)} is ${String(exhibit.status || 'on view').toLowerCase()} at ${exhibit.museum}${end}.`);
    }
    if (event) {
      const when = event.start_date ? ` on ${formatDate(event.start_date)}` : '';
      parts.push(`And on the calendar, ${cleanHeadline(event.title)} comes to ${event.venue}${when}.`);
    }

    const sale = realEstateSelection(data);
    if (sale?.sale_price && sale?.address) {
      parts.push(`In real estate, the largest transaction on the current tape is ${shortMoney(sale.sale_price)} at ${sale.address_line || sale.address}${sale.neighborhood ? ` in ${sale.neighborhood}` : ''}.`);
    }

    const policeThrough = data?.source_dates?.police?.latest_report;
    if (policeThrough) parts.push(`SFPD open-data reports are currently filed through ${formatDate(policeThrough)}.`);

    parts.push('That’s your Bulletin Brief. Open any neighborhood edition for the records, reporting, dining, real estate and arts behind the headlines.');

    // About 225 words at the relaxed narration rate lands close to 90 seconds.
    const maxWords = 235;
    const all = parts.join(' ').replace(/\.\./g, '.');
    const tokens = words(all);
    return tokens.length <= maxWords ? all : `${tokens.slice(0, maxWords - 11).join(' ')}. That’s your Bulletin Brief. Read more across the neighborhood editions.`;
  }

  function chooseVoice() {
    const available = window.speechSynthesis?.getVoices?.() || [];
    const english = available.filter((v) => /^en(-|_)/i.test(v.lang || ''));
    const preferredNames = ['Samantha', 'Ava', 'Evan', 'Daniel', 'Alex', 'Karen'];
    for (const name of preferredNames) {
      const match = english.find((v) => (v.name || '').includes(name));
      if (match) return match;
    }
    return english.find((v) => v.localService) || english[0] || available[0] || null;
  }

  function stopNarration(reset = true) {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    utterance = null;
    speaking = false;
    paused = false;
    play.textContent = 'Play brief';
    play.setAttribute('aria-pressed', 'false');
    status.textContent = recapText ? 'Ready to play' : 'Building latest brief…';
    if (reset && progress) progress.style.width = '0%';
  }

  function startNarration() {
    if (!recapText || !('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    utterance = new SpeechSynthesisUtterance(recapText);
    utterance.lang = 'en-US';
    utterance.rate = 0.88;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    const voice = chooseVoice();
    if (voice) utterance.voice = voice;
    utterance.onstart = () => {
      speaking = true;
      paused = false;
      play.textContent = 'Pause';
      play.setAttribute('aria-pressed', 'true');
      status.textContent = 'Playing latest brief';
    };
    utterance.onboundary = (event) => {
      if (typeof event.charIndex === 'number' && recapText.length && progress) {
        progress.style.width = `${Math.min(98, Math.round(event.charIndex / recapText.length * 100))}%`;
      }
    };
    utterance.onend = () => {
      speaking = false;
      paused = false;
      play.textContent = 'Replay brief';
      play.setAttribute('aria-pressed', 'false');
      status.textContent = 'Brief complete';
      if (progress) progress.style.width = '100%';
    };
    utterance.onerror = () => {
      speaking = false;
      paused = false;
      play.textContent = 'Play brief';
      play.setAttribute('aria-pressed', 'false');
      status.textContent = 'Narration unavailable — transcript is ready';
    };
    window.speechSynthesis.speak(utterance);
  }

  async function refreshRecap() {
    try {
      const response = await fetch('/api/bulletin', {headers:{Accept:'application/json'}, cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      if (!data?.generated_at || data.generated_at === snapshotGeneratedAt) return;
      snapshotGeneratedAt = data.generated_at;
      const next = buildRecap(data);
      if (!next) return;
      if (speaking || paused) stopNarration();
      recapText = next;
      transcript.textContent = recapText;
      const count = wordCount(recapText);
      const estimate = count / 155 * 60;
      duration.textContent = `About ${timeLabel(estimate)} · ${count} words`;
      updated.textContent = `Updated ${formatUpdated(data.generated_at)}`;
      status.textContent = 'Ready to play';
      play.disabled = false;
      if (!('speechSynthesis' in window)) {
        play.disabled = true;
        status.textContent = 'Audio narration is not supported by this browser — transcript is available';
      }
    } catch (_) {
      status.textContent = recapText ? status.textContent : 'Brief temporarily unavailable';
    }
  }

  play?.addEventListener('click', async () => {
    if (!('speechSynthesis' in window)) return;
    if (speaking && !paused) {
      window.speechSynthesis.pause();
      paused = true;
      play.textContent = 'Resume';
      status.textContent = 'Paused';
      return;
    }
    if (speaking && paused) {
      window.speechSynthesis.resume();
      paused = false;
      play.textContent = 'Pause';
      status.textContent = 'Playing latest brief';
      return;
    }
    // A play request always checks the current snapshot first, so a page left open
    // across the scheduled 7 a.m. / 6 p.m. refresh narrates the newest edition.
    await refreshRecap();
    startNarration();
  });

  transcriptToggle?.addEventListener('click', () => {
    const isHidden = transcript.hidden;
    transcript.hidden = !isHidden;
    transcriptToggle.textContent = isHidden ? 'Hide transcript' : 'Transcript';
    transcriptToggle.setAttribute('aria-expanded', String(isHidden));
  });

  if ('speechSynthesis' in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener?.('voiceschanged', () => window.speechSynthesis.getVoices());
  }
  window.addEventListener('pagehide', () => stopNarration(false));
  refreshRecap();
  // A long-open page updates automatically; playback also performs an immediate check.
  window.setInterval(refreshRecap, 5 * 60 * 1000);
})();
