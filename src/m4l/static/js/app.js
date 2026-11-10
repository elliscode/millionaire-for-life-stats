/* Millionaire for Life Tracker: page behavior.
 * Reads ONLY the JSON embedded in the page (#m4l-data). No network requests;
 * the page's CSP (connect-src 'none') would block them anyway. */
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("m4l-data").textContent);
  var SMALL_MAX = 240; // must match small.css's media="(max-width: 240px)"
  function isSmall() { return window.innerWidth <= SMALL_MAX; }
  var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function fmtDate(iso, withYear) {
    var p = iso.split("-");
    return MONTHS[+p[1] - 1] + " " + (+p[2]) + (withYear ? ", " + p[0] : "");
  }
  function fmtInt(n) { return Math.round(n).toLocaleString("en-US"); }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /* ---------- live "days since" (the HTML was generated earlier) -------- */
  function todayET() {
    // en-CA formats as YYYY-MM-DD
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit"
    }).format(new Date());
  }
  function daysBetween(a, b) {
    return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000);
  }
  try {
    var today = todayET();
    document.querySelectorAll(".js-days-since").forEach(function (node) {
      var n = daysBetween(node.getAttribute("data-from"), today);
      if (n >= 0) node.textContent = fmtInt(n);
    });
  } catch (e) { /* keep the server-rendered numbers */ }

  /* ---------- winners chart ------------------------------------------- */
  var S = DATA.series;
  var view = "cumulative";
  var winnersChart = null, playsChart = null;

  // Direct labels: the latest cumulative total at the end of each line.
  var endLabels = {
    id: "endLabels",
    afterDatasetsDraw: function (chart) {
      if (view !== "cumulative") return;
      var ctx = chart.ctx;
      ctx.save();
      ctx.font = "600 " + (isSmall() ? 10 : 12) + "px system-ui, -apple-system, Segoe UI, sans-serif";
      ctx.fillStyle = css("--ink");
      ctx.textAlign = "right";
      chart.data.datasets.forEach(function (ds, i) {
        var meta = chart.getDatasetMeta(i);
        if (meta.hidden || !meta.data.length) return;
        var pt = meta.data[meta.data.length - 1];
        var val = ds.data[ds.data.length - 1];
        ctx.fillText(ds.short + ": " + val, pt.x - 4, pt.y - 8);
      });
      ctx.restore();
    }
  };

  function datasets() {
    var cum = view === "cumulative";
    var common = cum
      ? { type: "line", stepped: true, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5,
          pointHoverBorderWidth: 2, pointHoverBorderColor: css("--surface"), fill: false }
      : { type: "bar", borderRadius: 4, borderSkipped: "start", maxBarThickness: 10, minBarLength: 0 };
    return [
      Object.assign({ label: "Top prize ($1M/yr for life)", short: "Top",
        data: cum ? S.topCumulative : S.topDaily,
        borderColor: css("--top"), backgroundColor: css("--top") }, common),
      Object.assign({ label: "Second prize ($100K/yr for life)", short: "Second",
        data: cum ? S.secondCumulative : S.secondDaily,
        borderColor: css("--second"), backgroundColor: css("--second") }, common)
    ];
  }

  function baseOptions() {
    var small = isSmall();
    Chart.defaults.font.size = small ? 9 : 12;
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      layout: { padding: { top: small ? 14 : 18, right: small ? 2 : 8 } },
      plugins: {
        legend: { display: false }, // HTML legend above the chart
        tooltip: {
          backgroundColor: css("--surface"), titleColor: css("--ink"), bodyColor: css("--ink-2"),
          borderColor: css("--axis"), borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true
        }
      },
      scales: {
        x: {
          grid: { display: false }, border: { color: css("--axis") },
          ticks: { color: css("--muted"), maxRotation: 0, autoSkip: true, maxTicksLimit: isSmall() ? 3 : window.innerWidth < 600 ? 4 : 8,
                   callback: function (v) { return fmtDate(this.getLabelForValue(v)); } }
        },
        y: {
          beginAtZero: true, grid: { color: css("--grid") }, border: { display: false },
          ticks: { color: css("--muted"), precision: 0 }
        }
      }
    };
  }

  function winnersOptions() {
    var o = baseOptions();
    o.scales.y.title = { display: !isSmall(), text: "Winning tickets", color: css("--muted") };
    o.plugins.tooltip.callbacks = {
      title: function (items) { return fmtDate(items[0].label, true); },
      label: function (item) {
        var n = item.raw;
        var what = view === "cumulative" ? " total since launch" : (n === 1 ? " winning ticket" : " winning tickets");
        return " " + item.dataset.short + " prize: " + n + what;
      }
    };
    return o;
  }

  function playsOptions() {
    var o = baseOptions();
    o.plugins.tooltip.callbacks = {
      title: function (items) { return fmtDate(items[0].label, true); },
      label: function (item) { return " ≈ " + fmtInt(item.raw) + " plays (estimate)"; }
    };
    o.scales.y.beginAtZero = false;
    o.scales.y.ticks.callback = function (v) { return (v / 1e6).toFixed(1) + "M"; };
    return o;
  }

  function drawCharts() {
    if (typeof Chart === "undefined") return;
    if (winnersChart) winnersChart.destroy();
    if (playsChart) playsChart.destroy();
    winnersChart = new Chart(document.getElementById("winners-chart"), {
      data: { labels: S.dates, datasets: datasets() }, options: winnersOptions(), plugins: [endLabels]
    });
    playsChart = new Chart(document.getElementById("plays-chart"), {
      type: "line",
      data: { labels: S.dates, datasets: [{ label: "Estimated plays", data: DATA.plays,
        borderColor: css("--accent"), backgroundColor: css("--accent"), borderWidth: 2,
        pointRadius: 0, pointHoverRadius: 4, tension: 0 }] },
      options: playsOptions()
    });
  }

  var captions = {
    cumulative: "Total winning tickets since launch, through each drawing.",
    daily: "Winning tickets in each individual drawing. Most drawings have none."
  };
  document.querySelectorAll(".toggle button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      view = btn.getAttribute("data-view");
      document.querySelectorAll(".toggle button").forEach(function (b) {
        b.setAttribute("aria-pressed", String(b === btn));
      });
      document.getElementById("chart-caption").textContent = captions[view];
      drawCharts();
    });
  });
  drawCharts();
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(drawCharts);
  }

  /* ---------- ticket checker ------------------------------------------ */
  var form = document.getElementById("checker-form");
  var out = document.getElementById("checker-result");

  /* Enter advances: date -> ball 1 -> ... -> ball 5 -> Millionaire Ball,
   * and Enter on the Millionaire Ball submits (the form's normal behavior).
   * The KaiOS D-pad center key also sends Enter. */
  var entryOrder = [form.querySelector("#ck-date")]
    .concat(Array.prototype.slice.call(form.querySelectorAll(".balls .ball")))
    .concat([form.querySelector("#ck-mb")]);
  entryOrder.forEach(function (input, i) {
    var next = entryOrder[i + 1];
    if (!next) return; // last field: let Enter submit
    input.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter" || ev.isComposing) return;
      ev.preventDefault(); // don't submit the form yet
      next.focus();
      if (next.select) next.select();
    });
  });

  /* Warn when the newest drawing on the page isn't the newest that should
   * exist (e.g. last night's results weren't posted when the page was
   * built), so nobody checks last night's ticket against an older drawing. */
  function expectedLatestET() {
    var parts = {};
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23"
    }).formatToParts(new Date()).forEach(function (p) { parts[p.type] = p.value; });
    var mins = (+parts.hour % 24) * 60 + (+parts.minute);
    var back = mins >= DATA.resultsDueMinET ? 0 : 1 + Math.floor((DATA.resultsDueMinET - mins - 1) / 1440);
    var d = new Date(Date.UTC(+parts.year, +parts.month - 1, +parts.day - back));
    return d.toISOString().slice(0, 10);
  }
  var expectedDate = null;
  try {
    var exp = expectedLatestET();
    if (DATA.lastDate && exp > DATA.lastDate) {
      expectedDate = exp;
      var stale = document.getElementById("ck-stale");
      stale.textContent = fmtDate(exp) + " results aren't in yet. Newest here: " +
        fmtDate(DATA.lastDate) + ".";
      stale.hidden = false;
    }
  } catch (e) { /* no warning rather than a broken checker */ }

  function readInt(input) {
    var v = input.value.trim();
    return /^\d+$/.test(v) ? parseInt(v, 10) : NaN;
  }

  function renderErrors(errors) {
    out.className = "result result--error";
    out.replaceChildren(el("h3", null, "Please fix the following"));
    var ul = el("ul");
    errors.forEach(function (e) { ul.appendChild(el("li", null, e)); });
    out.appendChild(ul);
  }

  function renderResult(res, drawing) {
    out.className = "result" + (res.tier && res.tier.lifetime ? " result--lifetime" : "");
    out.replaceChildren();
    var heading;
    if (res.tier && res.tier.lifetime === "top") heading = "Your numbers match the TOP PRIZE combination!";
    else if (res.tier && res.tier.lifetime === "second") heading = "Your numbers match the SECOND PRIZE combination!";
    else if (res.tier) heading = "Matching combination: " + res.tier.label;
    else heading = "No matching prize combination";
    out.appendChild(el("h3", null, heading));
    if (expectedDate && res.date === DATA.lastDate) {
      out.appendChild(el("p", null, "Note: this is the " + fmtDate(res.date) + " drawing. " +
        fmtDate(expectedDate) + " results aren't in yet."));
    }

    if (res.tier) out.appendChild(el("p", null, "Prize category: " + res.tier.prize));
    if (res.tier && res.tier.lifetime) {
      out.appendChild(el("p", null, "If this is a real ticket, sign the back and contact your state lottery right away. This page can't confirm a win."));
    }
    out.appendChild(el("p", "muted", "You matched " + res.matchedWhites + " white ball" +
      (res.matchedWhites === 1 ? "" : "s") + (res.matchedMillionaireBall ? " plus the Millionaire Ball" : " and not the Millionaire Ball") +
      " in the " + fmtDate(res.date, true) + " drawing."));

    var drawn = el("div", "drawn");
    drawn.setAttribute("aria-label", "Winning numbers for that drawing; matches are filled in");
    drawing.w.forEach(function (n) {
      drawn.appendChild(el("span", res.matchedNumbers.indexOf(n) >= 0 ? "match" : "", String(n)));
    });
    drawn.appendChild(el("span", "mb" + (res.matchedMillionaireBall ? " match" : ""), String(drawing.m)));
    out.appendChild(drawn);

    var p = el("p");
    var a = el("a", null, "Official Powerball result for this drawing");
    a.href = res.sourceUrl;
    p.appendChild(a);
    out.appendChild(p);
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var whiteInputs = Array.prototype.slice.call(form.querySelectorAll(".balls .ball"));
    var whites = whiteInputs.map(readInt);
    var mbInput = form.querySelector("#ck-mb");
    var mb = readInt(mbInput);
    var date = form.querySelector("#ck-date").value;

    var rules = DATA.rules;
    whiteInputs.forEach(function (inp, i) {
      var n = whites[i];
      var bad = !(n >= rules.whiteMin && n <= rules.whiteMax) || whites.indexOf(n) !== i;
      inp.setAttribute("aria-invalid", String(bad));
    });
    mbInput.setAttribute("aria-invalid", String(!(mb >= rules.mbMin && mb <= rules.mbMax)));

    var res = M4LChecker.checkTicket(rules, DATA.drawings, date, whites, mb);
    if (!res.ok) renderErrors(res.errors);
    else renderResult(res, DATA.drawings.find(function (d) { return d.d === date; }));
    if (isSmall()) out.scrollIntoView({ block: "nearest" });
  });

  /* ---------- "Every drawing" table, built on demand ------------------ *
   * Rendering ~all rows up front made the page slow on the flip phone, so
   * the server sends none; they're built from the embedded data (the same
   * drawings the checker uses, index-aligned with series) on request.
   * Markup matches what the generator used to emit, so the CSS is unchanged. */
  function fmtLongDate(iso) {
    var p = iso.split("-");
    return DAYS[new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).getUTCDay()] + ", " + fmtDate(iso, true);
  }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function countCell(n) {
    return el("td", "num" + (n ? " hit" : ""), String(n));
  }
  var historyBtn = document.getElementById("history-load");
  historyBtn.addEventListener("click", function () {
    var body = document.getElementById("history-body");
    var frag = document.createDocumentFragment();
    for (var i = DATA.drawings.length - 1; i >= 0; i--) {
      var d = DATA.drawings[i], top = S.topDaily[i], sec = S.secondDaily[i];
      var tr = el("tr", top || sec ? "is-win" : null);
      var dateCell = el("td"), a = el("a"), t = el("time", null, fmtLongDate(d.d));
      a.href = d.u;
      t.setAttribute("datetime", d.d);
      a.appendChild(t);
      dateCell.appendChild(a);
      var nums = el("td", "nums", d.w.map(pad2).join(" ") + " ");
      var mb = el("span", "mb-num", String(d.m));
      mb.title = "Millionaire Ball";
      nums.appendChild(mb);
      tr.appendChild(dateCell);
      tr.appendChild(nums);
      tr.appendChild(countCell(top));
      tr.appendChild(countCell(sec));
      frag.appendChild(tr);
    }
    body.appendChild(frag);
    document.getElementById("history-wrap").hidden = false;
    historyBtn.remove();
    var first = body.querySelector("a");
    if (first) first.focus(); // keep D-pad focus where the button was
  });

  /* ---------- flip-phone "Check your numbers" button (<=240px) -------- *
   * position: absolute, placed here from innerWidth/innerHeight/scrollY on
   * every scroll/resize/focus change, instead of position: fixed, which
   * renders displaced on real KaiOS hardware (foursure's
   * notes/kaios-softkey-fixed-position-bug.md).
   *
   * Only shown while the page is scrolled to the very top. Once the page
   * scrolls, it slides down out of the viewport (CSS transition on the
   * .jump-check--away class), then becomes display:none. Scrolling back to
   * the top slides it back in. */
  var jump = document.getElementById("jump-check");
  var checkSection = document.getElementById("check");
  var JUMP_SLIDE_MS = 200; // keep in sync with small.css's transition
  var jumpState = "shown"; // "shown" | "hiding" | "hidden"
  var jumpTimer = null;

  function scrollTop() {
    return window.pageYOffset || document.documentElement.scrollTop || 0;
  }

  // Anchor to the viewport's bottom center (in document coordinates).
  function placeJumpButton() {
    jump.style.bottom = "auto";
    jump.style.top = (scrollTop() + window.innerHeight - jump.offsetHeight - 6) + "px";
    jump.style.left = Math.max(0, Math.round((window.innerWidth - jump.offsetWidth) / 2)) + "px";
  }

  function showJumpButton() {
    clearTimeout(jumpTimer);
    if (jumpState === "hidden") {
      jump.hidden = false;
      placeJumpButton();
      void jump.offsetWidth; // commit the off-screen start state before animating in
    } else {
      placeJumpButton();
    }
    jump.classList.remove("jump-check--away");
    jumpState = "shown";
  }

  function hideJumpButton() {
    if (jumpState === "hidden") return;
    // Keep re-anchoring while it slides out, so it doesn't ride up with the page
    placeJumpButton();
    if (jumpState === "hiding") return;
    jumpState = "hiding";
    jump.classList.add("jump-check--away");
    jumpTimer = setTimeout(function () {
      if (jumpState !== "hiding") return;
      jump.hidden = true; // display: none
      jumpState = "hidden";
    }, JUMP_SLIDE_MS + 30);
  }

  function updateJumpButton() {
    if (!isSmall()) return;
    if (scrollTop() <= 0) showJumpButton();
    else hideJumpButton();
  }

  jump.addEventListener("click", function () {
    checkSection.scrollIntoView({ block: "start" });
    var first = form.querySelector(".balls .ball");
    try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); }
    updateJumpButton();
  });
  window.addEventListener("scroll", updateJumpButton);
  window.addEventListener("resize", updateJumpButton);
  document.addEventListener("focusin", updateJumpButton);
  updateJumpButton();
})();
