// A Cloudflare Worker that starts the IDX Quant "Daily refresh" on GitHub whenever Yahoo has a finished
// trading day the live site doesn't show yet.
//
// It runs every 5 minutes from 16:00 to 19:55 WIB on weekdays, so a normal day refreshes about 16:25, and
// once an hour every day, to catch a day Yahoo publishes late. Each time it:
//   1. asks Yahoo for IHSG's daily bars and finds the latest finished day: today's bar only counts once
//      the session is over and settled (Yahoo's session runs to 16:15 WIB, plus 10 minutes);
//   2. stops if the live site already shows that day. On a market holiday or a weekend Yahoo has no
//      newer day, so nothing runs, and a day Yahoo publishes late is picked up as soon as it appears;
//   3. waits if a refresh started in the last 30 minutes, since it may still be running or deploying,
//      or if it has already started 4 refreshes in the last 12 hours without the site catching up;
//   4. otherwise starts the GitHub workflow.
// GitHub's own schedule stays as a backup. If Yahoo can't be reached, it goes by the clock: from 16:40
// WIB on a weekday it expects that day on the site.
//
// Secrets: GITHUB_TOKEN, a fine-grained GitHub token for this repository only with "Actions: Read and
// write". Optional RUN_KEY, for testing from the browser:
//   https://<worker>.<subdomain>.workers.dev/?key=<RUN_KEY>&check=1   says what it would do now, starts nothing
//   https://<worker>.<subdomain>.workers.dev/?key=<RUN_KEY>           starts a refresh straight away

const REPOSITORY = "642ways/IDX-Quantitative";
const WORKFLOW = "daily.yml";
const BRANCH = "main";
const SITE_TODAY = "https://idx-quantitative.vercel.app/api/today.json";
const YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE?interval=1d&range=10d";

const WIB_MS = 7 * 60 * 60 * 1000;
export const FINAL_MINUTE = 16 * 60 + 20; // 16:20 WIB, the app's final_hour_wib and final_minute_wib
// Yahoo's IDX session ends at 16:15 WIB, after post-trading, and its daily bar exists all day while trading,
// so a few minutes after the session end is when the day's close and volume are settled
export const SETTLE_MINUTES = 10;
export const FALLBACK_MINUTE = 16 * 60 + 40; // If Yahoo can't be asked, a weekday counts as finished from 16:40 WIB
export const PATIENCE_MINUTES = 30; // A run started this recently may still be running or deploying
export const MAX_TRIES = 4; // Refreshes the Worker starts in 12 hours before it stops trying for the same day
const TRY_WINDOW_MS = 12 * 60 * 60 * 1000;

export const wibDate = (ms) => new Date(ms + WIB_MS).toISOString().slice(0, 10);
export const wibMinute = (ms) => {
  const moment = new Date(ms + WIB_MS);
  return moment.getUTCHours() * 60 + moment.getUTCMinutes();
};
const isWeekday = (ms) => [1, 2, 3, 4, 5].includes(new Date(ms + WIB_MS).getUTCDay());

// The latest trading day Yahoo shows as finished. Today counts only once its session is over and settled.
// date is null when Yahoo's answer is unusable.
export function latestFinishedDay(chart, nowMs) {
  const result = chart && chart.chart && chart.chart.result && chart.chart.result[0];
  if (!result || !Array.isArray(result.timestamp) || !result.timestamp.length) {
    return { date: null, reason: "Yahoo's answer had no prices" };
  }
  const days = result.timestamp.map((stamp) => wibDate(stamp * 1000));
  const today = wibDate(nowMs);
  const latest = days[days.length - 1];
  if (latest !== today) return { date: latest, reason: `Yahoo's latest finished day is ${latest}` };

  const end = result.meta && result.meta.currentTradingPeriod && result.meta.currentTradingPeriod.regular && result.meta.currentTradingPeriod.regular.end;
  const settled = (!end || nowMs >= (end + SETTLE_MINUTES * 60) * 1000) && wibMinute(nowMs) >= FINAL_MINUTE;
  if (settled) return { date: today, reason: `Today's session is over and settled` };
  const previous = days.length > 1 ? days[days.length - 2] : null;
  const until = end ? `${new Date((end + SETTLE_MINUTES * 60) * 1000 + WIB_MS).toISOString().slice(11, 16)} WIB` : "16:20 WIB";
  return { date: previous, reason: `Today's session isn't settled until ${until}, so the latest finished day is ${previous}` };
}

async function getJson(url, headers = {}) {
  const response = await fetch(url, { headers: { "User-Agent": "idx-quant-cron", ...headers }, cf: { cacheTtl: 0 } });
  if (!response.ok) throw new Error(`${url} answered ${response.status}`);
  return response.json();
}

const github = (env) => ({
  Authorization: `Bearer ${env.GITHUB_TOKEN}`,
  Accept: "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
});

// The Worker has already checked that there's a newer day to fetch, so the run always refreshes
async function startRefresh(env) {
  const response = await fetch(`https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: { ...github(env), "User-Agent": "idx-quant-cron", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: BRANCH, inputs: { if_due: "false" } }),
  });
  // GitHub answers 204 with no body when the run has been queued
  const detail = response.status === 204 ? "Daily refresh started." : await response.text();
  return { ok: response.status === 204, status: response.status, detail };
}

// The scheduled decision, step by step. Returns what it decided and why, and starts the run unless dryRun.
export async function decide(env, nowMs, dryRun = false) {
  let latest;
  try {
    latest = latestFinishedDay(await getJson(YAHOO_CHART), nowMs);
  } catch (error) {
    latest = { date: null, reason: `Yahoo couldn't be asked (${error.message})` };
  }
  if (latest.date === null) {
    // Without Yahoo, go by the clock: a weekday counts as finished from 16:40 WIB
    if (!isWeekday(nowMs) || wibMinute(nowMs) < FALLBACK_MINUTE) return { action: "wait", reason: `${latest.reason}; going by the clock from 16:40 WIB on weekdays` };
    latest = { date: wibDate(nowMs), reason: `${latest.reason}, and it's past 16:40 WIB on a weekday` };
  }

  let shown = null;
  try {
    shown = (await getJson(`${SITE_TODAY}?t=${nowMs}`)).data_date;
  } catch (error) {
    // Carry on: an unreachable site shouldn't stop the refresh
  }
  if (shown && shown >= latest.date) return { action: "done", reason: `The site already shows ${shown}. ${latest.reason}` };

  const runs = (await getJson(`https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/runs?per_page=20`, github(env))).workflow_runs || [];
  const age = (run) => nowMs - Date.parse(run.created_at);
  const recent = runs.find((run) => age(run) < PATIENCE_MINUTES * 60 * 1000);
  if (recent) return { action: "wait", reason: `A refresh started at ${recent.created_at} is ${recent.status}; giving it ${PATIENCE_MINUTES} minutes` };
  const tries = runs.filter((run) => run.event === "workflow_dispatch" && age(run) < TRY_WINDOW_MS).length;
  if (tries >= MAX_TRIES) {
    return { action: "wait", reason: `Already started ${tries} refreshes in 12 hours and the site still shows ${shown}; waiting rather than retrying again` };
  }

  const behind = `The site shows ${shown || "nothing readable"}, behind ${latest.date}. ${latest.reason}`;
  if (dryRun) return { action: "would start", reason: behind };
  const result = await startRefresh(env);
  if (!result.ok) throw new Error(`GitHub answered ${result.status}: ${result.detail}`);
  return { action: "started", reason: behind };
}

export default {
  async scheduled(controller, env) {
    const outcome = await decide(env, controller.scheduledTime);
    console.log(`${outcome.action}: ${outcome.reason}`);
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (!env.RUN_KEY || url.searchParams.get("key") !== env.RUN_KEY) {
      return new Response("This Worker starts the IDX Quant daily refresh whenever Yahoo has a finished trading day the site doesn't show yet.\n");
    }
    if (url.searchParams.has("check")) {
      const outcome = await decide(env, Date.now(), true);
      return new Response(`${outcome.action}: ${outcome.reason}\n`);
    }
    const result = await startRefresh(env);
    return new Response(`GitHub answered ${result.status}. ${result.detail}\n`, { status: result.ok ? 200 : 502 });
  },
};
