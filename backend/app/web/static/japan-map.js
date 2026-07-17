(function () {
  var NS = "http://www.w3.org/2000/svg";

  function padCode(code) {
    return String(code || "").replace(/\D/g, "").padStart(2, "0");
  }

  function formatManYen(value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    var man = Math.round(Number(value) / 10000);
    if (man >= 10000) return (man / 10000).toFixed(1).replace(/\.0$/, "") + "億円";
    return man.toLocaleString("ja-JP") + "万円";
  }

  function formatCount(value) {
    if (value == null) return "—";
    return Number(value).toLocaleString("ja-JP") + "件";
  }

  function parsePrefData(dataEl) {
    var raw = (dataEl && dataEl.textContent) || "[]";
    try {
      return JSON.parse(raw);
    } catch (_err) {
      try {
        var decoded = raw
          .replace(/&quot;/g, '"')
          .replace(/&#34;/g, '"')
          .replace(/&#x22;/gi, '"')
          .replace(/&amp;/g, "&");
        return JSON.parse(decoded);
      } catch (_err2) {
        return [];
      }
    }
  }

  function svgEl(name, attrs) {
    var el = document.createElementNS(NS, name);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        el.setAttribute(key, attrs[key]);
      });
    }
    return el;
  }

  async function initJapanMap(container) {
    if (!container) return;

    var prefs = parsePrefData(document.getElementById("prefecture-map-data"));
    var byCode = {};
    prefs.forEach(function (p) {
      byCode[padCode(p.code)] = p;
    });

    var res = await fetch("/static/japan-map.svg", { cache: "force-cache" });
    if (!res.ok) return;
    container.innerHTML = await res.text();
    container.removeAttribute("aria-busy");

    var svg = container.querySelector("svg");
    if (!svg) return;
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "日本地図から都道府県を選ぶ");
    svg.classList.add("japan-map-svg");
    svg.style.pointerEvents = "auto";

    var tip = document.createElement("div");
    tip.className = "japan-map-tooltip hidden";
    tip.setAttribute("role", "tooltip");
    container.appendChild(tip);

    var activeRegion = null;

    var regions = container.querySelectorAll(".prefecture[data-code]");
    regions.forEach(function (region) {
      var code = padCode(region.getAttribute("data-code"));
      var pref = byCode[code];
      if (!pref) return;

      var href = "/price/" + pref.slug;
      region.classList.add("japan-map-pref");
      region.style.cursor = "pointer";
      region.style.pointerEvents = "auto";
      region.querySelectorAll("polygon, path, circle").forEach(function (shape) {
        shape.style.pointerEvents = "auto";
        shape.style.cursor = "pointer";
      });
      region.setAttribute(
        "aria-label",
        pref.name_ja + "の不動産取引価格・相場を見る"
      );
      region.dataset.href = href;

      var parent = region.parentNode;
      if (parent && parent.namespaceURI === NS) {
        var link = svgEl("a", {
          href: href,
          "aria-label": pref.name_ja + "の不動産取引価格・相場を見る",
        });
        link.style.cursor = "pointer";
        parent.insertBefore(link, region);
        link.appendChild(region);
      }
    });

    function prefFromTarget(target) {
      var region =
        target && target.closest
          ? target.closest(".prefecture.japan-map-pref")
          : null;
      if (!region) return null;
      var code = padCode(region.getAttribute("data-code"));
      return { region: region, pref: byCode[code] };
    }

    function showTip(region, pref, event) {
      tip.innerHTML =
        "<strong>" +
        pref.name_ja +
        "</strong>" +
        "<span>" +
        formatCount(pref.total_transactions) +
        "</span>" +
        (pref.avg_price
          ? "<span>平均 " + formatManYen(pref.avg_price) + "</span>"
          : "");
      tip.classList.remove("hidden");
      var rect = container.getBoundingClientRect();
      var x = (event.clientX || rect.left + rect.width / 2) - rect.left;
      var y = (event.clientY || rect.top + 40) - rect.top;
      tip.style.left = Math.min(Math.max(x + 12, 8), rect.width - 160) + "px";
      tip.style.top = Math.max(y - 48, 8) + "px";
      if (activeRegion && activeRegion !== region) {
        activeRegion.classList.remove("is-active");
      }
      region.classList.add("is-active");
      activeRegion = region;
    }

    function hideTip() {
      tip.classList.add("hidden");
      if (activeRegion) activeRegion.classList.remove("is-active");
      activeRegion = null;
    }

    function go(pref) {
      if (!pref || !pref.slug) return;
      window.location.assign("/price/" + pref.slug);
    }

    container.addEventListener("click", function (event) {
      var hit = prefFromTarget(event.target);
      if (!hit) return;
      var anchor = event.target.closest("a[href]");
      if (anchor && anchor.getAttribute("href")) return;
      event.preventDefault();
      go(hit.pref);
    });

    container.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var hit = prefFromTarget(event.target);
      if (!hit) return;
      event.preventDefault();
      go(hit.pref);
    });

    container.addEventListener("mousemove", function (event) {
      var hit = prefFromTarget(event.target);
      if (!hit) {
        hideTip();
        return;
      }
      showTip(hit.region, hit.pref, event);
    });

    container.addEventListener("mouseleave", hideTip);

    container.addEventListener("focusin", function (event) {
      var hit = prefFromTarget(event.target);
      if (!hit) return;
      var rect = hit.region.getBoundingClientRect();
      var crect = container.getBoundingClientRect();
      showTip(hit.region, hit.pref, {
        clientX: rect.left + rect.width / 2,
        clientY: rect.top,
      });
      tip.style.left =
        Math.min(Math.max(rect.left - crect.left + 12, 8), crect.width - 160) +
        "px";
      tip.style.top = Math.max(rect.top - crect.top - 48, 8) + "px";
    });

    container.addEventListener("focusout", function (event) {
      if (!container.contains(event.relatedTarget)) hideTip();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var el = document.getElementById("japan-map");
    if (el) initJapanMap(el);
  });
})();
