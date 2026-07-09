(function () {
  "use strict";

  const RECENT_KEY = "reinfolib_recent_views";
  const MAX_RECENT = 8;

  // --- Recent views (localStorage) ---
  window.saveRecentView = function (item) {
    if (!item || !item.url) return;
    try {
      let items = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      items = items.filter((i) => i.url !== item.url);
      items.unshift({ ...item, viewedAt: Date.now() });
      items = items.slice(0, MAX_RECENT);
      localStorage.setItem(RECENT_KEY, JSON.stringify(items));
    } catch {
      /* ignore */
    }
  };

  function renderRecentViews() {
    const section = document.getElementById("recent-views-section");
    const list = document.getElementById("recent-views-list");
    if (!section || !list) return;
    try {
      const items = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      if (!items.length) return;
      section.classList.remove("hidden");
      list.innerHTML = items
        .map(
          (item) => `
        <a href="${item.url}" class="rounded-xl border border-slate-200 bg-white px-4 py-3 hover:border-brand-400 hover:bg-brand-50/50 transition group">
          <span class="font-medium text-ink-900 group-hover:text-brand-700 text-sm">${item.name}</span>
        </a>`
        )
        .join("");
    } catch {
      /* ignore */
    }
  }

  renderRecentViews();

  // --- Mobile menu ---
  const menuBtn = document.getElementById("mobile-menu-btn");
  const mobileMenu = document.getElementById("mobile-menu");
  if (menuBtn && mobileMenu) {
    menuBtn.addEventListener("click", () => {
      const open = mobileMenu.classList.toggle("hidden");
      menuBtn.setAttribute("aria-expanded", String(!open));
    });
  }

  // --- Mobile bottom nav active state ---
  const path = location.pathname;
  document.querySelectorAll(".mobile-nav-item").forEach((el) => {
    const nav = el.dataset.nav;
    const active =
      (nav === "home" && path === "/") ||
      (nav === "search" && path.startsWith("/search")) ||
      (nav === "rankings" && path.startsWith("/rankings")) ||
      (nav === "news" && path.startsWith("/news")) ||
      (nav === "compare" && path.startsWith("/compare")) ||
      (nav === "price" && path.startsWith("/price"));
    if (active) el.classList.add("mobile-nav-active");
  });

  // --- Share button ---
  const shareBtn = document.getElementById("share-btn");
  if (shareBtn) {
    shareBtn.addEventListener("click", async () => {
      const url = shareBtn.dataset.shareUrl || location.href;
      const title = document.title;
      if (navigator.share) {
        try {
          await navigator.share({ title, url });
          return;
        } catch {
          /* fall through */
        }
      }
      try {
        await navigator.clipboard.writeText(url);
        const orig = shareBtn.innerHTML;
        shareBtn.innerHTML = '<span class="text-emerald-600">コピーしました</span>';
        setTimeout(() => { shareBtn.innerHTML = orig; }, 2000);
      } catch {
        prompt("URLをコピーしてください:", url);
      }
    });
  }

  // --- Search autocomplete (reusable) ---
  function setupAutocomplete(inputId, resultsId, wrapId, onSelect) {
    const searchInput = document.getElementById(inputId);
    const searchResults = document.getElementById(resultsId);
    if (!searchInput || !searchResults) return;

    let searchTimer = null;
    let activeIndex = -1;
    let currentItems = [];

    function getItems() {
      return searchResults.querySelectorAll(".search-result-item");
    }

    function setActive(index) {
      const items = getItems();
      activeIndex = index;
      items.forEach((el, i) => {
        el.classList.toggle("search-result-active", i === activeIndex);
        if (i === activeIndex) el.scrollIntoView({ block: "nearest" });
      });
    }

    function renderResults(items) {
      currentItems = items;
      activeIndex = -1;
      if (!items.length) {
        searchResults.innerHTML =
          '<div class="px-4 py-3 text-sm text-slate-500">該当する市区町村がありません</div>';
        searchResults.classList.remove("hidden");
        return;
      }
      searchResults.innerHTML = items
        .map(
          (item, i) => `
        <a href="#" class="search-result-item" role="option" data-index="${i}">
          <span class="font-medium text-ink-900">${item.name_ja}</span>
          <span class="text-xs text-slate-500">${item.prefecture_name}</span>
          <span class="text-xs text-brand-600 ml-auto">${item.total_transactions.toLocaleString()}件</span>
        </a>`
        )
        .join("");
      searchResults.classList.remove("hidden");

      searchResults.querySelectorAll(".search-result-item").forEach((el) => {
        el.addEventListener("click", (e) => {
          e.preventDefault();
          const idx = parseInt(el.dataset.index, 10);
          if (currentItems[idx]) {
            onSelect(currentItems[idx], searchInput, searchResults);
          }
        });
      });
    }

    function hideResults() {
      searchResults.classList.add("hidden");
      activeIndex = -1;
    }

    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      const q = searchInput.value.trim();
      if (q.length < 1) {
        hideResults();
        return;
      }
      searchTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=8`);
          const data = await res.json();
          renderResults(data);
        } catch {
          hideResults();
        }
      }, 250);
    });

    searchInput.addEventListener("keydown", (e) => {
      const items = getItems();
      if (e.key === "Escape") {
        hideResults();
        return;
      }
      if (!items.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive(activeIndex < items.length - 1 ? activeIndex + 1 : 0);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive(activeIndex > 0 ? activeIndex - 1 : items.length - 1);
      } else if (e.key === "Enter" && activeIndex >= 0) {
        e.preventDefault();
        if (currentItems[activeIndex]) {
          onSelect(currentItems[activeIndex], searchInput, searchResults);
        }
      }
    });

    if (wrapId) {
      document.addEventListener("click", (e) => {
        const wrap = document.getElementById(wrapId);
        if (wrap && !wrap.contains(e.target)) hideResults();
      });
    }
  }

  setupAutocomplete("global-search", "search-results", "global-search-wrap", (item) => {
    location.href = `/price/${item.prefecture_slug}/${item.slug}`;
  });

  setupAutocomplete("hero-search", "hero-search-results", "hero-search-wrap", (item, input, results) => {
    location.href = `/price/${item.prefecture_slug}/${item.slug}`;
  });

  // --- Compare page pickers ---
  function setupComparePicker(side) {
    const inputId = `compare-search-${side}`;
    const resultsId = `compare-results-${side}`;
    const hiddenId = `compare-${side}`;

    setupAutocomplete(inputId, resultsId, null, (item, input, results) => {
      input.value = `${item.prefecture_name}${item.name_ja}`;
      const hidden = document.getElementById(hiddenId);
      if (hidden) hidden.value = `${item.prefecture_slug}/${item.slug}`;
      results.classList.add("hidden");

      const a = document.getElementById("compare-a")?.value;
      const b = document.getElementById("compare-b")?.value;
      if (a && b) {
        location.href = `/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`;
      }
    });
  }

  if (document.getElementById("compare-search-a")) {
    setupComparePicker("a");
    setupComparePicker("b");
  }

  // --- Municipality table filter ---
  const muniFilter = document.getElementById("muni-filter");
  const muniTable = document.getElementById("muni-table");
  if (muniFilter && muniTable) {
    muniFilter.addEventListener("input", () => {
      const q = muniFilter.value.trim();
      muniTable.querySelectorAll("tbody tr").forEach((row) => {
        const name = row.dataset.name || "";
        row.classList.toggle("hidden", q && !name.includes(q));
      });
    });
  }

  // --- Sortable table ---
  document.querySelectorAll(".sortable-table").forEach((table) => {
    const tbody = table.querySelector("tbody");
    if (!tbody) return;

    let currentSort = { key: "count", dir: "desc" };

    table.querySelectorAll("th[data-sort]").forEach((th) => {
      if (th.dataset.default) {
        currentSort = { key: th.dataset.sort, dir: th.dataset.default };
      }

      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        const dir =
          currentSort.key === key && currentSort.dir === "desc" ? "asc" : "desc";
        currentSort = { key, dir };

        table.querySelectorAll(".sort-indicator").forEach((s) => {
          s.textContent = "↕";
          s.classList.remove("text-brand-500");
          s.classList.add("text-slate-300");
        });
        const indicator = th.querySelector(".sort-indicator");
        if (indicator) {
          indicator.textContent = dir === "asc" ? "↑" : "↓";
          indicator.classList.add("text-brand-500");
          indicator.classList.remove("text-slate-300");
        }

        const rows = Array.from(tbody.querySelectorAll("tr"));
        const type = th.dataset.type || "text";
        rows.sort((a, b) => {
          let av = a.dataset[key] || "";
          let bv = b.dataset[key] || "";
          if (type === "number") {
            av = parseFloat(av) || 0;
            bv = parseFloat(bv) || 0;
          }
          if (av < bv) return dir === "asc" ? -1 : 1;
          if (av > bv) return dir === "asc" ? 1 : -1;
          return 0;
        });
        rows.forEach((row) => tbody.appendChild(row));
      });
    });
  });

  // --- Transaction API pagination ---
  const txPanel = document.getElementById("tx-panel");
  if (txPanel) {
    const pref = txPanel.dataset.pref;
    const muni = txPanel.dataset.muni;
    const tbody = document.getElementById("tx-tbody");
    const typeSel = document.getElementById("tx-filter-type");
    const classSel = document.getElementById("tx-price-class");
    const prevBtn = document.getElementById("tx-prev");
    const nextBtn = document.getElementById("tx-next");
    const pageInfo = document.getElementById("tx-page-info");
    const countEl = document.getElementById("tx-filter-count");
    let page = 1;

    function fmtMan(v) {
      if (v == null) return "—";
      const man = v / 10000;
      return man >= 1 ? `${Math.round(man).toLocaleString()}万円` : `${v.toLocaleString()}円`;
    }
    function fmtSqm(v) {
      return v != null ? `${Math.round(v).toLocaleString()}円/㎡` : "—";
    }

    async function loadTx(resetPage) {
      if (resetPage) page = 1;
      const params = new URLSearchParams({
        page: String(page),
        page_size: "20",
        price_classification: classSel?.value || "01",
      });
      if (typeSel?.value) params.set("property_type", typeSel.value);
      const res = await fetch(`/api/municipalities/${pref}/${muni}/transactions?${params}`);
      const data = await res.json();
      if (!tbody) return;
      tbody.innerHTML = data.items
        .map(
          (tx) => `
        <tr class="hover:bg-slate-50">
          <td class="px-4 py-3 whitespace-nowrap text-slate-600">${tx.period_label || tx.trade_year + " Q" + tx.trade_quarter}</td>
          <td class="px-4 py-3">${tx.property_type || "—"}</td>
          <td class="px-4 py-3">${tx.district_name || "—"}</td>
          <td class="px-4 py-3 text-right tabular-nums font-medium">${fmtMan(tx.trade_price)}</td>
          <td class="px-4 py-3 text-right tabular-nums">${fmtSqm(tx.unit_price)}</td>
          <td class="px-4 py-3 text-right tabular-nums">${tx.area ? tx.area.toFixed(1) + "㎡" : "—"}</td>
          <td class="px-4 py-3 hidden lg:table-cell">${tx.building_year || "—"}</td>
          <td class="px-4 py-3 hidden lg:table-cell">${tx.city_planning || "—"}</td>
        </tr>`
        )
        .join("");
      if (countEl) countEl.textContent = `全${data.total.toLocaleString()}件`;
      if (pageInfo) pageInfo.textContent = `${data.page}ページ目`;
      if (prevBtn) prevBtn.disabled = data.page <= 1;
      if (nextBtn) nextBtn.disabled = !data.has_more;
    }

    typeSel?.addEventListener("change", () => loadTx(true));
    classSel?.addEventListener("change", () => loadTx(true));
    prevBtn?.addEventListener("click", () => { if (page > 1) { page--; loadTx(); } });
    nextBtn?.addEventListener("click", () => { page++; loadTx(); });
  }

  // --- Tab navigation ---
  const tabBtns = document.querySelectorAll("[data-tab]");
  const tabPanels = document.querySelectorAll("[data-tab-panel]");
  if (tabBtns.length) {
    tabBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tab;
        tabBtns.forEach((b) => {
          b.classList.toggle("tab-active", b.dataset.tab === target);
          b.classList.toggle("tab-inactive", b.dataset.tab !== target);
        });
        tabPanels.forEach((panel) => {
          panel.classList.toggle("hidden", panel.dataset.tabPanel !== target);
        });
        const activePanel = document.querySelector(`[data-tab-panel="${target}"]`);
        if (activePanel) {
          requestAnimationFrame(() => {
            if (typeof resizeChartsIn === "function") resizeChartsIn(activePanel);
          });
        }
        history.replaceState(null, "", `#${target}`);
      });
    });

    const hash = location.hash.replace("#", "");
    if (hash) {
      const btn = document.querySelector(`[data-tab="${hash}"]`);
      if (btn) btn.click();
    }
  }

  // --- Report form municipality search ---
  const reportSearch = document.getElementById("report-search");
  const reportResults = document.getElementById("report-results");
  const reportForm = document.getElementById("report-form");
  let reportTimer = null;

  if (reportSearch && reportResults) {
    reportSearch.addEventListener("input", () => {
      clearTimeout(reportTimer);
      const q = reportSearch.value.trim();
      if (q.length < 1) {
        reportResults.innerHTML = "";
        return;
      }
      reportTimer = setTimeout(async () => {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`);
        const data = await res.json();
        reportResults.innerHTML = data
          .map(
            (item) => `
          <button type="button" class="report-pick w-full text-left px-4 py-3 hover:bg-brand-50 border-b border-slate-100 last:border-0"
                  data-pref="${item.prefecture_slug}" data-muni="${item.slug}">
            <span class="font-medium">${item.name_ja}</span>
            <span class="text-sm text-slate-500 ml-2">${item.prefecture_name}</span>
          </button>`
          )
          .join("");
      }, 250);
    });

    reportResults.addEventListener("click", (e) => {
      const btn = e.target.closest(".report-pick");
      if (!btn) return;
      const pref = btn.dataset.pref;
      const muni = btn.dataset.muni;
      const label = btn.querySelector(".font-medium").textContent;
      reportSearch.value = label;
      reportResults.innerHTML = "";
      if (reportForm) {
        reportForm.querySelector('[name="prefecture_slug"]').value = pref;
        reportForm.querySelector('[name="municipality_slug"]').value = muni;
        document.getElementById("report-selected")?.classList.remove("hidden");
        const sel = document.getElementById("report-selected-label");
        if (sel) sel.textContent = `${btn.querySelector(".font-medium").textContent}（${btn.querySelector(".text-sm")?.textContent?.trim() || ""}）`;
        const submit = document.getElementById("report-submit");
        if (submit) submit.disabled = false;
      }
    });
  }
})();
