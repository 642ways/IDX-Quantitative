// Run with: node --test scheduler/worker.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { decide, marketClosed } from "./worker.js";

// Monday 16 November 2026, Jakarta time is UTC+7
const at = (hhmm) => Date.parse(`2026-11-16T${hhmm}:00+07:00`);
// Yahoo reports IDX's session as 09:00 to 16:15 WIB, post-trading included
const SESSION_END = Date.parse("2026-11-16T16:15:00+07:00") / 1000;

const chart = (barDay = "2026-11-16", end = SESSION_END) => ({
  chart: {
    result: [
      {
        meta: { currentTradingPeriod: { regular: { start: end - 7 * 3600, end } } },
        timestamp: [Date.parse(`2026-11-13T09:00:00+07:00`) / 1000, Date.parse(`${barDay}T09:00:00+07:00`) / 1000],
      },
    ],
  },
});

// A stand-in for the web: the site, GitHub's run list and dispatch, and Yahoo, each answer as told
function fakeWeb({ siteDate = "2026-11-13", runs = [], yahoo = chart(), yahooFails = false } = {}) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET", body: options.body });
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
    if (String(url).includes("vercel.app")) return json({ data_date: siteDate });
    if (String(url).endsWith("/dispatches")) return new Response(null, { status: 204 });
    if (String(url).includes("/runs")) return json({ workflow_runs: runs });
    if (String(url).includes("yahoo")) return yahooFails ? json({}, 429) : json(yahoo);
    throw new Error(`Unexpected request ${url}`);
  };
  return calls;
}

const env = { GITHUB_TOKEN: "test-token" };
const started = (calls) => calls.filter((call) => call.method === "POST");

test("the market isn't closed before today's bar exists", () => {
  assert.equal(marketClosed(chart("2026-11-13"), at("16:45")).ready, false);
});

test("the market isn't settled until 10 minutes after the session ends", () => {
  assert.equal(marketClosed(chart(), at("15:56")).ready, false);
  assert.equal(marketClosed(chart(), at("16:20")).ready, false);
  assert.equal(marketClosed(chart(), at("16:25")).ready, true);
});

test("an early session end still waits for 16:20, when the app counts prices as final", () => {
  const halfDay = Date.parse("2026-11-16T11:30:00+07:00") / 1000;
  assert.equal(marketClosed(chart("2026-11-16", halfDay), at("12:00")).ready, false);
});

test("an unusable answer from Yahoo is neither yes nor no", () => {
  assert.equal(marketClosed({ chart: { result: [] } }, at("16:30")).ready, null);
});

test("nothing happens once the site shows today", async () => {
  const calls = fakeWeb({ siteDate: "2026-11-16" });
  assert.equal((await decide(env, at("16:30"))).action, "done");
  assert.equal(calls.length, 1);
});

test("a refresh started in the last 20 minutes is given time", async () => {
  const calls = fakeWeb({ runs: [{ created_at: new Date(at("16:22")).toISOString(), status: "in_progress" }] });
  assert.equal((await decide(env, at("16:30"))).action, "wait");
  assert.equal(started(calls).length, 0);
});

test("when the session is settled it starts the refresh, asking it to skip if already done", async () => {
  const calls = fakeWeb();
  assert.equal((await decide(env, at("16:25"))).action, "started");
  const [dispatch] = started(calls);
  assert.match(dispatch.url, /actions\/workflows\/daily\.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(dispatch.body), { ref: "main", inputs: { if_due: "true" } });
});

test("on a market holiday it never starts", async () => {
  const calls = fakeWeb({ yahoo: chart("2026-11-13") });
  assert.equal((await decide(env, at("18:00"))).action, "wait");
  assert.equal(started(calls).length, 0);
});

test("if Yahoo can't be asked it goes by the clock from 16:40", async () => {
  let calls = fakeWeb({ yahooFails: true });
  assert.equal((await decide(env, at("16:30"))).action, "wait");
  calls = fakeWeb({ yahooFails: true });
  assert.equal((await decide(env, at("16:45"))).action, "started");
  assert.equal(started(calls).length, 1);
});

test("a check starts nothing", async () => {
  const calls = fakeWeb();
  assert.equal((await decide(env, at("16:25"), true)).action, "would start");
  assert.equal(started(calls).length, 0);
});
