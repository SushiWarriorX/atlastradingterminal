"use strict";
/*
 * The wording checks of the browser script (e2e/signal.e2e.cjs). A test that checks many independent cards (the Macro tab: about forty) runs inside `softly`:
 * a failed wording check (`match`, `noMatch`) is then collected and the test goes on, so one failing card no longer hides the cards after it, and the test still
 * fails at the end, naming every failure. Outside `softly` a failed check throws at once, as it always did. `assert` and `eq` of the script are not here: they guard
 * structure (an element that must exist), the code after them relies on it, and they always throw. Self-test: e2e/soft.test.cjs (run by `npm test`).
 */
let collected = null;

const fail = (message) => {
  if (collected) collected.push(message);
  else throw new Error(message);
};
const flat = (t) => String(t).replace(/\s+/g, " ").slice(0, 500);

const match = (t, re, m) => { if (!re.test(t)) fail(`${m || `expected text to match ${re}`}\n    text: ${flat(t)}`); };
const noMatch = (t, re, m) => { const r = re.exec(t); if (r) fail(`${m || `text must not match ${re}`}\n    found: "${r[0]}"`); };

async function softly(fn) {
  collected = [];
  let thrown = null;
  try { await fn(); } catch (e) { thrown = e; }
  const failures = collected;
  collected = null;
  if (thrown !== null) {
    if (failures.length && thrown instanceof Error) thrown.message += `\n${failures.length} wording check(s) had already failed before this:\n- ${failures.join("\n- ")}`;
    throw thrown;
  }
  if (failures.length) throw new Error(`${failures.length} wording check(s) failed; every other check of this test still ran:\n- ${failures.join("\n- ")}`);
}

module.exports = { match, noMatch, softly };
