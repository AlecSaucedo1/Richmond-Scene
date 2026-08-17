(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const picker = $("#edition-picker");
  if (picker) {
    picker.addEventListener("change", () => {
      if (picker.value) window.location.href = picker.value;
    });
  }

  const isInteractiveTarget = (target) => Boolean(target.closest("a, button, input, select, summary, details"));
  $$("[data-href]").forEach((card) => {
    card.setAttribute("tabindex", "0");
    card.setAttribute("role", "link");
    const go = () => {
      const href = card.dataset.href;
      if (href) window.location.href = href;
    };
    card.addEventListener("click", (event) => {
      if (!isInteractiveTarget(event.target)) go();
    });
    card.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && !isInteractiveTarget(event.target)) {
        event.preventDefault();
        go();
      }
    });
  });

  const editionGrid = $("[data-edition-grid]");
  if (editionGrid) {
    const cards = $$("[data-edition-card]", editionGrid);
    const buttons = $$("[data-edition-filter]");
    const search = $("[data-neighborhood-search]");
    const count = $("[data-edition-count]");
    let activeFilter = "all";

    const apply = () => {
      const query = (search?.value || "").trim().toLowerCase();
      let visible = 0;
      cards.forEach((card) => {
        const sourceMatch = activeFilter === "all" || card.dataset.source === activeFilter;
        const searchMatch = !query || (card.dataset.search || "").includes(query);
        const show = sourceMatch && searchMatch;
        card.hidden = !show;
        if (show) visible += 1;
      });
      if (count) count.textContent = `${visible} neighborhood${visible === 1 ? "" : "s"}`;
    };

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        activeFilter = button.dataset.editionFilter || "all";
        buttons.forEach((item) => item.classList.toggle("is-active", item === button));
        apply();
      });
    });
    search?.addEventListener("input", apply);
    apply();
  }

  const storyGrid = $("[data-story-grid]");
  if (storyGrid) {
    const stories = $$("[data-story-card]", storyGrid);
    const buttons = $$("[data-story-filter]");
    const count = $("[data-story-count]");
    let active = "all";
    const apply = () => {
      let visible = 0;
      stories.forEach((story) => {
        const show = active === "all" || story.dataset.source === active;
        story.hidden = !show;
        if (show) visible += 1;
      });
      if (count) count.textContent = `${visible} stor${visible === 1 ? "y" : "ies"}`;
    };
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        active = button.dataset.storyFilter || "all";
        buttons.forEach((item) => item.classList.toggle("is-active", item === button));
        apply();
      });
    });
    apply();
  }

  const copyText = async (text) => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  };

  $$(".js-share").forEach((button) => {
    button.addEventListener("click", async () => {
      const url = new URL(button.dataset.shareUrl || window.location.href, window.location.origin).href;
      const title = button.dataset.shareTitle || document.title;
      try {
        if (navigator.share) {
          await navigator.share({ title, url });
          return;
        }
        await copyText(url);
        const original = button.textContent;
        button.textContent = "Link copied";
        button.classList.add("is-success");
        window.setTimeout(() => {
          button.textContent = original;
          button.classList.remove("is-success");
        }, 1600);
      } catch (error) {
        if (error?.name !== "AbortError") console.warn("Unable to share link", error);
      }
    });
  });

  $$(".pulse-bar").forEach((bar) => {
    bar.addEventListener("click", () => {
      const card = bar.closest(".pulse-card");
      const readout = $(".pulse-readout", card);
      $$(".pulse-bar", card).forEach((item) => item.classList.toggle("is-selected", item === bar));
      if (readout) readout.textContent = `Week ${bar.dataset.week}: ${bar.dataset.value} record${bar.dataset.value === "1" ? "" : "s"}`;
    });
  });

  $$("[data-expand-group]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = document.getElementById(button.dataset.expandGroup);
      if (!target) return;
      const expanded = button.getAttribute("aria-expanded") === "true";
      target.hidden = expanded;
      button.setAttribute("aria-expanded", String(!expanded));
      button.textContent = expanded ? button.dataset.moreLabel || "Show more" : button.dataset.lessLabel || "Show fewer";
    });
  });
})();
