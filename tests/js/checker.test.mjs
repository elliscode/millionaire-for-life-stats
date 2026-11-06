// Runs the browser checker logic (static/js/checker.js) against the same
// fixture cases as tests/test_ticket_checker.py.   node --test tests/js/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const checker = require("../../src/m4l/static/js/checker.js");
const fx = JSON.parse(readFileSync(new URL("../fixtures/checker_cases.json", import.meta.url)));

// Same shape generator.py embeds in the page (_rules()).
const TIERS = [
  ["m5-mb", 5, true, "top"], ["m5", 5, false, "second"], ["m4-mb", 4, true], ["m4", 4, false],
  ["m3-mb", 3, true], ["m3", 3, false], ["m2-mb", 2, true], ["m2", 2, false], ["m1-mb", 1, true],
];
const rules = {
  whiteMin: 1, whiteMax: 58, whiteCount: 5, mbMin: 1, mbMax: 5,
  tiers: TIERS.map(([code, whites, mb, lifetime]) => ({ code, whites, mb, label: code,
    prize: lifetime === "top" ? "$1,000,000 per year for life" : lifetime ? "$100,000 per year for life" : "fallback",
    lifetime: lifetime || null })),
};
const d = fx.drawing;
const drawings = [{ d: d.date, w: d.winningNumbers, m: d.millionaireBall, p: d.prizes, u: "https://example/x" }];

for (const c of fx.cases) {
  test(c.name, () => {
    const r = checker.checkTicket(rules, drawings, c.date || d.date, c.whites, c.mb);
    if (c.error) {
      assert.equal(r.ok, false);
      assert.ok(r.errors.some((e) => e.includes(c.error)), JSON.stringify(r.errors));
      return;
    }
    assert.equal(r.ok, true);
    if (c.tier === null) return assert.equal(r.tier, null);
    assert.equal(r.tier.code, c.tier);
    assert.equal(r.tier.lifetime, c.lifetime || null);
    if (c.prize) assert.equal(r.tier.prize, c.prize);
  });
}

test("rules embedded in the page match this test's tier table", () => {
  const gen = readFileSync(new URL("../../src/m4l/config.py", import.meta.url), "utf8");
  for (const [code] of TIERS) assert.ok(gen.includes(`"code": "${code}"`), code);
});
