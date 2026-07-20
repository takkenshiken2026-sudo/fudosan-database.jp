/*
 * 取引事例レポートのクライアント側生成器（種別フィルタ＋グラフ対応版）。
 *
 * 静的サイトにはサーバー処理が無いため、レポートのデータはページに JSON で
 * 埋め込み、PowerPoint / Word の生成と絞り込み・グラフ描画はブラウザ内で行う。
 * ロジックはブラウザ / Node の双方で動く純関数として定義し、末尾で環境ごとに
 * DOM 配線 or module.exports する（Node はテスト用）。
 *
 * グラフ：
 *   - プレビュー … インライン SVG
 *   - PowerPoint … PptxGenJS のネイティブグラフ（編集可能）
 *   - Word       … canvas で描いた PNG 画像（ブラウザのみ）
 */
(function () {
  "use strict";

  var FONT = "Meiryo";
  var PRIMARY = "0369A1";
  var DARK = "0F172A";
  var GREY = "64748B";
  var LIGHT = "F1F5F9";
  var WHITE = "FFFFFF";
  var BORDER = "E2E8F0";
  var PALETTE = ["0369A1", "0EA5E9", "38BDF8", "F97316", "10B981", "8B5CF6", "EF4444"];

  var SOURCE_NOTE = "出典: 国土交通省 不動産情報ライブラリ（不動産取引価格情報・地価公示）";
  var DISCLAIMER = "本レポートは参考情報です。実際の取引条件は個別の物件・取引により異なります。";
  var METHODOLOGY_TEXT =
    "本資料の査定価格は、国土交通省 不動産情報ライブラリに登録された実際の取引価格情報" +
    "および地価公示データに基づく参考値です。物件種別ごとの㎡単価・成約事例・地価水準を" +
    "総合的に勘案していますが、個別要因（築年数・方位・接道・室内状態・売却時期等）により" +
    "実際の成約価格は変動します。正式な査定は現地調査のうえ行ってください。";

  var TYPE_LABELS = {
    seller: "売主向け（周辺取引事例）",
    buyer: "買主向け（エリア相場説明）",
    appraisal: "査定用（価格根拠資料）",
  };
  var SECTION_PRESETS = {
    seller: ["summary", "recent_cases", "price_brackets", "property_mix", "yearly_trend"],
    buyer: ["summary", "yearly_trend", "land_price_trend", "property_mix", "price_brackets"],
    appraisal: ["summary", "property_mix", "land_price", "yearly_trend", "land_price_trend", "recent_cases", "methodology"],
  };
  var RECENT_LIMITS = { seller: 20, buyer: 10, appraisal: 10 };
  var SECTION_TITLES = {
    summary: "エリアサマリー",
    recent_cases: "直近の取引事例",
    price_brackets: "価格帯別の分布",
    property_mix: "物件種別の内訳",
    yearly_trend: "取引価格の年次推移",
    land_price_trend: "地価公示の推移",
    land_price: "地価公示サマリー",
    methodology: "査定の手法と留意事項",
  };
  var PERIOD_LABELS = { 1: "直近1年 + 年次推移", 2: "直近2年 + 年次推移", 3: "直近3年 + 年次推移", 5: "直近5年 + 年次推移" };

  var RECENT_HEADERS = ["時期", "種別", "地区", "面積", "取引価格", "㎡単価"];
  var PROPERTY_HEADERS = ["種別", "件数", "平均価格", "㎡単価"];
  var BRACKET_HEADERS = ["価格帯", "件数"];
  var YEARLY_HEADERS = ["年", "件数", "平均取引価格"];
  var LAND_TREND_HEADERS = ["調査年", "地点数", "平均地価", "前年比"];

  // ------------------------------------------------------------------ //
  // Formatters
  // ------------------------------------------------------------------ //
  function nf(n) { return Math.round(n).toLocaleString("en-US"); }
  function formatManYen(v) {
    if (v === null || v === undefined) return "—";
    var man = Number(v) / 10000;
    if (man >= 10000) return (man / 10000).toFixed(1) + "億円";
    if (man >= 1) return nf(man) + "万円";
    return nf(Number(v)) + "円";
  }
  function formatYenPerSqm(v) { return v === null || v === undefined ? "—" : nf(Number(v)) + "円/㎡"; }
  function formatCount(v) { return v === null || v === undefined ? "0" : nf(Number(v)); }
  function formatPercent(v) {
    if (v === null || v === undefined) return "—";
    return (v > 0 ? "+" : "") + Number(v).toFixed(1) + "%";
  }
  function quarterLabel(y, q) { return y + "年 第" + q + "四半期"; }
  function areaLabel(a) { return a ? nf(Number(a)) + "㎡" : "—"; }

  // ------------------------------------------------------------------ //
  // データ整形
  // ------------------------------------------------------------------ //
  function normalizeType(t) { return TYPE_LABELS[t] ? t : "seller"; }
  function normalizePeriod(p) { p = parseInt(p, 10); return p === 1 || p === 2 || p === 3 || p === 5 ? p : 2; }

  // データに存在する物件種別（件数の多い順）
  function availableTypes(data) {
    var counts = {};
    (data.propertyStats || []).forEach(function (s) {
      if (s.type) counts[s.type] = (counts[s.type] || 0) + (s.count || 0);
    });
    return Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
  }
  function normalizePropType(data, pt) {
    if (!pt || pt === "all") return "all";
    return availableTypes(data).indexOf(pt) >= 0 ? pt : "all";
  }
  function propTypeLabel(pt) { return pt === "all" ? "すべての種別" : pt; }

  // 種別ごとの年次推移（propertyStats を年で集計）。all は全種別合計 yearlyStats。
  function yearlyForType(data, pt) {
    if (pt === "all") return (data.yearlyStats || []).map(function (y) {
      return { year: y.year, count: y.count, avg: y.avg, unit: y.unit };
    });
    var byYear = {};
    (data.propertyStats || []).forEach(function (s) {
      if (s.type !== pt) return;
      var b = byYear[s.year] || (byYear[s.year] = { count: 0, ws: 0, wc: 0, us: 0, uc: 0 });
      var c = s.count || 0;
      b.count += c;
      if (s.avg != null) { b.ws += s.avg * c; b.wc += c; }
      if (s.unit != null) { b.us += s.unit * c; b.uc += c; }
    });
    return Object.keys(byYear).map(Number).sort(function (a, b) { return a - b; }).map(function (y) {
      var b = byYear[y];
      return { year: y, count: b.count, avg: b.wc ? b.ws / b.wc : null, unit: b.uc ? b.us / b.uc : null };
    });
  }

  // 最新年の物件種別内訳（種別ごとに集計）。pt 指定時はその種別のみ。
  function propertyMix(data, pt) {
    var stats = data.propertyStats || [];
    if (!stats.length) return [];
    var latestYear = data.latestYear;
    if (!latestYear) latestYear = Math.max.apply(null, stats.map(function (s) { return s.year || 0; }));
    var byType = {};
    stats.forEach(function (s) {
      if (s.year !== latestYear) return;
      if (pt !== "all" && s.type !== pt) return;
      var b = byType[s.type] || (byType[s.type] = { type: s.type, count: 0, ws: 0, wc: 0, us: 0, uc: 0 });
      var c = s.count || 0;
      b.count += c;
      if (s.avg != null) { b.ws += s.avg * c; b.wc += c; }
      if (s.unit != null) { b.us += s.unit * c; b.uc += c; }
    });
    return Object.keys(byType).map(function (t) {
      var b = byType[t];
      return { type: t, count: b.count, avg: b.wc ? b.ws / b.wc : null, unit: b.uc ? b.us / b.uc : null };
    }).sort(function (a, b) { return b.count - a.count; });
  }

  function filteredRecent(data, pt, type, period) {
    var recent = (data.recentTransactions || []).slice();
    if (data.latestYear) {
      var minYear = data.latestYear - period + 1;
      recent = recent.filter(function (t) { return t.year >= minYear; });
    }
    if (pt !== "all") recent = recent.filter(function (t) { return t.type === pt; });
    return recent.slice(0, RECENT_LIMITS[type]);
  }

  function recentRow(t) {
    return [t.periodLabel || quarterLabel(t.year, t.quarter), t.type || "—", t.district || "—",
      areaLabel(t.area), formatManYen(t.price), formatYenPerSqm(t.unit)];
  }

  function summaryText(type, data, pt) {
    var area = data.area;
    var scope = pt === "all" ? "" : "（" + pt + "）";
    var total = formatCount(data.totalTransactions);
    var avg = data.recentAvgPrice ? formatManYen(data.recentAvgPrice) : null;
    var base;
    if (type === "seller") {
      base = area + scope + "では累計 " + total + " 件の取引データが国土交通省 不動産情報ライブラリに登録されています。以下の周辺取引事例をもとに、ご所有物件の想定価格帯をご確認いただけます。";
    } else if (type === "buyer") {
      base = area + scope + "の不動産相場を、取引価格の年次推移と地価公示の動向からご説明します。累計取引件数は " + total + " 件です。";
    } else {
      base = area + scope + "の価格根拠資料です。物件種別ごとの取引実績・㎡単価、地価公示、年次推移をもとに査定価格の妥当性をご確認いただけます（累計 " + total + " 件）。";
    }
    if (avg) base += " 直近の平均取引価格は " + avg + " です。";
    if (data.yoyPriceChangePct != null) {
      var y = data.yoyPriceChangePct, dir = y > 0 ? "上昇" : y < 0 ? "下落" : "横ばい";
      base += " 直近の平均取引価格は前年比 " + (y > 0 ? "+" : "") + y.toFixed(1) + "%（" + dir + "）で推移しています。";
    }
    return base;
  }

  function buildModel(data, type, pt, period) {
    type = normalizeType(type); period = normalizePeriod(period); pt = normalizePropType(data, pt);
    return {
      type: type, propType: pt, period: period,
      typeLabel: TYPE_LABELS[type], propLabel: propTypeLabel(pt), periodLabel: PERIOD_LABELS[period],
      sections: SECTION_PRESETS[type],
      summary: summaryText(type, data, pt),
      recent: filteredRecent(data, pt, type, period),
      yearly: yearlyForType(data, pt).slice(-10),
      landYearly: (data.landPriceYearly || []).slice(-10),
      brackets: data.priceBrackets || [],
      mix: propertyMix(data, pt),
    };
  }

  function footerBits(data) {
    var bits = [SOURCE_NOTE];
    if (data.statsUpdatedAt) bits.push("データ更新: " + data.statsUpdatedAt);
    return bits;
  }

  // ------------------------------------------------------------------ //
  // グラフ仕様（各描画方式で共有）
  // kind:'line'|'bar', title, categories:[...], values:[num|null], seriesName, color
  // ------------------------------------------------------------------ //
  function specYearly(m) {
    return { kind: "line", title: "平均取引価格（万円）", seriesName: "平均取引価格（万円）", color: PRIMARY,
      categories: m.yearly.map(function (o) { return o.year + "年"; }),
      values: m.yearly.map(function (o) { return o.avg ? Math.round(o.avg / 10000) : null; }) };
  }
  function specLandTrend(m) {
    return { kind: "line", title: "平均地価（円/㎡）", seriesName: "平均地価（円/㎡）", color: "10B981",
      categories: m.landYearly.map(function (o) { return o.year + "年"; }),
      values: m.landYearly.map(function (o) { return o.avgUnitPrice ? Math.round(o.avgUnitPrice) : null; }) };
  }
  function specMix(m) {
    return { kind: "bar", title: "物件種別 取引件数", seriesName: "件数", color: PRIMARY,
      categories: m.mix.map(function (o) { return o.type; }),
      values: m.mix.map(function (o) { return o.count || 0; }) };
  }
  function specBrackets(m) {
    return { kind: "bar", title: "価格帯別 取引件数", seriesName: "件数", color: "F97316",
      categories: m.brackets.map(function (b) { return b.label; }),
      values: m.brackets.map(function (b) { return b.count || 0; }) };
  }
  function hasData(spec) {
    return spec && spec.categories.length && spec.values.some(function (v) { return v != null && v !== 0; });
  }

  // ------------------------------------------------------------------ //
  // SVG グラフ（プレビュー用）
  // ------------------------------------------------------------------ //
  function niceMax(v) {
    if (v <= 0) return 1;
    var pow = Math.pow(10, Math.floor(Math.log10(v)));
    var n = v / pow;
    var step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return step * pow;
  }
  function svgChart(spec) {
    if (!hasData(spec)) return "";
    var W = 680, H = 260, padL = 56, padR = 16, padT = 28, padB = 46;
    var iw = W - padL - padR, ih = H - padT - padB;
    var vals = spec.values.map(function (v) { return v == null ? 0 : v; });
    var max = niceMax(Math.max.apply(null, vals));
    var n = spec.categories.length;
    var color = "#" + spec.color;
    var parts = [];
    parts.push("<svg viewBox='0 0 " + W + " " + H + "' width='100%' style='max-width:680px' font-family='sans-serif' role='img'>");
    parts.push("<text x='" + padL + "' y='16' font-size='12' fill='#334155'>" + esc(spec.title) + "</text>");
    // gridlines + y labels
    var gl = 4;
    for (var g = 0; g <= gl; g++) {
      var yy = padT + ih * (1 - g / gl);
      var lv = (max * g) / gl;
      parts.push("<line x1='" + padL + "' y1='" + yy.toFixed(1) + "' x2='" + (W - padR) + "' y2='" + yy.toFixed(1) + "' stroke='#e2e8f0'/>");
      parts.push("<text x='" + (padL - 6) + "' y='" + (yy + 4).toFixed(1) + "' font-size='10' fill='#94a3b8' text-anchor='end'>" + nf(lv) + "</text>");
    }
    function xOf(i) { return padL + (n <= 1 ? iw / 2 : (iw * i) / (n - 1)); }
    function xBar(i) { return padL + (iw * (i + 0.15)) / n; }
    var bw = (iw / n) * 0.7;
    if (spec.kind === "bar") {
      spec.values.forEach(function (v, i) {
        var h = ((v || 0) / max) * ih;
        parts.push("<rect x='" + xBar(i).toFixed(1) + "' y='" + (padT + ih - h).toFixed(1) + "' width='" + bw.toFixed(1) + "' height='" + h.toFixed(1) + "' fill='" + color + "' rx='2'/>");
      });
    } else {
      var pts = [];
      spec.values.forEach(function (v, i) {
        if (v == null) return;
        var x = xOf(i), y = padT + ih * (1 - v / max);
        pts.push(x.toFixed(1) + "," + y.toFixed(1));
      });
      parts.push("<polyline points='" + pts.join(" ") + "' fill='none' stroke='" + color + "' stroke-width='2'/>");
      spec.values.forEach(function (v, i) {
        if (v == null) return;
        var x = xOf(i), y = padT + ih * (1 - v / max);
        parts.push("<circle cx='" + x.toFixed(1) + "' cy='" + y.toFixed(1) + "' r='2.5' fill='" + color + "'/>");
      });
    }
    // x labels (thin out)
    var stepX = Math.ceil(n / 8);
    spec.categories.forEach(function (c, i) {
      if (i % stepX !== 0 && i !== n - 1) return;
      var x = spec.kind === "bar" ? xBar(i) + bw / 2 : xOf(i);
      parts.push("<text x='" + x.toFixed(1) + "' y='" + (H - padB + 16) + "' font-size='10' fill='#64748b' text-anchor='middle'>" + esc(c) + "</text>");
    });
    parts.push("</svg>");
    return "<div style='overflow-x:auto'>" + parts.join("") + "</div>";
  }

  // ------------------------------------------------------------------ //
  // canvas PNG グラフ（Word 用・ブラウザのみ）
  // ------------------------------------------------------------------ //
  function chartPng(spec) {
    if (typeof document === "undefined" || !hasData(spec)) return null;
    var W = 680, H = 260, scale = 2;
    var cv = document.createElement("canvas");
    cv.width = W * scale; cv.height = H * scale;
    var ctx = cv.getContext("2d");
    ctx.scale(scale, scale);
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, W, H);
    var padL = 56, padR = 16, padT = 28, padB = 46, iw = W - padL - padR, ih = H - padT - padB;
    var vals = spec.values.map(function (v) { return v == null ? 0 : v; });
    var max = niceMax(Math.max.apply(null, vals));
    var n = spec.categories.length, color = "#" + spec.color;
    ctx.fillStyle = "#334155"; ctx.font = "12px sans-serif"; ctx.textAlign = "left";
    ctx.fillText(spec.title, padL, 16);
    var gl = 4;
    for (var g = 0; g <= gl; g++) {
      var yy = padT + ih * (1 - g / gl);
      ctx.strokeStyle = "#e2e8f0"; ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
      ctx.fillStyle = "#94a3b8"; ctx.font = "10px sans-serif"; ctx.textAlign = "right";
      ctx.fillText(nf((max * g) / gl), padL - 6, yy + 4);
    }
    function xOf(i) { return padL + (n <= 1 ? iw / 2 : (iw * i) / (n - 1)); }
    var bw = (iw / n) * 0.7;
    if (spec.kind === "bar") {
      ctx.fillStyle = color;
      spec.values.forEach(function (v, i) {
        var h = ((v || 0) / max) * ih, x = padL + (iw * (i + 0.15)) / n;
        ctx.fillRect(x, padT + ih - h, bw, h);
      });
    } else {
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath(); var started = false;
      spec.values.forEach(function (v, i) {
        if (v == null) return;
        var x = xOf(i), y = padT + ih * (1 - v / max);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = color;
      spec.values.forEach(function (v, i) {
        if (v == null) return;
        var x = xOf(i), y = padT + ih * (1 - v / max);
        ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fill();
      });
    }
    ctx.fillStyle = "#64748b"; ctx.font = "10px sans-serif"; ctx.textAlign = "center";
    var stepX = Math.ceil(n / 8);
    spec.categories.forEach(function (c, i) {
      if (i % stepX !== 0 && i !== n - 1) return;
      var x = spec.kind === "bar" ? padL + (iw * (i + 0.15)) / n + bw / 2 : xOf(i);
      ctx.fillText(c, x, H - padB + 16);
    });
    var url = cv.toDataURL("image/png");
    var b64 = url.split(",")[1], bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  // ------------------------------------------------------------------ //
  // PowerPoint (PptxGenJS)
  // ------------------------------------------------------------------ //
  function pptxTable(slide, x, y, w, headers, rows, rightFrom) {
    rightFrom = rightFrom || 1;
    var body = [headers.map(function (h, c) {
      return { text: h, options: { bold: true, color: WHITE, fill: { color: PRIMARY }, align: c < rightFrom ? "left" : "right" } };
    })];
    rows.forEach(function (row, r) {
      body.push(row.map(function (val, c) {
        return { text: String(val), options: { color: DARK, fill: { color: r % 2 ? LIGHT : WHITE }, align: c < rightFrom ? "left" : "right" } };
      }));
    });
    slide.addTable(body, { x: x, y: y, w: w, fontFace: FONT, fontSize: 10, border: { type: "solid", pt: 0.5, color: BORDER }, valign: "middle", autoPage: false });
  }
  function pptxChart(slide, spec, x, y, w, h) {
    if (!hasData(spec)) return;
    var lab = [], val = [];
    spec.categories.forEach(function (c, i) { lab.push(c); val.push(spec.values[i] == null ? 0 : spec.values[i]); });
    var kind = spec.kind === "bar" ? "bar" : "line";
    slide.addChart(kind, [{ name: spec.seriesName, labels: lab, values: val }], {
      x: x, y: y, w: w, h: h, chartColors: [spec.color], showLegend: false, showTitle: true, title: spec.title,
      titleFontFace: FONT, titleFontSize: 12, titleColor: DARK,
      catAxisLabelFontFace: FONT, catAxisLabelFontSize: 8, valAxisLabelFontFace: FONT, valAxisLabelFontSize: 8,
      barDir: "col", lineDataSymbol: "circle", lineSmooth: false,
    });
  }
  function contentSlide(pptx, title) {
    var s = pptx.addSlide();
    s.addShape(pptx.ShapeType ? pptx.ShapeType.rect : "rect", { x: 0, y: 0, w: "100%", h: 0.14, fill: { color: PRIMARY }, line: { type: "none" } });
    s.addText(title, { x: 0.6, y: 0.4, w: 12.1, h: 0.7, fontFace: FONT, fontSize: 22, bold: true, color: DARK });
    return s;
  }

  function buildPptx(PptxGenJS, data, type, pt, period) {
    var m = buildModel(data, type, pt, period);
    var pptx = new PptxGenJS();
    pptx.defineLayout({ name: "R", width: 13.333, height: 7.5 }); pptx.layout = "R";

    var cover = pptx.addSlide();
    cover.addShape(pptx.ShapeType ? pptx.ShapeType.rect : "rect", { x: 0, y: 0, w: "100%", h: 3.4, fill: { color: PRIMARY }, line: { type: "none" } });
    cover.addText(m.typeLabel + "　/　" + m.propLabel, { x: 0.9, y: 0.7, w: 11.5, h: 0.5, fontFace: FONT, fontSize: 14, color: "BAE6FD" });
    cover.addText(data.area, { x: 0.9, y: 1.2, w: 11.5, h: 1.0, fontFace: FONT, fontSize: 40, bold: true, color: WHITE });
    cover.addText("周辺取引価格の統計・事例に基づくエリア分析（" + m.periodLabel + "）", { x: 0.9, y: 2.35, w: 11.5, h: 0.6, fontFace: FONT, fontSize: 16, color: "E0F2FE" });
    var kpis = [["累計取引件数", formatCount(data.totalTransactions) + "件"], ["平均取引価格", formatManYen(data.recentAvgPrice)]];
    if (data.latestYear) kpis.push(["最新データ", quarterLabel(data.latestYear, data.latestQuarter || 1)]);
    kpis.forEach(function (kpi, i) {
      var left = 0.9 + i * 3.85;
      cover.addShape(pptx.ShapeType ? pptx.ShapeType.roundRect : "roundRect", { x: left, y: 3.9, w: 3.6, h: 1.3, fill: { color: LIGHT }, line: { color: BORDER, width: 1 }, rectRadius: 0.08 });
      cover.addText(kpi[0], { x: left + 0.25, y: 4.05, w: 3.1, h: 0.4, fontFace: FONT, fontSize: 12, color: GREY });
      cover.addText(kpi[1], { x: left + 0.25, y: 4.45, w: 3.1, h: 0.6, fontFace: FONT, fontSize: 22, bold: true, color: PRIMARY });
    });
    cover.addText(footerBits(data).join("　｜　"), { x: 0.9, y: 6.7, w: 11.5, h: 0.5, fontFace: FONT, fontSize: 10, color: GREY });

    m.sections.forEach(function (section) {
      if (section === "summary") {
        contentSlide(pptx, SECTION_TITLES.summary).addText(m.summary, { x: 0.6, y: 1.35, w: 12.1, h: 4.5, fontFace: FONT, fontSize: 15, color: DARK });
      } else if (section === "recent_cases") {
        if (!m.recent.length) return;
        var s = contentSlide(pptx, SECTION_TITLES.recent_cases + "（" + m.propLabel + "）");
        var shown = m.recent.slice(0, 14);
        pptxTable(s, 0.6, 1.35, 12.1, RECENT_HEADERS, shown.map(recentRow), 3);
        var extra = m.recent.length - shown.length;
        if (extra > 0) s.addText("ほか " + extra + " 件の取引事例があります。", { x: 0.6, y: 7.0, w: 12.1, h: 0.35, fontFace: FONT, fontSize: 10, color: GREY });
      } else if (section === "price_brackets") {
        if (!m.brackets.length) return;
        var sb = contentSlide(pptx, SECTION_TITLES.price_brackets + "（全種別）");
        pptxChart(sb, specBrackets(m), 0.6, 1.35, 7.0, 4.6);
        pptxTable(sb, 7.9, 1.35, 4.8, BRACKET_HEADERS, m.brackets.map(function (b) { return [b.label, formatCount(b.count) + "件"]; }));
      } else if (section === "property_mix") {
        if (!m.mix.length) return;
        var sp = contentSlide(pptx, SECTION_TITLES.property_mix + "（最新年 / " + m.propLabel + "）");
        pptxChart(sp, specMix(m), 0.6, 1.35, 6.4, 4.6);
        pptxTable(sp, 7.3, 1.35, 5.4, PROPERTY_HEADERS, m.mix.map(function (p) {
          return [p.type || "—", formatCount(p.count) + "件", formatManYen(p.avg), formatYenPerSqm(p.unit)];
        }));
      } else if (section === "yearly_trend") {
        if (!m.yearly.length) return;
        var sy = contentSlide(pptx, SECTION_TITLES.yearly_trend + "（" + m.propLabel + "）");
        pptxChart(sy, specYearly(m), 0.6, 1.35, 7.2, 4.6);
        pptxTable(sy, 8.1, 1.35, 4.6, YEARLY_HEADERS, m.yearly.map(function (o) { return [o.year + "年", formatCount(o.count) + "件", formatManYen(o.avg)]; }));
      } else if (section === "land_price_trend") {
        if (!m.landYearly.length) return;
        var sl = contentSlide(pptx, SECTION_TITLES.land_price_trend);
        pptxChart(sl, specLandTrend(m), 0.6, 1.35, 7.2, 4.6);
        pptxTable(sl, 8.1, 1.35, 4.6, LAND_TREND_HEADERS, m.landYearly.map(function (o) {
          return [o.year + "年", formatCount(o.pointCount) + "地点", formatYenPerSqm(o.avgUnitPrice), formatPercent(o.yoyPct)];
        }), 1);
      } else if (section === "land_price") {
        var land = data.landPrices;
        if (!land || !land.pointCount) return;
        var sland = contentSlide(pptx, SECTION_TITLES.land_price);
        [["地点数", formatCount(land.pointCount) + "地点"], ["平均地価", formatYenPerSqm(land.avgUnitPrice)], ["前年比", formatPercent(land.yoyChangeAvg)]].forEach(function (c, i) {
          var left = 0.6 + i * 4.05;
          sland.addShape(pptx.ShapeType ? pptx.ShapeType.roundRect : "roundRect", { x: left, y: 1.35, w: 3.8, h: 1.5, fill: { color: LIGHT }, line: { color: BORDER, width: 1 }, rectRadius: 0.08 });
          sland.addText(c[0], { x: left + 0.3, y: 1.55, w: 3.2, h: 0.4, fontFace: FONT, fontSize: 13, color: GREY });
          sland.addText(c[1], { x: left + 0.3, y: 2.0, w: 3.2, h: 0.7, fontFace: FONT, fontSize: 24, bold: true, color: PRIMARY });
        });
        if (land.latestYear) sland.addText(land.latestYear + "年 地価公示に基づく。", { x: 0.6, y: 3.15, w: 12.1, h: 0.4, fontFace: FONT, fontSize: 11, color: GREY });
      } else if (section === "methodology") {
        var sm = contentSlide(pptx, SECTION_TITLES.methodology);
        sm.addText(METHODOLOGY_TEXT, { x: 0.6, y: 1.35, w: 12.1, h: 4.5, fontFace: FONT, fontSize: 14, color: DARK });
        sm.addText(SOURCE_NOTE + "\n" + DISCLAIMER, { x: 0.6, y: 6.4, w: 12.1, h: 0.8, fontFace: FONT, fontSize: 10, color: GREY });
      }
    });
    return pptx;
  }

  // ------------------------------------------------------------------ //
  // Word (docx)
  // ------------------------------------------------------------------ //
  function buildDocx(docx, data, type, pt, period, opts) {
    opts = opts || {};
    var pngFor = opts.chartPng || function () { return null; };
    var m = buildModel(data, type, pt, period);
    var Paragraph = docx.Paragraph, TextRun = docx.TextRun, HeadingLevel = docx.HeadingLevel;
    var Table = docx.Table, TableRow = docx.TableRow, TableCell = docx.TableCell;
    var WidthType = docx.WidthType, AlignmentType = docx.AlignmentType, ImageRun = docx.ImageRun;
    var jp = { ascii: FONT, eastAsia: FONT, hAnsi: FONT, cs: FONT };

    function run(text, o) { o = o || {}; return new TextRun({ text: String(text), font: jp, bold: !!o.bold, size: o.size || 21, color: o.color }); }
    function para(text, o) { o = o || {}; return new Paragraph({ children: [run(text, o)], alignment: o.align, spacing: o.spacing }); }
    function heading(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 120 }, children: [run(text, { bold: true, size: 26, color: PRIMARY })] }); }
    function cell(text, o) {
      o = o || {};
      return new TableCell({ width: o.width ? { size: o.width, type: WidthType.PERCENTAGE } : undefined, shading: o.fill ? { fill: o.fill } : undefined,
        children: [new Paragraph({ alignment: o.align, children: [run(text, { bold: o.bold, size: 20, color: o.color })] })] });
    }
    function table(headers, rows, rightFrom) {
      rightFrom = rightFrom || 1;
      var trs = [new TableRow({ tableHeader: true, children: headers.map(function (h, c) {
        return cell(h, { bold: true, color: WHITE, fill: PRIMARY, align: c < rightFrom ? AlignmentType.LEFT : AlignmentType.RIGHT });
      }) })];
      rows.forEach(function (row) {
        trs.push(new TableRow({ children: row.map(function (val, c) {
          return cell(val, { align: c < rightFrom ? AlignmentType.LEFT : AlignmentType.RIGHT });
        }) }));
      });
      return new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, rows: trs });
    }
    function chartPara(spec) {
      var png = null;
      try { png = pngFor(spec); } catch (e) { png = null; }
      if (!png || !ImageRun) return null;
      return new Paragraph({ spacing: { after: 120 }, children: [new ImageRun({ data: png, transformation: { width: 560, height: 214 } })] });
    }

    var children = [];
    children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [run(data.area, { bold: true, size: 40 })] }));
    children.push(para(m.typeLabel + "　｜　" + m.propLabel + "　｜　" + m.periodLabel, { color: GREY }));
    var kpi = ["累計取引件数: " + formatCount(data.totalTransactions) + "件", "平均取引価格: " + formatManYen(data.recentAvgPrice)];
    if (data.latestYear) kpi.push("最新データ: " + quarterLabel(data.latestYear, data.latestQuarter || 1));
    children.push(para(kpi.join("　｜　"), { bold: true }));

    function pushChart(spec) { var p = chartPara(spec); if (p) children.push(p); }

    m.sections.forEach(function (section) {
      if (section === "summary") { children.push(heading(SECTION_TITLES.summary)); children.push(para(m.summary)); }
      else if (section === "recent_cases") {
        if (!m.recent.length) return;
        children.push(heading(SECTION_TITLES.recent_cases + "（" + m.propLabel + "）"));
        children.push(table(RECENT_HEADERS, m.recent.map(recentRow), 3));
      } else if (section === "price_brackets") {
        if (!m.brackets.length) return;
        children.push(heading(SECTION_TITLES.price_brackets + "（全種別）"));
        pushChart(specBrackets(m));
        children.push(table(BRACKET_HEADERS, m.brackets.map(function (b) { return [b.label, formatCount(b.count) + "件"]; })));
      } else if (section === "property_mix") {
        if (!m.mix.length) return;
        children.push(heading(SECTION_TITLES.property_mix + "（最新年 / " + m.propLabel + "）"));
        pushChart(specMix(m));
        children.push(table(PROPERTY_HEADERS, m.mix.map(function (p) { return [p.type || "—", formatCount(p.count) + "件", formatManYen(p.avg), formatYenPerSqm(p.unit)]; })));
      } else if (section === "yearly_trend") {
        if (!m.yearly.length) return;
        children.push(heading(SECTION_TITLES.yearly_trend + "（" + m.propLabel + "）"));
        pushChart(specYearly(m));
        children.push(table(YEARLY_HEADERS, m.yearly.map(function (o) { return [o.year + "年", formatCount(o.count) + "件", formatManYen(o.avg)]; })));
      } else if (section === "land_price_trend") {
        if (!m.landYearly.length) return;
        children.push(heading(SECTION_TITLES.land_price_trend));
        pushChart(specLandTrend(m));
        children.push(table(LAND_TREND_HEADERS, m.landYearly.map(function (o) { return [o.year + "年", formatCount(o.pointCount) + "地点", formatYenPerSqm(o.avgUnitPrice), formatPercent(o.yoyPct)]; }), 1));
      } else if (section === "land_price") {
        var land = data.landPrices;
        if (!land || !land.pointCount) return;
        children.push(heading(SECTION_TITLES.land_price));
        var yt = land.latestYear ? "（" + land.latestYear + "年）" : "";
        children.push(para("地点数 " + formatCount(land.pointCount) + "地点" + yt + "　｜　平均地価 " + formatYenPerSqm(land.avgUnitPrice) + "　｜　前年比 " + formatPercent(land.yoyChangeAvg)));
      } else if (section === "methodology") { children.push(heading(SECTION_TITLES.methodology)); children.push(para(METHODOLOGY_TEXT)); }
    });

    children.push(para(""));
    footerBits(data).concat([DISCLAIMER]).forEach(function (bit) { children.push(para(bit, { size: 18, color: GREY })); });

    return new docx.Document({ styles: { default: { document: { run: { font: jp, size: 21 } } } }, sections: [{ children: children }] });
  }

  // ------------------------------------------------------------------ //
  // プレビュー HTML
  // ------------------------------------------------------------------ //
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function htmlTable(headers, rows, rightFrom) {
    rightFrom = rightFrom || 1;
    var thead = "<thead class='bg-slate-50 text-slate-600'><tr>" + headers.map(function (h, c) {
      return "<th class='px-3 py-2 " + (c < rightFrom ? "text-left" : "text-right") + "'>" + esc(h) + "</th>";
    }).join("") + "</tr></thead>";
    var tbody = "<tbody class='divide-y divide-slate-100'>" + rows.map(function (row) {
      return "<tr>" + row.map(function (val, c) {
        return "<td class='px-3 py-2 " + (c < rightFrom ? "" : "text-right tabular-nums") + "'>" + esc(val) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody>";
    return "<table class='w-full text-sm border border-slate-200 rounded-lg overflow-hidden'>" + thead + tbody + "</table>";
  }
  function section(title, inner) {
    return "<section><h2 class='text-lg font-bold border-l-4 border-brand-600 pl-3 mb-4'>" + esc(title) + "</h2>" + inner + "</section>";
  }
  function renderPreviewHtml(data, type, pt, period) {
    var m = buildModel(data, type, pt, period);
    var out = ["<header class='bg-gradient-to-br from-brand-700 to-brand-600 text-white p-8 md:p-10 rounded-t-2xl'>" +
      "<p class='text-brand-100 text-sm mb-2'>" + esc(m.typeLabel) + "　/　" + esc(m.propLabel) + "</p>" +
      "<h1 class='text-2xl md:text-3xl font-bold'>" + esc(data.area) + "</h1>" +
      "<p class='mt-2 text-brand-100'>周辺取引価格の統計・事例に基づくエリア分析（" + esc(m.periodLabel) + "）</p></header>"];
    var body = ["<div class='p-8 md:p-10 space-y-8'>"];
    m.sections.forEach(function (sec) {
      if (sec === "summary") body.push(section(SECTION_TITLES.summary, "<p class='text-sm text-slate-600 leading-relaxed'>" + esc(m.summary) + "</p>"));
      else if (sec === "recent_cases") { if (m.recent.length) body.push(section(SECTION_TITLES.recent_cases + "（" + m.propLabel + "）", htmlTable(RECENT_HEADERS, m.recent.map(recentRow), 3))); }
      else if (sec === "price_brackets") { if (m.brackets.length) body.push(section(SECTION_TITLES.price_brackets + "（全種別）", svgChart(specBrackets(m)) + htmlTable(BRACKET_HEADERS, m.brackets.map(function (b) { return [b.label, formatCount(b.count) + "件"]; })))); }
      else if (sec === "property_mix") { if (m.mix.length) body.push(section(SECTION_TITLES.property_mix + "（最新年 / " + m.propLabel + "）", svgChart(specMix(m)) + htmlTable(PROPERTY_HEADERS, m.mix.map(function (p) { return [p.type || "—", formatCount(p.count) + "件", formatManYen(p.avg), formatYenPerSqm(p.unit)]; })))); }
      else if (sec === "yearly_trend") { if (m.yearly.length) body.push(section(SECTION_TITLES.yearly_trend + "（" + m.propLabel + "）", svgChart(specYearly(m)) + htmlTable(YEARLY_HEADERS, m.yearly.map(function (o) { return [o.year + "年", formatCount(o.count) + "件", formatManYen(o.avg)]; })))); }
      else if (sec === "land_price_trend") { if (m.landYearly.length) body.push(section(SECTION_TITLES.land_price_trend, svgChart(specLandTrend(m)) + htmlTable(LAND_TREND_HEADERS, m.landYearly.map(function (o) { return [o.year + "年", formatCount(o.pointCount) + "地点", formatYenPerSqm(o.avgUnitPrice), formatPercent(o.yoyPct)]; }), 1))); }
      else if (sec === "land_price") {
        var land = data.landPrices;
        if (land && land.pointCount) body.push(section(SECTION_TITLES.land_price,
          "<div class='grid sm:grid-cols-3 gap-4 text-sm'>" +
          "<div class='rounded-lg bg-slate-50 p-4'><div class='text-slate-500'>地点数</div><div class='font-bold text-lg'>" + esc(formatCount(land.pointCount)) + "</div></div>" +
          "<div class='rounded-lg bg-slate-50 p-4'><div class='text-slate-500'>平均地価</div><div class='font-bold text-lg'>" + esc(formatYenPerSqm(land.avgUnitPrice)) + "</div></div>" +
          "<div class='rounded-lg bg-slate-50 p-4'><div class='text-slate-500'>前年比</div><div class='font-bold text-lg'>" + esc(formatPercent(land.yoyChangeAvg)) + "</div></div></div>"));
      } else if (sec === "methodology") body.push(section(SECTION_TITLES.methodology, "<p class='text-sm text-slate-600 leading-relaxed'>" + esc(METHODOLOGY_TEXT) + "</p>"));
    });
    body.push("<footer class='text-xs text-slate-400 border-t border-slate-100 pt-6'><p>" + esc(SOURCE_NOTE) + "</p><p class='mt-1'>" + esc(DISCLAIMER) + "</p>" +
      (data.statsUpdatedAt ? "<p class='mt-1'>データ更新: " + esc(data.statsUpdatedAt) + "</p>" : "") + "</footer></div>");
    out.push(body.join(""));
    return out.join("");
  }

  function fileBase(data, type, pt) {
    var suffix = pt && pt !== "all" ? "-" + pt.replace(/[()（）\s]/g, "") : "";
    return "report-" + (data.slug || "area") + "-" + normalizeType(type) + suffix;
  }

  var api = { buildModel: buildModel, buildPptx: buildPptx, buildDocx: buildDocx, renderPreviewHtml: renderPreviewHtml,
    fileBase: fileBase, availableTypes: availableTypes, chartPng: chartPng, TYPE_LABELS: TYPE_LABELS };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  var PPTX_CDN = "https://cdn.jsdelivr.net/npm/pptxgenjs@3.12.0/dist/pptxgen.bundle.js";
  var DOCX_CDN = "https://cdn.jsdelivr.net/npm/docx@8.5.0/build/index.umd.js";
  var loaded = {};
  function loadScript(src) {
    if (loaded[src]) return loaded[src];
    loaded[src] = new Promise(function (resolve, reject) {
      var s = document.createElement("script"); s.src = src; s.onload = resolve;
      s.onerror = function () { reject(new Error("読み込みに失敗しました: " + src)); };
      document.head.appendChild(s);
    });
    return loaded[src];
  }
  function saveBlob(blob, name) {
    var url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var el = document.getElementById("report-data");
    if (!el) return;
    var data = JSON.parse(el.textContent);
    var typeSel = document.getElementById("report-type");
    var propSel = document.getElementById("report-proptype");
    var periodSel = document.getElementById("report-period");
    var preview = document.getElementById("report-preview");
    var pptxBtn = document.getElementById("dl-pptx");
    var docxBtn = document.getElementById("dl-docx");

    // 物件種別プルダウンをデータから生成
    if (propSel) {
      availableTypes(data).forEach(function (t) {
        var o = document.createElement("option"); o.value = t; o.textContent = t; propSel.appendChild(o);
      });
    }
    function cur() {
      return { type: typeSel ? typeSel.value : "seller", pt: propSel ? propSel.value : "all", period: periodSel ? periodSel.value : 2 };
    }
    function refresh() { if (preview) { var c = cur(); preview.innerHTML = renderPreviewHtml(data, c.type, c.pt, c.period); } }
    [typeSel, propSel, periodSel].forEach(function (s) { if (s) s.addEventListener("change", refresh); });
    refresh();

    function withBusy(btn, fn) {
      return function () {
        var orig = btn.textContent; btn.disabled = true; btn.textContent = "生成中…";
        Promise.resolve().then(fn).catch(function (err) {
          alert("生成に失敗しました。時間をおいて再度お試しください。\n" + (err && err.message ? err.message : err));
        }).then(function () { btn.disabled = false; btn.textContent = orig; });
      };
    }
    if (pptxBtn) pptxBtn.addEventListener("click", withBusy(pptxBtn, function () {
      var c = cur();
      return loadScript(PPTX_CDN).then(function () {
        return buildPptx(window.PptxGenJS, data, c.type, c.pt, c.period).writeFile({ fileName: fileBase(data, c.type, c.pt) + ".pptx" });
      });
    }));
    if (docxBtn) docxBtn.addEventListener("click", withBusy(docxBtn, function () {
      var c = cur();
      return loadScript(DOCX_CDN).then(function () {
        var doc = buildDocx(window.docx, data, c.type, c.pt, c.period, { chartPng: chartPng });
        return window.docx.Packer.toBlob(doc).then(function (blob) { saveBlob(blob, fileBase(data, c.type, c.pt) + ".docx"); });
      });
    }));
  });
})();
