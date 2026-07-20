(function () {
  "use strict";

  window.initLandPriceMap = function (prefSlug, muniSlug, year) {
    const mapEl = document.getElementById("land-map");
    if (!mapEl || typeof L === "undefined") return;

    const map = L.map("land-map", { scrollWheelZoom: false }).setView([35.68, 139.76], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap",
      maxZoom: 18,
    }).addTo(map);

    const yearParam = year ? `&year=${year}` : "";
    fetch(`/api/municipalities/${prefSlug}/${muniSlug}/land-prices?limit=300${yearParam}`)
      .then((r) => r.json())
      .then((points) => {
        if (!points.length) return;
        const bounds = [];
        points.forEach((p) => {
          if (!p.latitude || !p.longitude) return;
          const latlng = [p.latitude, p.longitude];
          bounds.push(latlng);
          const price = p.unit_price
            ? `${Math.round(p.unit_price).toLocaleString()}円/㎡`
            : "—";
          const yoy =
            p.year_on_year_change_rate != null
              ? `<br>前年比: ${p.year_on_year_change_rate >= 0 ? "+" : ""}${p.year_on_year_change_rate.toFixed(1)}%`
              : "";
          L.circleMarker(latlng, {
            radius: 6,
            color: "#0284c7",
            fillColor: "#0ea5e9",
            fillOpacity: 0.75,
            weight: 2,
          })
            .addTo(map)
            .bindPopup(
              `<strong>${p.location || "地価公示地点"}</strong><br>${price}${yoy}`
            );
        });
        if (bounds.length) map.fitBounds(bounds, { padding: [24, 24] });
        renderLandTable(points);
      })
      .catch(() => {});

    function renderLandTable(points) {
      const tbody = document.getElementById("land-points-body");
      if (!tbody) return;
      tbody.innerHTML = points
        .slice(0, 50)
        .map(
          (p) => `
        <tr>
          <td class="px-3 py-2">${p.location || "—"}</td>
          <td class="px-3 py-2 text-right tabular-nums">${p.unit_price ? p.unit_price.toLocaleString() + "円" : "—"}</td>
          <td class="px-3 py-2 text-right tabular-nums hidden sm:table-cell">${p.year_on_year_change_rate != null ? (p.year_on_year_change_rate >= 0 ? "+" : "") + p.year_on_year_change_rate.toFixed(1) + "%" : "—"}</td>
          <td class="px-3 py-2 hidden md:table-cell">${p.nearest_station || "—"}</td>
        </tr>`
        )
        .join("");
    }
  };
})();
