#!/usr/bin/env node
"use strict";
/* Self-test of e2e/soft.cjs, the wording checks of the browser script (run by `npm test`, no browser needed). */
const assert = require("node:assert/strict");
const { match, noMatch, softly } = require("./soft.cjs");

const cases = [];
const it = (name, fn) => cases.push([name, fn]);
const rejects = async (fn) => { try { await fn(); } catch (e) { return e; } return null; };
const throws = (fn) => { try { fn(); } catch (e) { return e; } return null; };

it("a failed match outside softly throws at once, with its message and the text it saw", () => {
  const e = throws(() => match("the card says  X\nand more", /Y/, "the card names Y"));
  assert.ok(e instanceof Error);
  assert.equal(e.message, "the card names Y\n    text: the card says X and more");
});

it("a failed match without a message names the pattern", () => {
  assert.equal(throws(() => match("abc", /xyz/)).message, "expected text to match /xyz/\n    text: abc");
});

it("a failed noMatch outside softly throws at once, with what it found", () => {
  assert.equal(throws(() => noMatch("a DOES NOT MATCH b", /DOES NOT MATCH/, "no alarm")).message, 'no alarm\n    found: "DOES NOT MATCH"');
  assert.equal(throws(() => noMatch("abc", /b/)).message, 'text must not match /b/\n    found: "b"');
});

it("a passing match and noMatch return quietly", () => {
  assert.equal(match("abc", /b/), undefined);
  assert.equal(noMatch("abc", /z/), undefined);
});

it("the text in a failure is cut at 500 characters", () => {
  const e = throws(() => match("x".repeat(900), /y/));
  assert.equal(e.message, `expected text to match /y/\n    text: ${"x".repeat(500)}`);
});

it("inside softly every failed check is collected, the code after a failure still runs, and the test fails at the end naming each one", async () => {
  const seen = [];
  const e = await rejects(() => softly(async () => {
    match("abc", /xyz/, "first card says X"); seen.push("after first");
    match("abc", /abc/, "fine"); seen.push("after fine");
    noMatch("abc", /b/, "third card has no B"); seen.push("after third");
  }));
  assert.deepEqual(seen, ["after first", "after fine", "after third"]);
  assert.ok(e instanceof Error);
  assert.equal(e.message, '2 wording check(s) failed; every other check of this test still ran:\n- first card says X\n    text: abc\n- third card has no B\n    found: "b"');
});

it("inside softly a test with no failed check passes", async () => {
  assert.equal(await rejects(() => softly(async () => { match("abc", /b/); noMatch("abc", /z/); })), null);
});

it("after softly ends, checks throw at once again, whether it passed, failed or threw", async () => {
  await softly(async () => { match("abc", /b/); });
  assert.ok(throws(() => match("abc", /z/)));
  await rejects(() => softly(async () => { match("abc", /z/); }));
  assert.ok(throws(() => match("abc", /z/)));
  await rejects(() => softly(async () => { throw new Error("boom"); }));
  assert.ok(throws(() => noMatch("abc", /b/)));
});

it("an ordinary error inside softly is rethrown with the earlier wording failures appended, so none is lost", async () => {
  const e = await rejects(() => softly(async () => {
    match("abc", /xyz/, "early card is wrong");
    throw new Error("the element never appeared");
  }));
  assert.ok(e instanceof Error);
  assert.ok(e.message.startsWith("the element never appeared"));
  assert.equal(e.message, "the element never appeared\n1 wording check(s) had already failed before this:\n- early card is wrong\n    text: abc");
});

it("several earlier wording failures are all listed, one bullet each, when an ordinary error follows", async () => {
  const e = await rejects(() => softly(async () => {
    match("abc", /x/, "one");
    match("abc", /y/, "two");
    throw new Error("then it broke");
  }));
  assert.equal(e.message, "then it broke\n2 wording check(s) had already failed before this:\n- one\n    text: abc\n- two\n    text: abc");
});

it("a falsy thrown value is still rethrown and never swallowed", async () => {
  assert.equal(await rejects(() => softly(async () => { throw 0; })), 0);
  assert.equal(await rejects(() => softly(async () => { throw ""; })), "");
});

it("an ordinary error with no earlier failure is rethrown unchanged", async () => {
  const original = new Error("plain");
  const e = await rejects(() => softly(async () => { throw original; }));
  assert.equal(e, original);
  assert.equal(e.message, "plain");
});

it("something that is not an Error is rethrown as it is", async () => {
  const e = await rejects(() => softly(async () => { match("abc", /z/, "m"); throw "just a string"; }));
  assert.equal(e, "just a string");
});

it("two tests in a row do not share failures", async () => {
  const first = await rejects(() => softly(async () => { match("abc", /z/, "only in the first"); }));
  const second = await rejects(() => softly(async () => { match("abc", /y/, "only in the second"); }));
  assert.ok(first.message.includes("only in the first") && !first.message.includes("only in the second"));
  assert.ok(second.message.includes("only in the second") && !second.message.includes("only in the first"));
  assert.ok(first.message.startsWith("1 wording check(s) failed;") && second.message.startsWith("1 wording check(s) failed;"));
});

(async () => {
  let failed = 0;
  for (const [name, fn] of cases) {
    try { await fn(); console.log(`  ok   ${name}`); } catch (e) { failed += 1; console.log(`  FAIL ${name}\n       ${String(e && e.message ? e.message : e).split("\n").join("\n       ")}`); }
  }
  console.log(`${cases.length - failed} of ${cases.length} checks of e2e/soft.cjs passed.`);
  process.exit(failed ? 1 : 0);
})();
