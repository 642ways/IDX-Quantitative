// A Cloudflare Worker that starts the IDX Quant "Daily refresh" on GitHub as soon as the day's prices are final.
//
// Its cron trigger runs every 5 minutes from 16:00 to 19:55 WIB on weekdays. Each time it:
//   1. stops if the live site already shows today's data;
//   2. waits if a refresh started in the last 20 minutes, since it may still be running or deploying;
//   3. asks Yahoo whether IHSG's session is over and today's daily bar exists (on a market holiday there
//      is none, so nothing runs), and whether it's 16:20 WIB yet, when the app counts prices as final;
//   4. starts the GitHub workflow if all of that says go.
// GitHub's own schedule stays as a backup. A run started this way skips the refresh if today's final data
// is already saved, the same as the scheduled tries.
//
// Secrets: GITHUB_TOKEN, a fine-grained GitHub token for this repository only with "Actions: Read and
// write". Optional RUN_KEY, for testing from the browser:
//   https://<worker>.<subdomain>.workers.dev/?key=<RUN_KEY>&check=1   says what it would do now, starts nothing
//   https://<worker>.<subdomain>.workers.dev/?key=<RUN_KEY>           starts a refresh straight away

const REPOSITORY = "642ways/IDX-Quantitative";
const WORKFLOW = "daily.yml";
const BRANCH = "main";
const SITE_TODAY = "https://idx-quantitative.vercel.app/api/today.json";
const YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE?interval=1d&range=5d";

const WIB_MS = 7 * 60 * 60 * 1000;
export const FINAL_MINUTE = 16 * 60 + 20; // 16:20 WIB, the app's final_hour_wib and final_minute_wib
// Yahoo's IDX session ends at 16:15 WIB, after post-trading, and its daily bar exists all day while trading,
// so a few minutes after the session end is when the day's close and volume are settled
export const SETTLE_MINUTES = 10;
export const FALLBACK_MINUTE = 16 * 60 + 40; // If Yahoo can't be asked, go by the clock from 16:40 WIB
export const PATIENCE_MINUTES = 20; // A run started this recently may still be running or deploying

export const wibDate = (ms) => new Date(ms + WIB_MS).toISOString().slice(0, 10);
export const wibMinute = (ms) => {
  const moment = new Date(ms + WIB_MS);
  return moment.getUTCHours() * 60 + moment.getUTCMinutes();
};

// Whether Yahoo's daily IHSG chart shows today's session as finished. ready is null when the answer is unusable.
export function marketClosed(chart, nowMs) {
  const result = chart && chart.chart && chart.chart.result && chart.chart.result[0];
  if (!result || !Array.isArray(result.timestamp) || !result.timestamp.length) {
    return { ready: null, reason: "Yahoo's answer had no prices" };
  }
  const today = wibDate(nowMs);
  const latest = wibDate(result.timestamp[result.timestamp.length - 1] * 1000);
  if (latest !== today) return { ready: false, reason: `No IHSG bar for ${today} yet (latest is ${latest}), so the market hasn't traded today` };
  const end = result.meta && result.meta.currentTradingPeriod && result.meta.currentTradingPeriod.regular && result.meta.currentTradingPeriod.regular.end;
  if (end && nowMs < (end + SETTLE_MINUTES * 60) * 1000) {
    return { ready: false, reason: `The session ends at ${new Date(end * 1000 + WIB_MS).toISOString().slice(11, 16)} WIB; waiting ${SETTLE_MINUTES} minutes after it` };
  }
  if (wibMinute(nowMs) < FINAL_MINUTE) return { ready: false, reason: "Before 16:20 WIB, when the app counts prices as final" };
  return { ready: true, reason: `Today's IHSG session is over and settled` };
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

async function startRefresh(env) {
  const response = await fetch(`https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: { ...github(env), "User-Agent": "idx-quant-cron", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: BRANCH, inputs: { if_due: "true" } }),
  });
  // GitHub answers 204 with no body when the run has been queued
  const detail = response.status === 204 ? "Daily refresh started." : await response.text();
  return { ok: response.status === 204, status: response.status, detail };
}

// The scheduled decision, step by step. Returns what it decided and why, and starts the run unless dryRun.
export async function decide(env, nowMs, dryRun = false) {
  const today = wibDate(nowMs);
  try {
    const site = await getJson(`${SITE_TODAY}?t=${nowMs}`);
    if (site.data_date === today) return { action: "done", reason: `The site already shows ${today}` };
  } catch (error) {
    // Carry on: an unreachable site shouldn't stop the refresh
  }

  const runs = await getJson(`https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/runs?per_page=5`, github(env));
  const recent = (runs.workflow_runs || []).find((run) => nowMs - Date.parse(run.created_at) < PATIENCE_MINUTES * 60 * 1000);
  if (recent) return { action: "wait", reason: `A refresh started at ${recent.created_at} is ${recent.status}; giving it ${PATIENCE_MINUTES} minutes` };

  let market;
  try {
    market = marketClosed(await getJson(YAHOO_CHART), nowMs);
  } catch (error) {
    market = { ready: null, reason: `Yahoo couldn't be asked (${error.message})` };
  }
  if (market.ready === null) {
    market = wibMinute(nowMs) >= FALLBACK_MINUTE
      ? { ready: true, reason: `${market.reason}, and it's past 16:40 WIB` }
      : { ready: false, reason: `${market.reason}; going by the clock from 16:40 WIB` };
  }
  if (!market.ready) return { action: "wait", reason: market.reason };
  if (dryRun) return { action: "would start", reason: market.reason };

  const result = await startRefresh(env);
  if (!result.ok) throw new Error(`GitHub answered ${result.status}: ${result.detail}`);
  return { action: "started", reason: market.reason };
}

export default {
  async scheduled(controller, env) {
    const outcome = await decide(env, controller.scheduledTime);
    console.log(`${outcome.action}: ${outcome.reason}`);
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (!env.RUN_KEY || url.searchParams.get("key") !== env.RUN_KEY) {
      return new Response("This Worker starts the IDX Quant daily refresh as soon as the day's prices are final.\n");
    }
    if (url.searchParams.has("check")) {
      const outcome = await decide(env, Date.now(), true);
      return new Response(`${outcome.action}: ${outcome.reason}\n`);
    }
    const result = await startRefresh(env);
    return new Response(`GitHub answered ${result.status}. ${result.detail}\n`, { status: result.ok ? 200 : 502 });
  },
};
