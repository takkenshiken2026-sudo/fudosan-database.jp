(function () {
  var DATA = null;
  var TX = {};
  var sel = { pref: null, muni: null, district: "", type: null };

  var TYPE_LABEL = {
    mansion: "中古マンション",
    house: "戸建（土地＋建物）",
    land: "土地",
  };
  var AREA_LABEL = {
    mansion: "専有面積",
    house: "土地面積",
    land: "土地面積",
  };
  var AREA_HINT = {
    mansion: "専有面積のおおよその範囲を選択",
    house: "土地面積のおおよその範囲を選択（建物込みで試算）",
    land: "土地面積のおおよその範囲を選択",
  };
  var AREA_RANGES = {
    mansion: [
      { label: "30㎡未満", value: 25 },
      { label: "30〜45㎡", value: 37.5 },
      { label: "45〜60㎡", value: 52.5 },
      { label: "60〜75㎡", value: 67.5 },
      { label: "75〜90㎡", value: 82.5 },
      { label: "90〜110㎡", value: 100 },
      { label: "110㎡以上", value: 120 },
    ],
    house: [
      { label: "80㎡未満", value: 65 },
      { label: "80〜120㎡", value: 100 },
      { label: "120〜160㎡", value: 140 },
      { label: "160〜200㎡", value: 180 },
      { label: "200〜250㎡", value: 225 },
      { label: "250〜300㎡", value: 275 },
      { label: "300㎡以上", value: 340 },
    ],
    land: [
      { label: "50㎡未満", value: 40 },
      { label: "50〜80㎡", value: 65 },
      { label: "80〜120㎡", value: 100 },
      { label: "120〜180㎡", value: 150 },
      { label: "180〜250㎡", value: 215 },
      { label: "250〜350㎡", value: 300 },
      { label: "350〜500㎡", value: 425 },
      { label: "500㎡以上", value: 600 },
    ],
  };
  var AGE_RANGES = {
    mansion: [
      { label: "新築〜5年", value: 3 },
      { label: "6〜10年", value: 8 },
      { label: "11〜15年", value: 13 },
      { label: "16〜20年", value: 18 },
      { label: "21〜30年", value: 25 },
      { label: "31〜40年", value: 35 },
      { label: "41〜50年", value: 45 },
      { label: "51年以上", value: 55 },
    ],
    house: [
      { label: "新築〜5年", value: 3 },
      { label: "6〜15年", value: 10 },
      { label: "16〜25年", value: 20 },
      { label: "26〜35年", value: 30 },
      { label: "36〜50年", value: 43 },
      { label: "51年以上", value: 55 },
    ],
  };
  var TYPE_KEYS = ["mansion", "house", "land"];

  function $(id) {
    return document.getElementById(id);
  }

  function yen(v) {
    v = Math.round(v);
    if (v >= 100000000) {
      return (v / 100000000).toFixed(v >= 1000000000 ? 0 : 2).replace(/\.0+$/, "") + "億円";
    }
    if (v >= 10000) return Math.round(v / 10000).toLocaleString() + "万円";
    return v.toLocaleString() + "円";
  }

  function unitYen(v) {
    if (v >= 10000) {
      return (v / 10000).toLocaleString(undefined, { maximumFractionDigits: 1 }) + "万円/㎡";
    }
    return Math.round(v).toLocaleString() + "円/㎡";
  }

  function median(a) {
    if (!a.length) return null;
    var s = a.slice().sort(function (x, y) {
      return x - y;
    });
    var i = Math.floor(s.length / 2);
    return s.length % 2 ? s[i] : (s[i - 1] + s[i]) / 2;
  }

  function pctile(a, q) {
    if (!a.length) return null;
    var s = a.slice().sort(function (x, y) {
      return x - y;
    });
    var i = q * (s.length - 1);
    var lo = Math.floor(i);
    var f = i - lo;
    return lo + 1 >= s.length ? s[lo] : s[lo] * (1 - f) + s[lo + 1] * f;
  }

  function depr(type, age) {
    if (type === "land") return 1;
    var rate = type === "mansion" ? 0.013 : 0.01;
    var floor = type === "mansion" ? 0.3 : 0.45;
    return Math.max(floor, 1 - rate * age);
  }

  function curPref() {
    return DATA.prefectures.find(function (x) {
      return x.slug === sel.pref;
    });
  }

  function curMuni() {
    var p = curPref();
    return p && sel.muni ? p.m.find(function (x) { return x.slug === sel.muni; }) : null;
  }

  function muniDeals() {
    var t = TX[sel.pref];
    return (t && t[sel.muni]) || [];
  }

  function aggregateTypes(munis) {
    var out = {};
    TYPE_KEYS.forEach(function (k) {
      out[k] = { n: 0, unitW: 0, priceW: 0, w: 0 };
    });
    munis.forEach(function (muni) {
      TYPE_KEYS.forEach(function (k) {
        var t = muni.t[k];
        if (!t || !t.n) return;
        out[k].n += t.n;
        if (t.u) {
          out[k].unitW += t.u * t.n;
          out[k].w += t.n;
        }
        if (t.avg) out[k].priceW += t.avg * t.n;
      });
    });
    TYPE_KEYS.forEach(function (k) {
      var b = out[k];
      b.u = b.w ? b.unitW / b.w : null;
      b.avg = b.n ? b.priceW / b.n : null;
    });
    return out;
  }

  function topMunicipalities(pref, limit) {
    return pref.m
      .map(function (m) {
        var total = TYPE_KEYS.reduce(function (sum, k) {
          return sum + (m.t[k] ? m.t[k].n : 0);
        }, 0);
        return { name: m.name, slug: m.slug, total: total };
      })
      .filter(function (m) {
        return m.total > 0;
      })
      .sort(function (a, b) {
        return b.total - a.total;
      })
      .slice(0, limit || 5);
  }

  function selectedOptionLabel(el) {
    if (!el || el.selectedIndex < 0) return "";
    return el.options[el.selectedIndex].textContent || "";
  }

  function hasAreaSelected() {
    return $("area").value !== "";
  }

  function hasAgeSelected() {
    return sel.type !== "land" && $("age").value !== "";
  }

  function getSelectedArea() {
    return parseFloat($("area").value) || 0;
  }

  function getSelectedAge() {
    return parseInt($("age").value, 10) || 0;
  }

  function closestRangeIndex(ranges, target) {
    if (!target || !ranges.length) return 0;
    var best = 0;
    var bestDiff = Infinity;
    ranges.forEach(function (r, i) {
      var diff = Math.abs(r.value - target);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    });
    return best;
  }

  function fillSelectOptions(el, ranges, placeholder, defaultIndex) {
    el.innerHTML = "";
    var ph = document.createElement("option");
    ph.value = "";
    ph.textContent = placeholder;
    el.appendChild(ph);
    ranges.forEach(function (r, i) {
      var o = document.createElement("option");
      o.value = String(r.value);
      o.textContent = r.label;
      el.appendChild(o);
    });
    el.disabled = false;
    if (defaultIndex != null && ranges[defaultIndex]) {
      el.selectedIndex = defaultIndex + 1;
    }
  }

  function fillAreaAndAge() {
    var areaEl = $("area");
    var ageEl = $("age");
    if (!sel.muni || !sel.type) {
      areaEl.innerHTML = '<option value="">市区町村・種別を選択</option>';
      ageEl.innerHTML = '<option value="">市区町村・種別を選択</option>';
      areaEl.disabled = true;
      ageEl.disabled = true;
      return;
    }
    var m = curMuni();
    var t = m && m.t[sel.type];
    var areaRanges = AREA_RANGES[sel.type] || [];
    var areaIdx = t && t.a ? closestRangeIndex(areaRanges, t.a) : Math.floor(areaRanges.length / 2);
    fillSelectOptions(areaEl, areaRanges, "面積を選択", areaIdx);

    if (sel.type === "land") {
      ageEl.innerHTML = "";
      ageEl.disabled = true;
      return;
    }
    var ageRanges = AGE_RANGES[sel.type] || [];
    fillSelectOptions(ageEl, ageRanges, "築年数を選択", null);
  }

  function setAgeAdjDisplay(adj) {
    var wrap = $("r-age-adj-wrap");
    if (!wrap) return;
    if (sel.type === "land" || !hasAgeSelected() || Math.abs(adj - 1) < 0.02) {
      wrap.classList.add("hidden");
      return;
    }
    wrap.classList.remove("hidden");
    var pct = Math.round((adj - 1) * 100);
    $("r-age-adj").textContent =
      (pct > 0 ? "+" : "") + pct + "%（エリア平均築年比）";
  }

  function showResultPanel() {
    $("result-empty").classList.add("hidden");
    $("result").classList.remove("hidden");
  }

  function hideResultPanel() {
    $("result").classList.add("hidden");
    $("result-empty").classList.remove("hidden");
  }

  function renderTypeBreakdown(types, container) {
    container.innerHTML = "";
    TYPE_KEYS.forEach(function (k) {
      var t = types[k];
      if (!t || !t.n) return;
      var row = document.createElement("div");
      row.className = "flex justify-between text-sm py-1 border-b border-slate-100 last:border-0";
      row.innerHTML =
        '<span class="text-slate-600">' +
        TYPE_LABEL[k] +
        "</span>" +
        '<span class="tabular-nums text-slate-700">' +
        (t.u ? unitYen(t.u) : "—") +
        ' <span class="text-slate-400">(' +
        t.n.toLocaleString() +
        "件)</span></span>";
      container.appendChild(row);
    });
  }

  function renderComps(deals) {
    var body = $("comps-body");
    body.innerHTML = "";
    if (!deals.length) {
      $("comps").classList.add("hidden");
      return;
    }
    var rows = deals
      .slice()
      .sort(function (a, b) {
        return (b.y || 0) - (a.y || 0);
      })
      .slice(0, 8);
    rows.forEach(function (d) {
      var age = d.y ? "築" + (DATA.now - d.y) + "年" : "—";
      var unit = d.a && d.p ? unitYen(d.p / d.a) : "—";
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td class="px-2.5 py-1.5">' +
        (d.d || "—") +
        "</td>" +
        '<td class="px-2.5 py-1.5 text-right tabular-nums">' +
        (d.a ? d.a + "㎡" : "—") +
        "</td>" +
        '<td class="px-2.5 py-1.5 text-right tabular-nums">' +
        age +
        "</td>" +
        '<td class="px-2.5 py-1.5 text-right tabular-nums">' +
        (d.p ? yen(d.p) : "—") +
        "</td>" +
        '<td class="px-2.5 py-1.5 text-right tabular-nums">' +
        unit +
        "</td>";
      body.appendChild(tr);
    });
    $("comps-title").textContent =
      (sel.district ? sel.district : sel.muni ? "このエリア" : "主な市区町村") +
      "の実際の取引事例" +
      (deals.length > 8 ? "（新しい順に8件）" : "（" + deals.length + "件）");
    $("comps").classList.remove("hidden");
  }

  function setRangeVisible(visible, hint) {
    var wrap = $("r-range-wrap");
    if (visible) {
      wrap.classList.remove("hidden");
      $("r-range-hint").classList.add("hidden");
    } else {
      wrap.classList.add("hidden");
      $("r-range-hint").classList.remove("hidden");
      $("r-range-hint").textContent = hint || "面積を選ぶと参考価格レンジが表示されます";
    }
  }

  function updateResults() {
    if (!DATA || !sel.pref) {
      hideResultPanel();
      return;
    }

    var pref = curPref();
    if (!pref) {
      hideResultPanel();
      return;
    }

    showResultPanel();
    var m = curMuni();
    if (!m || !sel.type) {
      var wrap = $("r-age-adj-wrap");
      if (wrap) wrap.classList.add("hidden");
    }
    var area = getSelectedArea();
    var hasArea = hasAreaSelected() && area > 0;
    var age = sel.type === "land" ? 0 : getSelectedAge();
    var hasAge = hasAgeSelected() && age > 0;

    $("r-type-breakdown").classList.toggle("hidden", !!(m && sel.type));

    if (!m) {
      var prefTypes = aggregateTypes(pref.m);
      $("r-area-name").textContent = pref.name + "の相場概要";
      $("r-cond").textContent = "都道府県全体（直近5年の取引データ）";
      renderTypeBreakdown(prefTypes, $("r-type-breakdown"));

      var top = topMunicipalities(pref, 5);
      var totalN = TYPE_KEYS.reduce(function (s, k) {
        return s + (prefTypes[k] ? prefTypes[k].n : 0);
      }, 0);
      $("r-unit").textContent = "—";
      $("r-avg").textContent = "—";
      $("r-n").textContent = totalN.toLocaleString() + "件（県内合計）";
      setRangeVisible(false, "市区町村・面積を選ぶと参考価格レンジが表示されます");

      var note =
        "都道府県全体の種別別相場です。市区町村を選ぶとエリアが絞り込まれます。";
      if (top.length) {
        note += " 取引が多い市区町村: " + top.map(function (x) { return x.name; }).join("、") + "。";
      }
      $("r-note").textContent = note;
      $("comps").classList.add("hidden");
      $("r-link").setAttribute("href", "/price/" + sel.pref);
      $("r-link").textContent = pref.name + "の詳細ページを見る →";
      return;
    }

    if (!sel.type) {
      $("r-area-name").textContent = pref.name + m.name;
      $("r-cond").textContent = "物件種別を選択してください";
      setRangeVisible(false);
      $("comps").classList.add("hidden");
      return;
    }

    var t = m.t[sel.type];
    if (!t) {
      $("r-note").textContent = "この市区町村には選択した種別の取引データがありません。";
      return;
    }

    var typeDeals = muniDeals().filter(function (d) {
      return d.t === sel.type;
    });
    var scopeDeals = sel.district
      ? typeDeals.filter(function (d) {
          return d.d === sel.district;
        })
      : typeDeals;
    var units = scopeDeals
      .filter(function (d) {
        return d.a && d.p && d.a > 0;
      })
      .map(function (d) {
        return d.p / d.a;
      });
    var ages = scopeDeals
      .filter(function (d) {
        return d.y;
      })
      .map(function (d) {
        return DATA.now - d.y;
      });

    var basis, unit, loU, hiU, sampleN;
    if (sel.district && units.length >= 3) {
      basis = "district";
      unit = median(units);
      sampleN = units.length;
      loU = pctile(units, 0.25);
      hiU = pctile(units, 0.75);
      if (hiU / loU < 1.15) {
        loU = unit * 0.85;
        hiU = unit * 1.15;
      }
    } else {
      basis = "muni";
      unit = t.u;
      sampleN = t.n;
      loU = t.lo ? t.lo : t.u * 0.8;
      hiU = t.hi ? t.hi : t.u * 1.2;
    }

    var typAge = ages.length ? median(ages) : t.g != null ? t.g : 20;
    var adj = 1;
    if (hasArea && sel.type !== "land" && hasAge) {
      adj = depr(sel.type, age) / depr(sel.type, typAge);
      adj = Math.max(0.5, Math.min(1.7, adj));
    } else if (hasArea && sel.type !== "land") {
      adj = 1;
    }

    $("r-area-name").textContent = pref.name + m.name + (sel.district ? " " + sel.district : "");
    var cond = [TYPE_LABEL[sel.type]];
    if (hasArea) cond.push(selectedOptionLabel($("area")));
    if (hasAge) cond.push(selectedOptionLabel($("age")));
    $("r-cond").textContent = cond.join("・") || "市区町村の相場（条件を追加すると絞り込み）";

    if (hasArea && unit) {
      setRangeVisible(true);
      $("r-range").textContent = yen(loU * area * adj) + " 〜 " + yen(hiU * area * adj);
      var point = "中心値の目安 " + yen(unit * area * adj);
      if (hasAge && Math.abs(adj - 1) >= 0.02) {
        point += "（築年補正反映）";
      }
      $("r-point").textContent = point;
    } else {
      setRangeVisible(false, hasAge && !hasArea
        ? "面積を選ぶと築年数を反映した参考価格が表示されます"
        : "面積を選ぶと参考価格レンジが表示されます");
    }

    setAgeAdjDisplay(adj);

    $("r-unit").textContent = unit ? unitYen(unit) + (basis === "district" ? "（地区）" : "") : "—";
    $("r-avg").textContent = t.avg ? yen(t.avg) : "—";
    $("r-n").textContent = sampleN + "件" + (basis === "district" ? "（地区の同種取引）" : "");

    var note = "";
    if (!hasArea && hasAge) {
      note = "築年数「" + selectedOptionLabel($("age")) + "」を選択中です。面積を選ぶと参考価格に反映されます。";
    } else if (!hasArea) {
      note = "市区町村の相場を表示しています。面積・築年数を選ぶと参考価格レンジが算出されます。";
    } else if (!hasAge && sel.type !== "land") {
      note = "面積を反映した参考価格です。築年数を選ぶと新しさ・古さによる補正が加わります。";
    } else if (basis === "district") {
      note = "「" + sel.district + "」の同種取引" + sampleN + "件をもとに試算しました。";
    } else if (sel.district) {
      note =
        "「" +
        sel.district +
        "」の同種取引が少ない（" +
        units.length +
        "件）ため、市区町村全体の相場をもとに試算しました。";
    } else {
      note = "市区町村全体の相場をもとに試算しました。町名を選ぶと地区の事例で絞り込めます。";
    }
    if (hasArea && hasAge) {
      var ta = Math.round(typAge);
      if (age < ta - 3) note += " 平均築年数（約" + ta + "年）より新しいため、相場より高めになりやすい傾向です。";
      else if (age > ta + 3) note += " 平均築年数（約" + ta + "年）より古いため、相場より控えめになりやすい傾向です。";
    }
    if (sampleN < 5) note += " ※サンプルが少ないため参考程度にご覧ください。";
    $("r-note").textContent = note;

    renderComps(scopeDeals.length ? scopeDeals : typeDeals);
    $("r-link").setAttribute("href", "/price/" + sel.pref + "/" + sel.muni);
    $("r-link").textContent = "このエリアの詳細・実際の取引事例を見る →";
  }

  function fillPrefs() {
    var s = $("pref");
    DATA.prefectures.forEach(function (p) {
      var o = document.createElement("option");
      o.value = p.slug;
      o.textContent = p.name;
      s.appendChild(o);
    });
  }

  function fillMunis() {
    var s = $("muni");
    s.innerHTML = "";
    var p = curPref();
    if (!p) {
      s.disabled = true;
      s.innerHTML = '<option value="">先に都道府県を選択</option>';
      return;
    }
    s.disabled = false;
    var o0 = document.createElement("option");
    o0.value = "";
    o0.textContent = "選択してください（任意）";
    s.appendChild(o0);
    p.m.forEach(function (m) {
      var o = document.createElement("option");
      o.value = m.slug;
      o.textContent = m.name;
      s.appendChild(o);
    });
  }

  function fillDistricts() {
    var s = $("district");
    s.innerHTML = '<option value="">エリア全体</option>';
    sel.district = "";
    if (!sel.muni) {
      s.disabled = true;
      return;
    }
    var deals = muniDeals();
    if (!deals.length) {
      s.disabled = true;
      return;
    }
    var names = {};
    deals.forEach(function (d) {
      if (d.d && (!sel.type || d.t === sel.type)) names[d.d] = (names[d.d] || 0) + 1;
    });
    var list = Object.keys(names).sort(function (a, b) {
      return names[b] - names[a] || a.localeCompare(b, "ja");
    });
    if (!list.length) {
      s.disabled = true;
      return;
    }
    s.disabled = false;
    list.forEach(function (n) {
      var o = document.createElement("option");
      o.value = n;
      o.textContent = n + "（" + names[n] + "件）";
      s.appendChild(o);
    });
  }

  function fillTypes() {
    var box = $("ptype");
    box.innerHTML = "";
    sel.type = null;
    var m = curMuni();
    var empty = $("ptype-empty");
    if (!m) {
      empty.classList.remove("hidden");
      empty.textContent = "都道府県・市区町村を選ぶと選択できます";
      return;
    }
    var keys = TYPE_KEYS.filter(function (k) {
      return m.t[k];
    });
    if (!keys.length) {
      empty.classList.remove("hidden");
      return;
    }
    empty.classList.add("hidden");
    var cnt = {};
    muniDeals().forEach(function (d) {
      cnt[d.t] = (cnt[d.t] || 0) + 1;
    });
    keys.sort(function (a, b) {
      return (cnt[b] || m.t[b].n || 0) - (cnt[a] || m.t[a].n || 0);
    });
    keys.forEach(function (k) {
      var b = document.createElement("button");
      b.type = "button";
      b.dataset.k = k;
      b.className = "px-4 py-2 rounded-full text-sm font-medium transition border";
      b.textContent = TYPE_LABEL[k];
      b.addEventListener("click", function () {
        selectType(k);
      });
      box.appendChild(b);
    });
    selectType(keys[0]);
  }

  function selectType(k) {
    sel.type = k;
    Array.prototype.forEach.call($("ptype").children, function (b) {
      if (!b.dataset) return;
      var on = b.dataset.k === k;
      b.className =
        "px-4 py-2 rounded-full text-sm font-medium transition border " +
        (on
          ? "bg-brand-600 text-white border-brand-600"
          : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50");
    });
    $("area-label").textContent = AREA_LABEL[k];
    $("area-hint").textContent = AREA_HINT[k];
    $("age-wrap").style.display = k === "land" ? "none" : "";
    fillAreaAndAge();
    fillDistricts();
    updateResults();
  }

  function loadTx(pref) {
    if (TX[pref]) return Promise.resolve(TX[pref]);
    return fetch("/static/estimate-tx/" + pref + ".json")
      .then(function (r) {
        return r.ok ? r.json() : {};
      })
      .then(function (j) {
        TX[pref] = j;
        return j;
      })
      .catch(function () {
        TX[pref] = {};
        return {};
      });
  }

  function onPref() {
    sel.pref = $("pref").value;
    sel.muni = null;
    sel.district = "";
    sel.type = null;
    $("muni").value = "";
    $("ptype").innerHTML = "";
    $("ptype-empty").classList.remove("hidden");
    $("ptype-empty").textContent = "都道府県・市区町村を選ぶと選択できます";
    $("district").innerHTML = '<option value="">エリア全体</option>';
    $("district").disabled = true;

    if (!sel.pref) {
      fillMunis();
      fillAreaAndAge();
      hideResultPanel();
      return;
    }

    fillMunis();
    var mu = $("muni");
    mu.disabled = true;
    mu.innerHTML = '<option value="">読み込み中…</option>';
    loadTx(sel.pref).then(function () {
      fillMunis();
      updateResults();
    });
  }

  function onMuni() {
    sel.muni = $("muni").value || null;
    sel.district = "";
    if (!sel.muni) {
      $("ptype").innerHTML = "";
      $("ptype-empty").classList.remove("hidden");
      $("ptype-empty").textContent = "都道府県・市区町村を選ぶと選択できます";
      $("district").disabled = true;
      fillAreaAndAge();
      updateResults();
      return;
    }
    fillTypes();
    fillDistricts();
    updateResults();
  }

  function init() {
    fillPrefs();
    $("pref").addEventListener("change", onPref);
    $("muni").addEventListener("change", onMuni);
    $("district").addEventListener("change", function () {
      sel.district = this.value;
      updateResults();
    });
    $("area").addEventListener("change", updateResults);
    $("area").addEventListener("input", updateResults);
    $("age").addEventListener("change", updateResults);
    $("age").addEventListener("input", updateResults);
    $("est-form").addEventListener("submit", function (e) {
      e.preventDefault();
      updateResults();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch("/static/estimate-data.json")
      .then(function (r) {
        return r.json();
      })
      .then(function (j) {
        DATA = j;
        init();
      })
      .catch(function () {
        $("result-empty").innerHTML =
          '<p class="text-sm text-red-500">データの読み込みに失敗しました。時間をおいて再度お試しください。</p>';
      });
  });
})();
