(() => {
  const copyText = async (text) => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
  };

  document.querySelectorAll('[data-page-share]').forEach((button) => {
    button.addEventListener('click', async () => {
      const title = button.dataset.shareTitle || document.title;
      const url = `${window.location.origin}${window.location.pathname}`;
      try {
        if (navigator.share) {
          await navigator.share({title, text:'Read this edition of The San Francisco Bulletin.', url});
          return;
        }
        await copyText(url);
        const original = button.textContent;
        button.textContent = 'Link copied';
        button.classList.add('is-success');
        window.setTimeout(() => {
          button.textContent = original;
          button.classList.remove('is-success');
        }, 1800);
      } catch (error) {
        if (error?.name !== 'AbortError') console.warn('Unable to share Bulletin page', error);
      }
    });
  });
})();
