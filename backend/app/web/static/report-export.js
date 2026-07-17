/*
 * 取引事例レポートのクライアント側生成器。
 *
 * 静的サイト（GitHub Pages）にはサーバー処理が無いため、レポートのデータは
 * ページに JSON で埋め込み、PowerPoint / Word の生成はブラウザ内で行う。
 * 生成には PptxGenJS / docx（CDN から遅延ロード）を用いる。
 *
 * ロジックはブラウザと Node の双方で動くよう純関数として定義し、末尾で
 * 環境に応じて DOM 配線 or module.exports を行う（Node はテスト用）。
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
    seller: ["summary", "recent_cases", "price_brackets", "property_mix"],
    buyer: ["summary", "yearly_trend", "land_price_trend", "property_mix"],
    appraisal: ["summary", "property_mix", "land_price", "yearly_trend", "recent_cases", "methodology"],
  };
  var RECENT_LIMITS = { seller: 20, buyer: 10, appraisal: 10 };
  var SECTION_TITLES = {
    summary: "エリアサマリー",
    recent_cases: "直近の取引事例",
    price_brackets: "価格帯別の分布",
    property_mix: "物件種別の内訳（最新四半期）",
    yearly_trend: "取引価格の年次推移",
    land_price_trend: "地価公示の推移",
    land_price: "地価公示サマリー",
    methodology: "査定の手法と留意事項",
  };
  var PERIOD_LABELS = {
    1: "直近1年 + 年次推移",
    2: "直近2年 + 年次推移",
    3: "直近3年 + 年次推移",
    5: "直近5年 + 年次推移",
  };

  var RECENT_HEADERS = ["時期", "種別", "地区", "面積", "取引価格", "㎡単価"];
  var PROPERTY_HEADERS = ["種別", "件数", "平均価格", "㎡単価"];
  var BRACKET_HEADERS = ["価格帯", "件数", "平均㎡単価"];
  var YEARLY_HEADERS = ["年", "件数", "平均取引価格"];
  var LAND_TREND_HEADERS = ["調査年", "地点数", "平均地価", "前年比"];

  // ------------------------------------------------------------------ //
  // Formatters（Python 版 formatters.py と挙動を合わせる）
  // ------------------------------------------------------------------ //
  function nf(n) {
    return Math.round(n).toLocaleString("en-US");
  }
  function formatManYen(v) {
    if (v === null || v === undefined) return "—";
    var man = Number(v) / 10000;
    if (man >= 10000) return (man / 10000).toFixed(1) + "億円";
    if (man >= 1) return nf(man) + "万円";
    return nf(Number(v)) + "円";
  }
  function formatYenPerSqm(v) {
    if (v === null || v === undefined) return "—";
    return nf(Number(v)) + "円/㎡";
  }
  function formatCount(v) {
    if (v === null || v === undefined) return "0";
    return nf(Number(v));
  }
  function formatPercent(v) {
    if (v === null || v === undefined) return "—";
    var sign = v > 0 ? "+" : "";
    return sign + Number(v).toFixed(1) + "%";
  }
  function quarterLabel(y, q) {
    return y + "年 第" + q + "四半期";
  }
  function areaLabel(a) {
    return a ? nf(Number(a)) + "㎡" : "—";
  }

  // ------------------------------------------------------------------ //
  // データ整形
  // ------------------------------------------------------------------ //
  function normalizeType(t) {
    return TYPE_LABELS[t] ? t : "seller";
  }
  function normalizePeriod(p) {
    p = parseInt(p, 10);
    return p === 1 || p === 2 || p === 3 || p === 5 ? p : 2;
  }

  function summaryText(type, data) {
    var area = data.area;
    var total = formatCount(data.totalTransactions);
    var avg = data.recentAvgPrice ? formatManYen(data.recentAvgPrice) : null;
    var base;
    if (type === "seller") {
      base =
        area + "では累計 " + total + " 件の取引データが国土交通省 不動産情報ライブラリに登録されています。" +
        "以下の周辺取引事例をもとに、ご所有物件の想定価格帯をご確認いただけます。";
    } else if (type === "buyer") {
      base = area + "の不動産相場を、取引価格の年次推移と地価公示の動向からご説明します。累計取引件数は " + total + " 件です。";
    } else {
      base =
        area + "の価格根拠資料です。物件種別ごとの取引実績・㎡単価、地価公示、年次推移をもとに" +
        "査定価格の妥当性をご確認いただけます（累計 " + total + " 件）。";
    }
    if (avg) base += " 直近の平均取引価格は " + avg + " です。";
    if (data.yoyPriceChangePct !== null && data.yoyPriceChangePct !== undefined) {
      var y = data.yoyPriceChangePct;
      var dir = y > 0 ? "上昇" : y < 0 ? "下落" : "横ばい";
      base += " 直近の平均取引価格は前年比 " + (y > 0 ? "+" : "") + y.toFixed(1) + "%（" + dir + "）で推移しています。";
    }
    return base;
  }

  // 対象期間で直近取引事例を絞り込み、種別ごとの掲載件数に丸める。
  function filteredRecent(data, type, period) {
    var recent = (data.recentTransactions || []).slice();
    if (data.latestYear) {
      var minYear = data.latestYear - period + 1;
      recent = recent.filter(function (t) {
        return t.year >= minYear;
      });
    }
    return recent.slice(0, RECENT_LIMITS[type]);
  }

  function recentRow(t) {
    return [
      t.periodLabel || quarterLabel(t.year, t.quarter),
      t.type || "—",
      t.district || "—",
      areaLabel(t.area),
      formatManYen(t.price),
      formatYenPerSqm(t.unit),
    ];
  }

  function buildModel(data, type, period) {
    type = normalizeType(type);
    period = normalizePeriod(period);
    return {
      type: type,
      period: period,
      typeLabel: TYPE_LABELS[type],
      periodLabel: PERIOD_LABELS[period],
      sections: SECTION_PRESETS[type],
      summary: summaryText(type, data),
      recent: filteredRecent(data, type, period),
      yearly: (data.yearlyStats || []).slice(-10),
      landYearly: (data.landPriceYearly || []).slice(-10),
      brackets: data.priceBrackets || [],
      property: data.propertyStats || [],
    };
  }

  function footerBits(data) {
    var bits = [SOURCE_NOTE];
    if (data.statsUpdatedAt) bits.push("データ更新: " + data.statsUpdatedAt);
    return bits;
  }

  // ------------------------------------------------------------------ //
  // PowerPoint (PptxGenJS)
  // ------------------------------------------------------------------ //
  function pptxTable(slide, x, y, w, headers, rows, rightFrom) {
    rightFrom = rightFrom || 1;
    var body = [];
    var head = headers.map(function (h, c) {
      return {
        text: h,
        options: { bold: true, color: WHITE, fill: { color: PRIMARY }, align: c < rightFrom ? "left" : "right" },
      };
    });
    body.push(head);
    rows.forEach(function (row, r) {
      body.push(
        row.map(function (val, c) {
          return {
            text: String(val),
            options: {
              color: DARK,
              fill: { color: r % 2 ? LIGHT : WHITE },
              align: c < rightFrom ? "left" : "right",
            },
          };
        })
      );
    });
    slide.addTable(body, {
      x: x,
      y: y,
      w: w,
      fontFace: FONT,
      fontSize: 10.5,
      border: { type: "solid", pt: 0.5, color: BORDER },
      valign: "middle",
      autoPage: false,
    });
  }

  function pptxLineChart(PptxGenJS, slide, x, y, w, h, name, labels, values) {
    var lab = [];
    var val = [];
    for (var i = 0; i < labels.length; i++) {
      if (values[i] !== null && values[i] !== undefined) {
        lab.push(labels[i]);
        val.push(values[i]);
      }
    }
    slide.addChart("line", [{ name: name, labels: lab, values: val }], {
      x: x,
      y: y,
      w: w,
      h: h,
      chartColors: [PRIMARY],
      showLegend: true,
      legendPos: "b",
      legendFontFace: FONT,
      lineSmooth: false,
      lineDataSymbol: "circle",
      catAxisLabelFontFace: FONT,
      catAxisLabelFontSize: 9,
      valAxisLabelFontFace: FONT,
      valAxisLabelFontSize: 9,
    });
  }

  function contentSlide(pptx, title) {
    var slide = pptx.addSlide();
    slide.addShape(pptx.ShapeType ? pptx.ShapeType.rect : "rect", {
      x: 0,
      y: 0,
      w: "100%",
      h: 0.14,
      fill: { color: PRIMARY },
      line: { type: "none" },
    });
    slide.addText(title, { x: 0.6, y: 0.4, w: 12.1, h: 0.7, fontFace: FONT, fontSize: 22, bold: true, color: DARK });
    return slide;
  }

  function buildPptx(PptxGenJS, data, type, period) {
    var m = buildModel(data, type, period);
    var pptx = new PptxGenJS();
    pptx.defineLayout({ name: "REPORT", width: 13.333, height: 7.5 });
    pptx.layout = "REPORT";

    // 表紙
    var cover = pptx.addSlide();
    cover.addShape(pptx.ShapeType ? pptx.ShapeType.rect : "rect", {
      x: 0,
      y: 0,
      w: "100%",
      h: 3.4,
      fill: { color: PRIMARY },
      line: { type: "none" },
    });
    cover.addText(m.typeLabel, { x: 0.9, y: 0.7, w: 11.5, h: 0.5, fontFace: FONT, fontSize: 14, color: "BAE6FD" });
    cover.addText(data.area, { x: 0.9, y: 1.2, w: 11.5, h: 1.0, fontFace: FONT, fontSize: 40, bold: true, color: WHITE });
    cover.addText("周辺取引価格の統計・事例に基づくエリア分析（" + m.periodLabel + "）", {
      x: 0.9,
      y: 2.35,
      w: 11.5,
      h: 0.6,
      fontFace: FONT,
      fontSize: 16,
      color: "E0F2FE",
    });

    var kpis = [
      ["累計取引件数", formatCount(data.totalTransactions) + "件"],
      ["平均取引価格", formatManYen(data.recentAvgPrice)],
    ];
    if (data.latestYear) kpis.push(["最新データ", quarterLabel(data.latestYear, data.latestQuarter || 1)]);
    kpis.forEach(function (kpi, i) {
      var left = 0.9 + i * 3.85;
      cover.addShape(pptx.ShapeType ? pptx.ShapeType.roundRect : "roundRect", {
        x: left,
        y: 3.9,
        w: 3.6,
        h: 1.3,
        fill: { color: LIGHT },
        line: { color: BORDER, width: 1 },
        rectRadius: 0.08,
      });
      cover.addText(kpi[0], { x: left + 0.25, y: 4.05, w: 3.1, h: 0.4, fontFace: FONT, fontSize: 12, color: GREY });
      cover.addText(kpi[1], { x: left + 0.25, y: 4.45, w: 3.1, h: 0.6, fontFace: FONT, fontSize: 22, bold: true, color: PRIMARY });
    });
    cover.addText(footerBits(data).join("　｜　"), {
      x: 0.9,
      y: 6.7,
      w: 11.5,
      h: 0.5,
      fontFace: FONT,
      fontSize: 10,
      color: GREY,
    });

    m.sections.forEach(function (section) {
      if (section === "summary") {
        contentSlide(pptx, SECTION_TITLES.summary).addText(m.summary, {
          x: 0.6,
          y: 1.35,
          w: 12.1,
          h: 4.5,
          fontFace: FONT,
          fontSize: 15,
          color: DARK,
        });
      } else if (section === "recent_cases") {
        if (!m.recent.length) return;
        var s = contentSlide(pptx, SECTION_TITLES.recent_cases);
        var shown = m.recent.slice(0, 14);
        pptxTable(s, 0.6, 1.35, 12.1, RECENT_HEADERS, shown.map(recentRow), 3);
        var extra = m.recent.length - shown.length;
        if (extra > 0)
          s.addText("ほか " + extra + " 件の取引事例があります。", {
            x: 0.6,
            y: 7.0,
            w: 12.1,
            h: 0.35,
            fontFace: FONT,
            fontSize: 10,
            color: GREY,
          });
      } else if (section === "price_brackets") {
        if (!m.brackets.length) return;
        var sb = contentSlide(pptx, SECTION_TITLES.price_brackets);
        pptxTable(
          sb,
          0.6,
          1.35,
          7.5,
          BRACKET_HEADERS,
          m.brackets.map(function (b) {
            return [b.label, formatCount(b.count) + "件", formatYenPerSqm(b.unit)];
          })
        );
      } else if (section === "property_mix") {
        if (!m.property.length) return;
        var sp = contentSlide(pptx, SECTION_TITLES.property_mix);
        pptxTable(
          sp,
          0.6,
          1.35,
          12.1,
          PROPERTY_HEADERS,
          m.property.map(function (p) {
            return [p.type || "—", formatCount(p.count) + "件", formatManYen(p.avg), formatYenPerSqm(p.unit)];
          })
        );
      } else if (section === "yearly_trend") {
        if (!m.yearly.length) return;
        var sy = contentSlide(pptx, SECTION_TITLES.yearly_trend);
        pptxLineChart(
          PptxGenJS,
          sy,
          0.6,
          1.35,
          7.2,
          4.6,
          "平均取引価格（万円）",
          m.yearly.map(function (o) {
            return o.year + "年";
          }),
          m.yearly.map(function (o) {
            return o.avg ? Math.round(o.avg / 10000) : null;
          })
        );
        pptxTable(
          sy,
          8.1,
          1.35,
          4.6,
          YEARLY_HEADERS,
          m.yearly.map(function (o) {
            return [o.year + "年", formatCount(o.count) + "件", formatManYen(o.avg)];
          })
        );
      } else if (section === "land_price_trend") {
        if (!m.landYearly.length) return;
        var sl = contentSlide(pptx, SECTION_TITLES.land_price_trend);
        pptxLineChart(
          PptxGenJS,
          sl,
          0.6,
          1.35,
          7.2,
          4.6,
          "平均地価（円/㎡）",
          m.landYearly.map(function (o) {
            return o.year + "年";
          }),
          m.landYearly.map(function (o) {
            return o.avgUnitPrice ? Math.round(o.avgUnitPrice) : null;
          })
        );
        pptxTable(
          sl,
          8.1,
          1.35,
          4.6,
          LAND_TREND_HEADERS,
          m.landYearly.map(function (o) {
            return [o.year + "年", formatCount(o.pointCount) + "地点", formatYenPerSqm(o.avgUnitPrice), formatPercent(o.yoyPct)];
          }),
          1
        );
      } else if (section === "land_price") {
        var land = data.landPrices;
        if (!land || !land.pointCount) return;
        var sland = contentSlide(pptx, SECTION_TITLES.land_price);
        var cards = [
          ["地点数", formatCount(land.pointCount) + "地点"],
          ["平均地価", formatYenPerSqm(land.avgUnitPrice)],
          ["前年比", formatPercent(land.yoyChangeAvg)],
        ];
        cards.forEach(function (c, i) {
          var left = 0.6 + i * 4.05;
          sland.addShape(pptx.ShapeType ? pptx.ShapeType.roundRect : "roundRect", {
            x: left,
            y: 1.35,
            w: 3.8,
            h: 1.5,
            fill: { color: LIGHT },
            line: { color: BORDER, width: 1 },
            rectRadius: 0.08,
          });
          sland.addText(c[0], { x: left + 0.3, y: 1.55, w: 3.2, h: 0.4, fontFace: FONT, fontSize: 13, color: GREY });
          sland.addText(c[1], { x: left + 0.3, y: 2.0, w: 3.2, h: 0.7, fontFace: FONT, fontSize: 24, bold: true, color: PRIMARY });
        });
        if (land.latestYear)
          sland.addText(land.latestYear + "年 地価公示に基づく。", {
            x: 0.6,
            y: 3.15,
            w: 12.1,
            h: 0.4,
            fontFace: FONT,
            fontSize: 11,
            color: GREY,
          });
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
  function buildDocx(docx, data, type, period) {
    var m = buildModel(data, type, period);
    var Paragraph = docx.Paragraph;
    var TextRun = docx.TextRun;
    var HeadingLevel = docx.HeadingLevel;
    var Table = docx.Table;
    var TableRow = docx.TableRow;
    var TableCell = docx.TableCell;
    var WidthType = docx.WidthType;
    var AlignmentType = docx.AlignmentType;
    var jpFont = { ascii: FONT, eastAsia: FONT, hAnsi: FONT, cs: FONT };

    function run(text, opts) {
      opts = opts || {};
      return new TextRun({
        text: String(text),
        font: jpFont,
        bold: !!opts.bold,
        size: opts.size || 21,
        color: opts.color,
      });
    }
    function para(text, opts) {
      opts = opts || {};
      return new Paragraph({ children: [run(text, opts)], alignment: opts.align, spacing: opts.spacing });
    }
    function heading(text) {
      return new Paragraph({
        heading: HeadingLevel.HEADING_1,
        spacing: { before: 240, after: 120 },
        children: [run(text, { bold: true, size: 26, color: PRIMARY })],
      });
    }
    function cell(text, opts) {
      opts = opts || {};
      return new TableCell({
        width: opts.width ? { size: opts.width, type: WidthType.PERCENTAGE } : undefined,
        shading: opts.fill ? { fill: opts.fill } : undefined,
        children: [
          new Paragraph({
            alignment: opts.align,
            children: [run(text, { bold: opts.bold, size: 20, color: opts.color })],
          }),
        ],
      });
    }
    function table(headers, rows, rightFrom) {
      rightFrom = rightFrom || 1;
      var trs = [];
      trs.push(
        new TableRow({
          tableHeader: true,
          children: headers.map(function (h, c) {
            return cell(h, { bold: true, color: WHITE, fill: PRIMARY, align: c < rightFrom ? AlignmentType.LEFT : AlignmentType.RIGHT });
          }),
        })
      );
      rows.forEach(function (row) {
        trs.push(
          new TableRow({
            children: row.map(function (val, c) {
              return cell(val, { align: c < rightFrom ? AlignmentType.LEFT : AlignmentType.RIGHT });
            }),
          })
        );
      });
      return new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, rows: trs });
    }

    var children = [];
    children.push(
      new Paragraph({ heading: HeadingLevel.TITLE, children: [run(data.area, { bold: true, size: 40 })] })
    );
    children.push(para(m.typeLabel + "　｜　" + m.periodLabel, { color: GREY }));
    var kpiParts = [
      "累計取引件数: " + formatCount(data.totalTransactions) + "件",
      "平均取引価格: " + formatManYen(data.recentAvgPrice),
    ];
    if (data.latestYear) kpiParts.push("最新データ: " + quarterLabel(data.latestYear, data.latestQuarter || 1));
    children.push(para(kpiParts.join("　｜　"), { bold: true }));

    m.sections.forEach(function (section) {
      if (section === "summary") {
        children.push(heading(SECTION_TITLES.summary));
        children.push(para(m.summary));
      } else if (section === "recent_cases") {
        if (!m.recent.length) return;
        children.push(heading(SECTION_TITLES.recent_cases));
        children.push(table(RECENT_HEADERS, m.recent.map(recentRow), 3));
      } else if (section === "price_brackets") {
        if (!m.brackets.length) return;
        children.push(heading(SECTION_TITLES.price_brackets));
        children.push(
          table(
            BRACKET_HEADERS,
            m.brackets.map(function (b) {
              return [b.label, formatCount(b.count) + "件", formatYenPerSqm(b.unit)];
            })
          )
        );
      } else if (section === "property_mix") {
        if (!m.property.length) return;
        children.push(heading(SECTION_TITLES.property_mix));
        children.push(
          table(
            PROPERTY_HEADERS,
            m.property.map(function (p) {
              return [p.type || "—", formatCount(p.count) + "件", formatManYen(p.avg), formatYenPerSqm(p.unit)];
            })
          )
        );
      } else if (section === "yearly_trend") {
        if (!m.yearly.length) return;
        children.push(heading(SECTION_TITLES.yearly_trend));
        children.push(
          table(
            YEARLY_HEADERS,
            m.yearly.map(function (o) {
              return [o.year + "年", formatCount(o.count) + "件", formatManYen(o.avg)];
            })
          )
        );
      } else if (section === "land_price_trend") {
        if (!m.landYearly.length) return;
        children.push(heading(SECTION_TITLES.land_price_trend));
        children.push(
          table(
            LAND_TREND_HEADERS,
            m.landYearly.map(function (o) {
              return [o.year + "年", formatCount(o.pointCount) + "地点", formatYenPerSqm(o.avgUnitPrice), formatPercent(o.yoyPct)];
            }),
            1
          )
        );
      } else if (section === "land_price") {
        var land = data.landPrices;
        if (!land || !land.pointCount) return;
        children.push(heading(SECTION_TITLES.land_price));
        var yearTxt = land.latestYear ? "（" + land.latestYear + "年）" : "";
        children.push(
          para(
            "地点数 " + formatCount(land.pointCount) + "地点" + yearTxt + "　｜　平均地価 " +
              formatYenPerSqm(land.avgUnitPrice) + "　｜　前年比 " + formatPercent(land.yoyChangeAvg)
          )
        );
      } else if (section === "methodology") {
        children.push(heading(SECTION_TITLES.methodology));
        children.push(para(METHODOLOGY_TEXT));
      }
    });

    children.push(para(""));
    footerBits(data)
      .concat([DISCLAIMER])
      .forEach(function (bit) {
        children.push(para(bit, { size: 18, color: GREY }));
      });

    return new docx.Document({
      styles: { default: { document: { run: { font: jpFont, size: 21 } } } },
      sections: [{ children: children }],
    });
  }

  // ------------------------------------------------------------------ //
  // プレビュー HTML（画面表示用）
  // ------------------------------------------------------------------ //
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function htmlTable(headers, rows, rightFrom) {
    rightFrom = rightFrom || 1;
    var thead =
      "<thead class='bg-slate-50 text-slate-600'><tr>" +
      headers
        .map(function (h, c) {
          return "<th class='px-3 py-2 " + (c < rightFrom ? "text-left" : "text-right") + "'>" + esc(h) + "</th>";
        })
        .join("") +
      "</tr></thead>";
    var tbody =
      "<tbody class='divide-y divide-slate-100'>" +
      rows
        .map(function (row) {
          return (
            "<tr>" +
            row
              .map(function (val, c) {
                return "<td class='px-3 py-2 " + (c < rightFrom ? "" : "text-right tabular-nums") + "'>" + esc(val) + "</td>";
              })
              .join("") +
            "</tr>"
          );
        })
        .join("") +
      "</tbody>";
    return "<table class='w-full text-sm border border-slate-200 rounded-lg overflow-hidden'>" + thead + tbody + "</table>";
  }
  function renderPreviewHtml(data, type, period) {
    var m = buildModel(data, type, period);
    var out = [];
    out.push(
      "<header class='bg-gradient-to-br from-brand-700 to-brand-600 text-white p-8 md:p-10 rounded-t-2xl'>" +
        "<p class='text-brand-100 text-sm mb-2'>" + esc(m.typeLabel) + "</p>" +
        "<h1 class='text-2xl md:text-3xl font-bold'>" + esc(data.area) + "</h1>" +
        "<p class='mt-2 text-brand-100'>周辺取引価格の統計・事例に基づくエリア分析（" + esc(m.periodLabel) + "）</p>" +
        "</header>"
    );
    var body = ["<div class='p-8 md:p-10 space-y-8'>"];
    m.sections.forEach(function (section) {
      var title = SECTION_TITLES[section];
      var inner = "";
      if (section === "summary") {
        inner = "<p class='text-sm text-slate-600 leading-relaxed'>" + esc(m.summary) + "</p>";
      } else if (section === "recent_cases") {
        if (!m.recent.length) return;
        inner = htmlTable(RECENT_HEADERS, m.recent.map(recentRow), 3);
      } else if (section === "price_brackets") {
        if (!m.brackets.length) return;
        inner = htmlTable(
          BRACKET_HEADERS,
          m.brackets.map(function (b) {
            return [b.label, formatCount(b.count) + "件", formatYenPerSqm(b.unit)];
          })
        );
      } else if (section === "property_mix") {
        if (!m.property.length) return;
        inner = htmlTable(
          PROPERTY_HEADERS,
          m.property.map(function (p) {
            return [p.type || "—", formatCount(p.count) + "件", formatManYen(p.avg), formatYenPerSqm(p.unit)];
          })
        );
      } else if (section === "yearly_trend") {
        if (!m.yearly.length) return;
        inner = htmlTable(
          YEARLY_HEADERS,
          m.yearly.map(function (o) {
            return [o.year + "年", formatCount(o.count) + "件", formatManYen(o.avg)];
          })
        );
      } else if (section === "land_price_trend") {
        if (!m.landYearly.length) return;
        inner = htmlTable(
          LAND_TREND_HEADERS,
          m.landYearly.map(function (o) {
            return [o.year + "年", formatCount(o.pointCount) + "地点", formatYenPerSqm(o.avgUnitPrice), formatPercent(o.yoyPct)];
          }),
          1
        );
      } else if (section === "land_price") {
        var land = data.landPrices;
        if (!land || !land.pointCount) return;
        inner =
          "<div class='grid sm:grid-cols-3 gap-4 text-sm'>" +
          "<div class='rounded-lg bg-slate-50 p-4'><div class='text-slate-500'>地点数</div><div class='font-bold text-lg'>" +
          esc(formatCount(land.pointCount)) + "</div></div>" +
          "<div class='rounded-lg bg-slate-50 p-4'><div class='text-slate-500'>平均地価</div><div class='font-bold text-lg'>" +
          esc(formatYenPerSqm(land.avgUnitPrice)) + "</div></div>" +
          "<div class='rounded-lg bg-slate-50 p-4'><div class='text-slate-500'>前年比</div><div class='font-bold text-lg'>" +
          esc(formatPercent(land.yoyChangeAvg)) + "</div></div></div>";
      } else if (section === "methodology") {
        inner = "<p class='text-sm text-slate-600 leading-relaxed'>" + esc(METHODOLOGY_TEXT) + "</p>";
      }
      if (inner)
        body.push(
          "<section><h2 class='text-lg font-bold border-l-4 border-brand-600 pl-3 mb-4'>" + esc(title) + "</h2>" + inner + "</section>"
        );
    });
    body.push(
      "<footer class='text-xs text-slate-400 border-t border-slate-100 pt-6'><p>" +
        esc(SOURCE_NOTE) + "</p><p class='mt-1'>" + esc(DISCLAIMER) + "</p>" +
        (data.statsUpdatedAt ? "<p class='mt-1'>データ更新: " + esc(data.statsUpdatedAt) + "</p>" : "") +
        "</footer>"
    );
    body.push("</div>");
    out.push(body.join(""));
    return out.join("");
  }

  function fileBase(data, type) {
    return "report-" + (data.slug || "area") + "-" + normalizeType(type);
  }

  var api = {
    buildModel: buildModel,
    buildPptx: buildPptx,
    buildDocx: buildDocx,
    renderPreviewHtml: renderPreviewHtml,
    fileBase: fileBase,
    formatManYen: formatManYen,
    TYPE_LABELS: TYPE_LABELS,
  };

  // ------------------------------------------------------------------ //
  // 環境ごとの配線
  // ------------------------------------------------------------------ //
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api; // Node（テスト用）
  }

  if (typeof document === "undefined") return;

  var PPTX_CDN = "https://cdn.jsdelivr.net/npm/pptxgenjs@3.12.0/dist/pptxgen.bundle.js";
  var DOCX_CDN = "https://cdn.jsdelivr.net/npm/docx@8.5.0/build/index.umd.js";
  var loaded = {};
  function loadScript(src) {
    if (loaded[src]) return loaded[src];
    loaded[src] = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () {
        reject(new Error("読み込みに失敗しました: " + src));
      };
      document.head.appendChild(s);
    });
    return loaded[src];
  }
  function saveBlob(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var el = document.getElementById("report-data");
    if (!el) return;
    var data = JSON.parse(el.textContent);
    var typeSel = document.getElementById("report-type");
    var periodSel = document.getElementById("report-period");
    var preview = document.getElementById("report-preview");
    var pptxBtn = document.getElementById("dl-pptx");
    var docxBtn = document.getElementById("dl-docx");

    function currentType() {
      return typeSel ? typeSel.value : "seller";
    }
    function currentPeriod() {
      return periodSel ? periodSel.value : 2;
    }
    function refresh() {
      if (preview) preview.innerHTML = renderPreviewHtml(data, currentType(), currentPeriod());
    }
    if (typeSel) typeSel.addEventListener("change", refresh);
    if (periodSel) periodSel.addEventListener("change", refresh);
    refresh();

    function withBusy(btn, label, fn) {
      return function () {
        var original = btn.textContent;
        btn.disabled = true;
        btn.textContent = label;
        Promise.resolve()
          .then(fn)
          .catch(function (err) {
            alert("生成に失敗しました。時間をおいて再度お試しください。\n" + (err && err.message ? err.message : err));
          })
          .then(function () {
            btn.disabled = false;
            btn.textContent = original;
          });
      };
    }

    if (pptxBtn)
      pptxBtn.addEventListener(
        "click",
        withBusy(pptxBtn, "生成中…", function () {
          return loadScript(PPTX_CDN).then(function () {
            var pptx = buildPptx(window.PptxGenJS, data, currentType(), currentPeriod());
            return pptx.writeFile({ fileName: fileBase(data, currentType()) + ".pptx" });
          });
        })
      );
    if (docxBtn)
      docxBtn.addEventListener(
        "click",
        withBusy(docxBtn, "生成中…", function () {
          return loadScript(DOCX_CDN).then(function () {
            var doc = buildDocx(window.docx, data, currentType(), currentPeriod());
            return window.docx.Packer.toBlob(doc).then(function (blob) {
              saveBlob(blob, fileBase(data, currentType()) + ".docx");
            });
          });
        })
      );
  });
})();
