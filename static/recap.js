(() => {
  const root = document.querySelector('[data-bulletin-recap]');
  if (!root) return;

  const play = root.querySelector('[data-recap-play]');
  const status = root.querySelector('[data-recap-status]');
  const duration = root.querySelector('[data-recap-duration]');
  const updated = root.querySelector('[data-recap-updated]');
  const voiceLabel = root.querySelector('[data-recap-voice]');
  const transcript = root.querySelector('[data-recap-transcript]');
  const progress = root.querySelector('[data-recap-progress]');
  const transcriptToggle = root.querySelector('[data-recap-toggle]');

  const audio = new Audio();
  audio.preload = 'metadata';
  let snapshotGeneratedAt = '';
  let recapText = '';
  let neuralReady = false;
  let fallbackUtterance = null;
  let fallbackSpeaking = false;
  let fallbackPaused = false;

  const clean = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
  const words = (value) => clean(value).split(/\s+/).filter(Boolean);
  const timeLabel = (seconds) => {
    const total = Math.max(1, Math.round(Number(seconds || 0)));
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return `${mins}:${String(secs).padStart(2, '0')}`;
  };
  const dateTimeLabel = (value) => {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
  };

  function fallbackRecap(data) {
    const generated = data.generated_at ? new Date(data.generated_at) : new Date();
    const day = generated.toLocaleDateString('en-US', {weekday:'long', month:'long', day:'numeric'});
    const parts = [`You're listening to the San Francisco Bulletin Brief for ${day}. Here's what stands out across the city.`];
    const stories = [...(data.front_page || [])].sort((a,b) => Number(b.interest || 0) - Number(a.interest || 0));
    const used = new Set();
    for (const item of stories) {
      if (!item?.headline || used.has(item.name)) continue;
      used.add(item.name);
      parts.push(`${parts.length === 1 ? 'First' : 'Elsewhere'}, in ${clean(item.name)}: ${clean(item.headline)}. ${clean(item.dek || '')}`);
      if (used.size >= 3) break;
    }
    parts.push("That's your Bulletin Brief. Open any neighborhood edition for the reporting and public records behind the headlines.");
    const all = clean(parts.join(' '));
    const tokens = words(all);
    return tokens.length <= 235 ? all : `${tokens.slice(0, 224).join(' ')}. That's your Bulletin Brief.`;
  }

  function chooseFallbackVoice() {
    const available = window.speechSynthesis?.getVoices?.() || [];
    const english = available.filter((v) => /^en(-|_)/i.test(v.lang || ''));
    const preferred = ['Ava', 'Samantha', 'Evan', 'Daniel', 'Alex', 'Karen'];
    for (const name of preferred) {
      const match = english.find((v) => (v.name || '').includes(name));
      if (match) return match;
    }
    return english.find((v) => v.localService) || english[0] || available[0] || null;
  }

  function stopFallback() {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    fallbackUtterance = null;
    fallbackSpeaking = false;
    fallbackPaused = false;
  }

  function startFallback() {
    if (!recapText || !('speechSynthesis' in window)) return;
    stopFallback();
    fallbackUtterance = new SpeechSynthesisUtterance(recapText);
    fallbackUtterance.lang = 'en-US';
    fallbackUtterance.rate = 0.92;
    fallbackUtterance.pitch = 1;
    const voice = chooseFallbackVoice();
    if (voice) fallbackUtterance.voice = voice;
    fallbackUtterance.onstart = () => {
      fallbackSpeaking = true;
      fallbackPaused = false;
      play.textContent = 'Pause';
      play.setAttribute('aria-pressed', 'true');
      status.textContent = 'Playing browser fallback voice';
    };
    fallbackUtterance.onend = () => {
      fallbackSpeaking = false;
      fallbackPaused = false;
      play.textContent = 'Replay brief';
      play.setAttribute('aria-pressed', 'false');
      status.textContent = 'Brief complete';
      if (progress) progress.style.width = '100%';
    };
    fallbackUtterance.onerror = () => {
      fallbackSpeaking = false;
      fallbackPaused = false;
      play.textContent = 'Play brief';
      play.setAttribute('aria-pressed', 'false');
      status.textContent = 'Audio unavailable — transcript is ready';
    };
    window.speechSynthesis.speak(fallbackUtterance);
  }

  function resetPlayback() {
    audio.pause();
    try { audio.currentTime = 0; } catch (_) {}
    stopFallback();
    play.textContent = 'Play brief';
    play.setAttribute('aria-pressed', 'false');
    if (progress) progress.style.width = '0%';
  }

  play?.addEventListener('click', () => {
    // Refresh quietly without blocking the direct user gesture required by iOS audio playback.
    refreshRecap();
    if (neuralReady) {
      stopFallback();
      if (!audio.paused) {
        audio.pause();
        play.textContent = 'Resume';
        play.setAttribute('aria-pressed', 'false');
        status.textContent = 'Paused';
        return;
      }
      audio.play().catch(() => {
        neuralReady = false;
        status.textContent = 'Neural audio unavailable — tap Play for fallback narration';
        if (voiceLabel) voiceLabel.textContent = 'Browser fallback';
      });
      return;
    }

    if (fallbackSpeaking && !fallbackPaused) {
      window.speechSynthesis.pause();
      fallbackPaused = true;
      play.textContent = 'Resume';
      status.textContent = 'Paused';
      return;
    }
    if (fallbackSpeaking && fallbackPaused) {
      window.speechSynthesis.resume();
      fallbackPaused = false;
      play.textContent = 'Pause';
      status.textContent = 'Playing browser fallback voice';
      return;
    }
    startFallback();
  });

  audio.addEventListener('play', () => {
    play.textContent = 'Pause';
    play.setAttribute('aria-pressed', 'true');
    status.textContent = 'Playing neural Bulletin Brief';
  });
  audio.addEventListener('pause', () => {
    if (!audio.ended && audio.currentTime > 0) {
      play.textContent = 'Resume';
      play.setAttribute('aria-pressed', 'false');
    }
  });
  audio.addEventListener('ended', () => {
    play.textContent = 'Replay brief';
    play.setAttribute('aria-pressed', 'false');
    status.textContent = 'Brief complete';
    if (progress) progress.style.width = '100%';
  });
  audio.addEventListener('timeupdate', () => {
    if (!progress || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
    progress.style.width = `${Math.min(100, Math.round(audio.currentTime / audio.duration * 100))}%`;
  });
  audio.addEventListener('loadedmetadata', () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) duration.textContent = `About ${timeLabel(audio.duration)}`;
  });
  audio.addEventListener('error', () => {
    neuralReady = false;
    if (voiceLabel) voiceLabel.textContent = 'Browser fallback';
    status.textContent = 'Neural audio unavailable — fallback narration is ready';
  });

  transcriptToggle?.addEventListener('click', () => {
    const isHidden = transcript.hidden;
    transcript.hidden = !isHidden;
    transcriptToggle.textContent = isHidden ? 'Hide transcript' : 'Transcript';
    transcriptToggle.setAttribute('aria-expanded', String(isHidden));
  });

  async function refreshRecap() {
    try {
      const response = await fetch('/api/bulletin', {headers:{Accept:'application/json'}, cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      if (!data?.generated_at || data.generated_at === snapshotGeneratedAt) return;

      const brief = data.bulletin_brief || {};
      const nextText = clean(brief.transcript) || fallbackRecap(data);
      if (!nextText) return;

      const changed = Boolean(snapshotGeneratedAt && data.generated_at !== snapshotGeneratedAt);
      if (changed) resetPlayback();
      snapshotGeneratedAt = data.generated_at;
      recapText = nextText;
      transcript.textContent = recapText;

      const seconds = Number(brief.estimated_seconds || (words(recapText).length / 155 * 60));
      duration.textContent = `About ${timeLabel(seconds)} · ${brief.word_count || words(recapText).length} words`;
      updated.textContent = `Updated ${dateTimeLabel(brief.generated_at || data.generated_at)}`;

      neuralReady = Boolean(brief.audio_ready && brief.audio_url);
      if (neuralReady) {
        audio.src = `${brief.audio_url}?edition=${encodeURIComponent(data.generated_at)}`;
        audio.load();
        status.textContent = 'Ready to play · neural podcast voice';
        if (voiceLabel) voiceLabel.textContent = `${brief.voice_label || 'Neural voice'} · AI-narrated`;
      } else {
        audio.removeAttribute('src');
        audio.load();
        status.textContent = 'Ready to play · browser fallback voice';
        if (voiceLabel) voiceLabel.textContent = 'Browser fallback';
      }
      play.disabled = false;

      if (!neuralReady && !('speechSynthesis' in window)) {
        play.disabled = true;
        status.textContent = 'Audio narration unavailable — transcript is ready';
      }
    } catch (_) {
      if (!recapText) status.textContent = 'Brief temporarily unavailable';
    }
  }

  if ('speechSynthesis' in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener?.('voiceschanged', () => window.speechSynthesis.getVoices());
  }
  window.addEventListener('pagehide', () => {
    audio.pause();
    stopFallback();
  });
  refreshRecap();
  window.setInterval(refreshRecap, 5 * 60 * 1000);
})();