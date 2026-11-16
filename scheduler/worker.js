// A Cloudflare Worker that starts the IDX Quant "Daily refresh" workflow on GitHub at an exact time.
//
// GitHub's own schedule can start a run hours late. A run started through GitHub's API begins within
// seconds, so this Worker's cron trigger asks for one at 18:20 WIB on weekdays. The run is told to skip
// the refresh if today's final data is already saved, the same as GitHub's scheduled backup tries.
//
// Needs one secret, GITHUB_TOKEN: a fine-grained GitHub token for this repository only, with
// "Actions: Read and write". Optional secret RUN_KEY lets you start a run by hand from the browser:
// https://<worker-name>.<your-subdomain>.workers.dev/?key=<RUN_KEY>

const REPOSITORY = "642ways/IDX-Quantitative";
const WORKFLOW = "daily.yml";
const BRANCH = "main";

async function startRefresh(env) {
  const response = await fetch(`https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "idx-quant-cron",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: BRANCH, inputs: { if_due: "true" } }),
  });
  // GitHub answers 204 with no body when the run has been queued
  const detail = response.status === 204 ? "Daily refresh started." : await response.text();
  return { ok: response.status === 204, status: response.status, detail };
}

export default {
  async scheduled(controller, env) {
    const result = await startRefresh(env);
    if (!result.ok) {
      // Failing loudly makes the error show in the Worker's logs
      throw new Error(`GitHub answered ${result.status}: ${result.detail}`);
    }
  },

  async fetch(request, env) {
    const key = new URL(request.url).searchParams.get("key");
    if (env.RUN_KEY && key === env.RUN_KEY) {
      const result = await startRefresh(env);
      return new Response(`GitHub answered ${result.status}. ${result.detail}\n`, { status: result.ok ? 200 : 502 });
    }
    return new Response("This Worker starts the IDX Quant daily refresh on weekdays at 18:20 WIB.\n");
  },
};
