// Run with: node --test scheduler/worker.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { decide, latestFinishedDay } from "./worker.js";

// Jakarta time is UTC+7. 16 to 20 November 2026 is Monday to Friday, 21 and 22 the weekend.
const at = (day, hhmm) => Date.parse(`2026-11-${day}T${hhmm}:00+07:00`);
const stamp = (day) => Date.parse(`2026-11-${day}T09:00:00+07:00`) / 1000;

// Yahoo's daily IHSG chart: one bar per trading day, stamped 09:00 WIB, with a session to 16:15 WIB
const chart = (days, sessionDay = days[days.length - 1]) => ({
  chart: {
    result: [
      {
        meta: { currentTradingPeriod: { regular: { start: stamp(sessionDay), end: Date.parse(`2026-11-${sessionDay}T16:15:00+07:00`) / 1000 } } },
        timestamp: days.map(stamp),
      },
    ],
  },
});

// A stand-in for the web: Yahoo, the site, and GitHub's run list and dispatch each answer as told
function fakeWeb({ yahoo, siteDate, runs = [], yahooFails = false }) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET", body: options.body });
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
    if (String(url).includes("yahoo")) return yahooFails ? json({}, 429) : json(yahoo);
    if (String(url).includes("vercel.app")) return json({ data_date: siteDate });
    if (String(url).endsWith("/dispatches")) return new Response(null, { status: 204 });
    if (String(url).includes("/runs")) return json({ workflow_runs: runs });
    throw new Error(`Unexpected request ${url}`);
  };
  return calls;
}

const env = { GITHUB_TOKEN: "test-token" };
const started = (calls) => calls.filter((call) => call.method === "POST");
const run = (day, hhmm, event = "workflow_dispatch", status = "completed") => ({ created_at: new Date(at(day, hhmm)).toISOString(), event, status });

test("today's bar counts once the session is over and settled", () => {
  const week = chart(["16", "17", "18"]);
  assert.equal(latestFinishedDay(week, at("18", "15:56")).date, "2026-11-17");
  assert.equal(latestFinishedDay(week, at("18", "16:20")).date, "2026-11-17");
  assert.equal(latestFinishedDay(week, at("18", "16:25")).date, "2026-11-18");
});

test("an unusable answer from Yahoo gives no day", () => {
  assert.equal(latestFinishedDay({ chart: { result: [] } }, at("18", "16:30")).date, null);
});

test("a normal day refreshes once the session is settled, and forces the refresh", async () => {
  const calls = fakeWeb({ yahoo: chart(["16", "17", "18"]), siteDate: "2026-11-17" });
  assert.equal((await decide(env, at("18", "16:25"))).action, "started");
  const [dispatch] = started(calls);
  assert.match(dispatch.url, /actions\/workflows\/daily\.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(dispatch.body), { ref: "main", inputs: { if_due: "false" } });
});

test("nothing happens while the session is still settling", async () => {
  const calls = fakeWeb({ yahoo: chart(["16", "17", "18"]), siteDate: "2026-11-17" });
  assert.equal((await decide(env, at("18", "16:15"))).action, "done");
  assert.equal(started(calls).length, 0);
});

test("nothing happens once the site shows the latest finished day", async () => {
  const calls = fakeWeb({ yahoo: chart(["16", "17", "18"]), siteDate: "2026-11-18" });
  assert.equal((await decide(env, at("18", "17:00"))).action, "done");
  assert.equal(started(calls).length, 0);
});

test("a market holiday or weekend starts nothing, since Yahoo has no newer day", async () => {
  const calls = fakeWeb({ yahoo: chart(["17", "18", "19"]), siteDate: "2026-11-19" });
  assert.equal((await decide(env, at("20", "18:00"))).action, "done");
  assert.equal((await decide(env, at("22", "10:17"))).action, "done");
  assert.equal(started(calls).length, 0);
});

test("a day Yahoo publishes late is picked up as soon as it appears, even on a weekend", async () => {
  // 20 November: Yahoo had no Friday bar all evening, so nothing ran, which was right
  let calls = fakeWeb({ yahoo: chart(["17", "18", "19"]), siteDate: "2026-11-19" });
  assert.equal((await decide(env, at("20", "19:55"))).action, "done");
  assert.equal(started(calls).length, 0);
  // Saturday morning the Friday bar appears, and the next hourly check starts the refresh
  calls = fakeWeb({ yahoo: chart(["18", "19", "20"]), siteDate: "2026-11-19", runs: [run("21", "05:19", "schedule")] });
  const outcome = await decide(env, at("21", "08:17"));
  assert.equal(outcome.action, "started");
  assert.match(outcome.reason, /behind 2026-11-20/);
});

test("a refresh started in the last 30 minutes is given time", async () => {
  const calls = fakeWeb({ yahoo: chart(["16", "17", "18"]), siteDate: "2026-11-17", runs: [run("18", "16:25", "workflow_dispatch", "in_progress")] });
  assert.equal((await decide(env, at("18", "16:50"))).action, "wait");
  assert.equal(started(calls).length, 0);
});

test("after 4 tries in 12 hours without the site catching up, it stops trying", async () => {
  const tries = ["16:25", "17:00", "18:00", "19:00"].map((time) => run("18", time));
  const calls = fakeWeb({ yahoo: chart(["16", "17", "18"]), siteDate: "2026-11-17", runs: tries });
  const outcome = await decide(env, at("18", "19:45"));
  assert.equal(outcome.action, "wait");
  assert.match(outcome.reason, /Already started 4 refreshes/);
  assert.equal(started(calls).length, 0);
});

test("if Yahoo can't be asked it goes by the clock from 16:40 on weekdays only", async () => {
  let calls = fakeWeb({ yahooFails: true, siteDate: "2026-11-17" });
  assert.equal((await decide(env, at("18", "16:30"))).action, "wait");
  calls = fakeWeb({ yahooFails: true, siteDate: "2026-11-17" });
  assert.equal((await decide(env, at("18", "16:45"))).action, "started");
  assert.equal(started(calls).length, 1);
  calls = fakeWeb({ yahooFails: true, siteDate: "2026-11-20" });
  assert.equal((await decide(env, at("21", "16:45"))).action, "wait");
});

test("a check starts nothing", async () => {
  const calls = fakeWeb({ yahoo: chart(["16", "17", "18"]), siteDate: "2026-11-17" });
  assert.equal((await decide(env, at("18", "16:25"), true)).action, "would start");
  assert.equal(started(calls).length, 0);
});
