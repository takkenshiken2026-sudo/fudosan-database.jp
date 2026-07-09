(function () {
  const FONT = '"Noto Sans JP", sans-serif';
  const BRAND = "#0284c7";
  const BRAND_LIGHT = "#38bdf8";
  const SLATE = "#64748b";
  const GRID = "#e2e8f0";

  function ensureChartDefaults() {
    if (typeof Chart === "undefined") return false;
    Chart.defaults.font.family = FONT;
    Chart.defaults.color = SLATE;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    return true;
  }

  function quarterLabel(year, quarter) {
    return `${year} Q${quarter}`;
  }

  function toManYen(value) {
    if (value == null) return null;
    return Math.round(value / 10000);
  }

  function baseOptions(yTitle) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top" },
        tooltip: {
          titleFont: { family: FONT },
          bodyFont: { family: FONT },
        },
      },
      scales: {
        x: {
          grid: { color: GRID },
          ticks: { maxRotation: 45, minRotation: 0, font: { size: 11 } },
        },
        y: {
          title: yTitle ? { display: true, text: yTitle, font: { size: 12 } } : undefined,
          grid: { color: GRID },
          ticks: { font: { size: 11 } },
        },
      },
    };
  }

  function destroyChart(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const existing = Chart.getChart(el);
    if (existing) existing.destroy();
  }

  function createChart(id, config) {
    if (!ensureChartDefaults()) return;
    const el = document.getElementById(id);
    if (!el) return;
    destroyChart(id);
    new Chart(el, config);
  }

  /** 非表示タブ内のグラフは幅0で描画されるため、タブ表示時に resize */
  window.resizeChartsIn = function (container) {
    if (!container || typeof Chart === "undefined") return;
    container.querySelectorAll("canvas").forEach((canvas) => {
      const chart = Chart.getChart(canvas);
      if (chart) chart.resize();
    });
  };

  window.initMunicipalityCharts = function (data) {
    const quarterly = data.quarterly_chart || [];
    const yearly = data.yearly_stats || [];
    const property = data.property_stats || [];
    const landYearly = data.land_price_yearly || [];

    if (quarterly.length) {
      const qLabels = quarterly.map((r) => quarterLabel(r.trade_year, r.trade_quarter));

      createChart("chart-quarterly-count", {
        type: "bar",
        data: {
          labels: qLabels,
          datasets: [
            {
              label: "取引件数",
              data: quarterly.map((r) => r.transaction_count),
              backgroundColor: "rgba(2, 132, 199, 0.65)",
              borderColor: BRAND,
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          ...baseOptions("件"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "四半期別 取引件数", font: { size: 14, weight: "600" } },
          },
        },
      });

      createChart("chart-quarterly-price", {
        type: "line",
        data: {
          labels: qLabels,
          datasets: [
            {
              label: "平均取引価格",
              data: quarterly.map((r) => toManYen(r.trade_price_avg)),
              borderColor: BRAND,
              backgroundColor: "rgba(2, 132, 199, 0.1)",
              fill: true,
              tension: 0.3,
              pointRadius: 2,
              yAxisID: "y",
            },
            {
              label: "㎡単価",
              data: quarterly.map((r) => r.unit_price_avg),
              borderColor: "#f59e0b",
              backgroundColor: "rgba(245, 158, 11, 0.08)",
              fill: false,
              tension: 0.3,
              pointRadius: 2,
              yAxisID: "y1",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: { position: "top" },
            title: { display: true, text: "四半期別 価格推移", font: { size: 14, weight: "600" } },
            tooltip: {
              callbacks: {
                label(ctx) {
                  if (ctx.datasetIndex === 0) {
                    const v = ctx.parsed.y;
                    return v != null ? `平均: ${v.toLocaleString()}万円` : "平均: —";
                  }
                  const v = ctx.parsed.y;
                  return v != null ? `㎡単価: ${Math.round(v).toLocaleString()}円` : "㎡単価: —";
                },
              },
            },
          },
          scales: {
            x: { grid: { color: GRID }, ticks: { maxRotation: 45, font: { size: 11 } } },
            y: {
              position: "left",
              title: { display: true, text: "万円" },
              grid: { color: GRID },
            },
            y1: {
              position: "right",
              title: { display: true, text: "円/㎡" },
              grid: { drawOnChartArea: false },
            },
          },
        },
      });
    }

    if (yearly.length) {
      const yLabels = yearly.map((r) => `${r.trade_year}年`);

      createChart("chart-yearly-count", {
        type: "bar",
        data: {
          labels: yLabels,
          datasets: [
            {
              label: "年間取引件数",
              data: yearly.map((r) => r.transaction_count),
              backgroundColor: "rgba(14, 165, 233, 0.7)",
              borderColor: BRAND_LIGHT,
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          ...baseOptions("件"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "年次 取引件数推移", font: { size: 14, weight: "600" } },
          },
        },
      });

      createChart("chart-yearly-price", {
        type: "line",
        data: {
          labels: yLabels,
          datasets: [
            {
              label: "年平均取引価格",
              data: yearly.map((r) => toManYen(r.trade_price_avg)),
              borderColor: BRAND,
              backgroundColor: "rgba(2, 132, 199, 0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 3,
            },
            {
              label: "年間㎡単価",
              data: yearly.map((r) => r.unit_price_avg),
              borderColor: "#10b981",
              backgroundColor: "rgba(16, 185, 129, 0.08)",
              fill: false,
              tension: 0.25,
              pointRadius: 3,
              yAxisID: "y1",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "top" },
            title: { display: true, text: "年次 価格推移", font: { size: 14, weight: "600" } },
            tooltip: {
              callbacks: {
                label(ctx) {
                  if (ctx.datasetIndex === 0) {
                    const v = ctx.parsed.y;
                    return v != null ? `平均: ${v.toLocaleString()}万円` : "平均: —";
                  }
                  const v = ctx.parsed.y;
                  return v != null ? `㎡単価: ${Math.round(v).toLocaleString()}円` : "㎡単価: —";
                },
              },
            },
          },
          scales: {
            x: { grid: { color: GRID } },
            y: { position: "left", title: { display: true, text: "万円" }, grid: { color: GRID } },
            y1: {
              position: "right",
              title: { display: true, text: "円/㎡" },
              grid: { drawOnChartArea: false },
            },
          },
        },
      });
    }

    if (property.length) {
      createChart("chart-property-mix", {
        type: "doughnut",
        data: {
          labels: property.map((r) => r.property_type || "種別不明"),
          datasets: [
            {
              data: property.map((r) => r.transaction_count),
              backgroundColor: [
                "#0284c7",
                "#0ea5e9",
                "#38bdf8",
                "#f59e0b",
                "#10b981",
                "#8b5cf6",
                "#ec4899",
                "#64748b",
              ],
              borderWidth: 2,
              borderColor: "#fff",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "right" },
            title: {
              display: true,
              text: "物件種別構成（最新四半期）",
              font: { size: 14, weight: "600" },
            },
          },
        },
      });

      createChart("chart-property-price", {
        type: "bar",
        data: {
          labels: property.map((r) => r.property_type || "種別不明"),
          datasets: [
            {
              label: "平均取引価格",
              data: property.map((r) => toManYen(r.trade_price_avg)),
              backgroundColor: "rgba(2, 132, 199, 0.75)",
              borderRadius: 6,
            },
          ],
        },
        options: {
          indexAxis: "y",
          ...baseOptions("万円"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "種別別 平均価格", font: { size: 14, weight: "600" } },
          },
        },
      });
    }

    if (landYearly.length) {
      const landLabels = landYearly.map((r) => `${r.survey_year}年`);
      const landPriceDataset = {
        label: "平均地価（円/㎡）",
        data: landYearly.map((r) => r.avg_unit_price),
        borderColor: "#10b981",
        backgroundColor: "rgba(16, 185, 129, 0.12)",
        fill: true,
        tension: 0.25,
        pointRadius: 3,
      };
      const landPriceOptions = {
        ...baseOptions("円/㎡"),
        plugins: {
          ...baseOptions().plugins,
          title: { display: true, text: "地価公示 年平均地価", font: { size: 14, weight: "600" } },
        },
      };

      createChart("chart-land-yearly", {
        type: "line",
        data: { labels: landLabels, datasets: [landPriceDataset] },
        options: landPriceOptions,
      });

      createChart("chart-muni-land-overview", {
        type: "line",
        data: { labels: landLabels, datasets: [landPriceDataset] },
        options: landPriceOptions,
      });
    }
  };

  window.initPrefectureCharts = function (data) {
    const yearly = data.yearly_stats || [];
    const top = data.top_municipalities || [];

    if (yearly.length) {
      createChart("chart-pref-yearly-count", {
        type: "line",
        data: {
          labels: yearly.map((r) => `${r.trade_year}年`),
          datasets: [
            {
              label: "取引件数",
              data: yearly.map((r) => r.transaction_count),
              borderColor: BRAND,
              backgroundColor: "rgba(2, 132, 199, 0.15)",
              fill: true,
              tension: 0.25,
              pointRadius: 3,
            },
          ],
        },
        options: {
          ...baseOptions("件"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "県全体の年次取引件数", font: { size: 14, weight: "600" } },
          },
        },
      });

      createChart("chart-pref-yearly-price", {
        type: "line",
        data: {
          labels: yearly.map((r) => `${r.trade_year}年`),
          datasets: [
            {
              label: "平均取引価格",
              data: yearly.map((r) => toManYen(r.trade_price_avg)),
              borderColor: "#f59e0b",
              backgroundColor: "rgba(245, 158, 11, 0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 3,
            },
          ],
        },
        options: {
          ...baseOptions("万円"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "県全体の年平均取引価格", font: { size: 14, weight: "600" } },
          },
        },
      });
    }

    if (top.length) {
      createChart("chart-pref-top-cities", {
        type: "bar",
        data: {
          labels: top.map((m) => m.name_ja),
          datasets: [
            {
              label: "累計取引件数",
              data: top.map((m) => m.total_transactions),
              backgroundColor: "rgba(2, 132, 199, 0.7)",
              borderRadius: 6,
            },
          ],
        },
        options: {
          indexAxis: "y",
          ...baseOptions("件"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "取引件数トップ市区町村", font: { size: 14, weight: "600" } },
          },
        },
      });
    }

    const landYearly = data.land_price_yearly || [];
    if (landYearly.length) {
      const landLabels = landYearly.map((r) => `${r.survey_year}年`);

      createChart("chart-pref-land-price", {
        type: "line",
        data: {
          labels: landLabels,
          datasets: [
            {
              label: "平均地価（円/㎡）",
              data: landYearly.map((r) => r.avg_unit_price),
              borderColor: "#10b981",
              backgroundColor: "rgba(16, 185, 129, 0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 3,
            },
          ],
        },
        options: {
          ...baseOptions("円/㎡"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "県全体の年平均地価", font: { size: 14, weight: "600" } },
          },
        },
      });

      createChart("chart-pref-land-points", {
        type: "bar",
        data: {
          labels: landLabels,
          datasets: [
            {
              label: "公示地点数",
              data: landYearly.map((r) => r.point_count),
              backgroundColor: "rgba(16, 185, 129, 0.55)",
              borderColor: "#10b981",
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          ...baseOptions("地点"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "県全体の公示地点数", font: { size: 14, weight: "600" } },
          },
        },
      });
    }

    const topStations = data.top_stations || [];
    if (topStations.length) {
      createChart("chart-pref-top-stations", {
        type: "bar",
        data: {
          labels: topStations.map((s) => s.station_name),
          datasets: [
            {
              label: "乗降客数（人/日）",
              data: topStations.map((s) => s.latest_passengers),
              backgroundColor: "rgba(16, 185, 129, 0.65)",
              borderRadius: 6,
            },
          ],
        },
        options: {
          indexAxis: "y",
          ...baseOptions("人/日"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "乗降客数トップ駅", font: { size: 14, weight: "600" } },
          },
        },
      });
    }
  };

  window.initStationChart = function (station) {
    const yearly = station.yearly_passengers || [];
    if (!yearly.length) return;
    createChart("chart-station-passengers", {
      type: "line",
      data: {
        labels: yearly.map((r) => `${r.year}年`),
        datasets: [
          {
            label: "乗降客数（人/日）",
            data: yearly.map((r) => r.passengers),
            borderColor: "#10b981",
            backgroundColor: "rgba(16, 185, 129, 0.12)",
            fill: true,
            tension: 0.25,
            pointRadius: 3,
          },
        ],
      },
      options: {
        ...baseOptions("人/日"),
        plugins: {
          ...baseOptions().plugins,
          title: {
            display: true,
            text: `${station.station_name}駅 乗降客数の推移`,
            font: { size: 14, weight: "600" },
          },
        },
      },
    });
  };

  window.initHomeCharts = function (data) {
    const yearly = data.yearly_stats || [];
    const landYearly = data.land_price_yearly || [];

    if (yearly.length) {
      const labels = yearly.map((r) => `${r.trade_year}年`);

      createChart("chart-home-volume", {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              label: "全国取引件数",
              data: yearly.map((r) => r.transaction_count),
              backgroundColor: "rgba(2, 132, 199, 0.7)",
              borderColor: BRAND,
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          ...baseOptions("件"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "全国の年間取引件数", font: { size: 14, weight: "600" } },
          },
        },
      });

      createChart("chart-home-price", {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              label: "全国平均取引価格",
              data: yearly.map((r) => toManYen(r.trade_price_avg)),
              borderColor: "#f59e0b",
              backgroundColor: "rgba(245, 158, 11, 0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 3,
            },
          ],
        },
        options: {
          ...baseOptions("万円"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "全国の年平均取引価格", font: { size: 14, weight: "600" } },
            tooltip: {
              callbacks: {
                label(ctx) {
                  const v = ctx.parsed.y;
                  return v != null ? `平均: ${v.toLocaleString()}万円` : "平均: —";
                },
              },
            },
          },
        },
      });
    }

    if (landYearly.length) {
      const landLabels = landYearly.map((r) => `${r.survey_year}年`);

      createChart("chart-home-land-price", {
        type: "line",
        data: {
          labels: landLabels,
          datasets: [
            {
              label: "全国平均地価（円/㎡）",
              data: landYearly.map((r) => r.avg_unit_price),
              borderColor: "#10b981",
              backgroundColor: "rgba(16, 185, 129, 0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 3,
            },
          ],
        },
        options: {
          ...baseOptions("円/㎡"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "全国の年平均地価（地価公示）", font: { size: 14, weight: "600" } },
            tooltip: {
              callbacks: {
                label(ctx) {
                  const v = ctx.parsed.y;
                  return v != null ? `平均: ${Math.round(v).toLocaleString()}円/㎡` : "平均: —";
                },
              },
            },
          },
        },
      });

      createChart("chart-home-land-points", {
        type: "bar",
        data: {
          labels: landLabels,
          datasets: [
            {
              label: "公示地点数",
              data: landYearly.map((r) => r.point_count),
              backgroundColor: "rgba(16, 185, 129, 0.55)",
              borderColor: "#10b981",
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          ...baseOptions("地点"),
          plugins: {
            ...baseOptions().plugins,
            title: { display: true, text: "全国の地価公示地点数", font: { size: 14, weight: "600" } },
          },
        },
      });
    }
  };

  window.initCompareCharts = function (data) {
    const left = data.left || {};
    const right = data.right || {};
    const leftYearly = left.yearly_stats || [];
    const rightYearly = right.yearly_stats || [];

    if (leftYearly.length || rightYearly.length) {
      const years = [
        ...new Set([
          ...leftYearly.map((r) => r.trade_year),
          ...rightYearly.map((r) => r.trade_year),
        ]),
      ].sort();

      const leftMap = Object.fromEntries(leftYearly.map((r) => [r.trade_year, r]));
      const rightMap = Object.fromEntries(rightYearly.map((r) => [r.trade_year, r]));

      createChart("chart-compare-yearly", {
        type: "line",
        data: {
          labels: years.map((y) => `${y}年`),
          datasets: [
            {
              label: left.name_ja || "エリア A",
              data: years.map((y) => toManYen(leftMap[y]?.trade_price_avg)),
              borderColor: "#0284c7",
              backgroundColor: "rgba(2, 132, 199, 0.1)",
              fill: false,
              tension: 0.25,
              pointRadius: 3,
            },
            {
              label: right.name_ja || "エリア B",
              data: years.map((y) => toManYen(rightMap[y]?.trade_price_avg)),
              borderColor: "#f59e0b",
              backgroundColor: "rgba(245, 158, 11, 0.1)",
              fill: false,
              tension: 0.25,
              pointRadius: 3,
            },
          ],
        },
        options: {
          ...baseOptions("万円"),
          plugins: {
            ...baseOptions().plugins,
            title: {
              display: true,
              text: "年平均取引価格の比較",
              font: { size: 14, weight: "600" },
            },
            tooltip: {
              callbacks: {
                label(ctx) {
                  const v = ctx.parsed.y;
                  return v != null
                    ? `${ctx.dataset.label}: ${v.toLocaleString()}万円`
                    : `${ctx.dataset.label}: —`;
                },
              },
            },
          },
        },
      });
    }

    const leftLand = left.land_price_yearly || [];
    const rightLand = right.land_price_yearly || [];
    if (leftLand.length || rightLand.length) {
      const years = [
        ...new Set([
          ...leftLand.map((r) => r.survey_year),
          ...rightLand.map((r) => r.survey_year),
        ]),
      ].sort();

      const leftMap = Object.fromEntries(leftLand.map((r) => [r.survey_year, r]));
      const rightMap = Object.fromEntries(rightLand.map((r) => [r.survey_year, r]));

      createChart("chart-compare-land-yearly", {
        type: "line",
        data: {
          labels: years.map((y) => `${y}年`),
          datasets: [
            {
              label: left.name_ja || "エリア A",
              data: years.map((y) => leftMap[y]?.avg_unit_price ?? null),
              borderColor: "#10b981",
              backgroundColor: "rgba(16, 185, 129, 0.1)",
              fill: false,
              tension: 0.25,
              pointRadius: 3,
            },
            {
              label: right.name_ja || "エリア B",
              data: years.map((y) => rightMap[y]?.avg_unit_price ?? null),
              borderColor: "#059669",
              borderDash: [6, 4],
              backgroundColor: "rgba(5, 150, 105, 0.08)",
              fill: false,
              tension: 0.25,
              pointRadius: 3,
            },
          ],
        },
        options: {
          ...baseOptions("円/㎡"),
          plugins: {
            ...baseOptions().plugins,
            title: {
              display: true,
              text: "地価公示 年平均地価の比較",
              font: { size: 14, weight: "600" },
            },
            tooltip: {
              callbacks: {
                label(ctx) {
                  const v = ctx.parsed.y;
                  return v != null
                    ? `${ctx.dataset.label}: ${Math.round(v).toLocaleString()}円/㎡`
                    : `${ctx.dataset.label}: —`;
                },
              },
            },
          },
        },
      });
    }
  };
})();
