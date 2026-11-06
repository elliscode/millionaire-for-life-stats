/*
 * Ticket comparison logic, shared by the browser (window.M4LChecker) and the
 * Node test suite (module.exports). Mirrors src/m4l/ticket_checker.py; both
 * are tested against tests/fixtures/checker_cases.json.
 *
 * `rules` is the embedded rules object: {whiteMin, whiteMax, whiteCount,
 * mbMin, mbMax, tiers: [{code, whites, mb, label, prize, lifetime}]}.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.M4LChecker = api;
})(this, function () {
  "use strict";

  function isInt(n) {
    return typeof n === "number" && Number.isInteger(n);
  }

  function validate(rules, whites, mb) {
    var errors = [];
    if (whites.length !== rules.whiteCount)
      errors.push("Enter exactly " + rules.whiteCount + " white ball numbers.");
    if (whites.some(function (n) { return !isInt(n) || n < rules.whiteMin || n > rules.whiteMax; }))
      errors.push("White ball numbers must be whole numbers from " + rules.whiteMin + " to " + rules.whiteMax + ".");
    if (new Set(whites).size !== whites.length)
      errors.push("White ball numbers must all be different.");
    if (!isInt(mb) || mb < rules.mbMin || mb > rules.mbMax)
      errors.push("The Millionaire Ball must be a whole number from " + rules.mbMin + " to " + rules.mbMax + ".");
    return errors;
  }

  function matchTier(rules, whites, mb, drawWhites, drawMb) {
    var drawn = new Set(drawWhites);
    var matched = Array.from(new Set(whites)).filter(function (n) { return drawn.has(n); })
      .sort(function (a, b) { return a - b; });
    var b = mb === drawMb;
    var tier = rules.tiers.find(function (t) { return t.whites === matched.length && t.mb === b; }) || null;
    return { matched: matched, mbMatched: b, tier: tier };
  }

  // drawings: [{d: "YYYY-MM-DD", w: [5 ints], m: int, p: [9 prize strings], u: url}]
  function checkTicket(rules, drawings, drawDate, whites, mb) {
    var errors = [];
    if (typeof drawDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(drawDate) ||
        isNaN(Date.parse(drawDate + "T00:00:00Z")))
      errors.push("Choose a valid drawing date.");
    errors = errors.concat(validate(rules, whites, mb));
    var drawing = drawings.find(function (d) { return d.d === drawDate; });
    if (!errors.length && !drawing) errors.push("No verified result is available for that date.");
    if (errors.length) return { ok: false, errors: errors };

    var m = matchTier(rules, whites, mb, drawing.w, drawing.m);
    var out = {
      ok: true, date: drawDate, matchedWhites: m.matched.length, matchedMillionaireBall: m.mbMatched,
      matchedNumbers: m.matched, sourceUrl: drawing.u, tier: null
    };
    if (m.tier) {
      var idx = rules.tiers.indexOf(m.tier);
      out.tier = {
        code: m.tier.code, label: m.tier.label,
        prize: m.tier.lifetime ? m.tier.prize : (drawing.p[idx] || m.tier.prize),
        lifetime: m.tier.lifetime || null
      };
    }
    return out;
  }

  return { validate: validate, matchTier: matchTier, checkTicket: checkTicket };
});
