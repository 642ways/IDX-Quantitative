const DASH = "—";
const app = document.getElementById("app");
const banner = document.getElementById("banner");
const dataDate = document.getElementById("data-date");
const refreshButton = document.getElementById("refresh");
// The static site on Vercel reads daily JSON files instead of asking a running server
const STATIC_SITE = document.querySelector('meta[name="idx-mode"]')?.content === "static";
const KINDS = { long: "Long term", short: "Short term", pair: "Pair trade" };
const PLAY_HELP = { long: "Long-term play", short: "Short-term play", pair: "Pair trade rules" };
const ENDINGS = "Hits target, hits stop, neither in time";
const MARKET_TYPES = ["Rally", "Quiet", "Weakening", "Panic", "Rebound"];
let filter = "all";
let polling = false;
let chartPlays = [];
let regimeData = null;
let marketTypeData = null;
let equityData = null;
let showAllRecord = false;
let lastDataDate = null;
const RECORD_ROWS = 6;
const LOADING_DELAY = 150; // Fast loads skip the placeholder, so the page doesn't flash
let settings = null;
let helpTopics = [];
let helpTimer;
const HELP_HIDE_DELAY = 200;
const helpBox = document.getElementById("helpbox");

const esc = (value) =>
  String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const missing = (value) => value === null || value === undefined;
const price = (value) => (missing(value) ? DASH : Math.round(value).toLocaleString("en-US"));
const times = (value) => (missing(value) ? DASH : `${value.toFixed(1)}x`);
const rupiah = (value) =>
  missing(value) ? DASH : `Rp ${value.toLocaleString("en-US", { maximumFractionDigits: Math.abs(value) < 100 ? 1 : 0 })}`;
const money = (value) => {
  if (missing(value)) return DASH;
  const size = Math.abs(value);
  return size >= 1e12 ? `Rp ${(value / 1e12).toFixed(1)} tn` : `Rp ${(value / 1e9).toFixed(0)} bn`;
};
const pct = (value, digits = 1) => (missing(value) ? DASH : `${(value * 100).toFixed(digits)}%`);
const signedPct = (value) => (missing(value) ? DASH : `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`);
const help = (key, label = key) =>
  `<button type="button" class="help" data-help="${esc(key)}" aria-label="Explain ${esc(label)}">?</button>`;
const topicHelp = (topic, label) => help(`topic:${topic}`, label);
const tag = (kind) => `<span class="tag ${esc(kind)}">${esc(KINDS[kind] || kind)}</span>`;

async function getJson(url) {
  const response = await fetch(STATIC_SITE ? `${url}.json` : url);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function showStatus(today) {
  dataDate.textContent = today.data_date ? `Data as of ${today.data_date}` : "No data yet";
  banner.hidden = !today.warnings.length;
  banner.textContent = today.warnings.join(" ");
  if (STATIC_SITE) {
    refreshButton.hidden = true;
    if (today.data_date) dataDate.textContent += ". Updates on weekdays after 18:00 WIB";
    return;
  }
  refreshButton.disabled = today.refreshing;
  refreshButton.textContent = today.refreshing ? "Refreshing…" : "Refresh";
  if (today.refreshing) pollRefresh();
}

function setNav(active) {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === active);
  });
}

function pollRefresh() {
  if (polling) return;
  polling = true;
  const timer = setInterval(async () => {
    const { running } = await getJson("/api/refresh/status");
    if (running) return;
    clearInterval(timer);
    polling = false;
    route();
  }, 2000);
}

// Stop on the left, target on the right, the buy zone as a dark mark: lengths show downside and upside
function planBar(p) {
  const low = p.stop;
  const span = p.target - low || 1;
  const at = (value) => Math.max(0, Math.min(100, ((value - low) / span) * 100));
  const label = `Stop ${price(p.stop)}, buy ${price(p.entry_low)} to ${price(p.entry_high)}, target ${price(p.target)}`;
  return `<div class="plan" title="${label}" role="img" aria-label="${label}">
      <div class="plan-track">
        <span class="plan-risk" style="left:0;width:${at(p.entry_low).toFixed(1)}%"></span>
        <span class="plan-reward" style="left:${at(p.entry_high).toFixed(1)}%;right:0"></span>
        <span class="plan-entry" style="left:${at(p.entry_low).toFixed(1)}%;width:max(3px, ${(at(p.entry_high) - at(p.entry_low)).toFixed(1)}%)"></span>
      </div>
      <div class="plan-ends"><span>${signedPct(-p.downside)}</span><span>${signedPct(p.upside)}</span></div>
    </div>`;
}

function chanceBar(mc) {
  if (!mc) return DASH;
  const share = pct(mc.target_prob, 0);
  return `<div class="chance" title="Hits target ${share}, hits stop ${pct(mc.stop_prob, 0)}, neither ${pct(mc.neither_prob, 0)}">
      <div class="track"><div class="fill" style="width:${(mc.target_prob * 100).toFixed(1)}%"></div></div><span>${share}</span>
    </div>`;
}

function pickRows(picks) {
  return picks
    .map(
      (p) => `<tr data-href="#/stock/${esc(p.ticker)}">
        <td class="n">${p.rank}</td>
        <td><a class="tk" href="#/stock/${esc(p.ticker)}">${esc(p.ticker)}</a><span class="nm">${esc(p.name)}</span></td>
        <td>${tag(p.kind)}</td>
        <td>${planBar(p)}</td>
        <td class="n">${chanceBar(p.monte_carlo)}</td>
        <td>${esc(p.reason)}</td>
      </tr>`,
    )
    .join("");
}

const change = (logValue) => (missing(logValue) ? null : Math.exp(logValue) - 1);
const RECENT_WEEKS = 26;

// A line through 0-to-1 values, stretched to its box. The dashed line marks the threshold.
function sparkArea(values, threshold, label) {
  const last = values.length - 1 || 1;
  const points = values.map((value, i) => `${((i / last) * 100).toFixed(2)},${((1 - value) * 30).toFixed(2)}`);
  const mark = ((1 - threshold) * 30).toFixed(2);
  return `<svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="${esc(label)}">
      <path class="spark-area" d="M0,30 L${points.join(" L")} L100,30 Z"></path>
      <line class="spark-mark" x1="0" x2="100" y1="${mark}" y2="${mark}"></line>
      <path class="spark-line" d="M${points.join(" L")}"></path>
    </svg>`;
}

function marketPanel(regime, type) {
  if (!regime && !type) return "";
  const typeRow = type
    ? `<div class="mrow">
        <span class="mlabel">Market type${help("Market type")}</span>
        <div class="weeks">${type.history
          .slice(-RECENT_WEEKS)
          .map(([day, label]) => `<i class="mt-${esc(label.toLowerCase())}" title="Week of ${esc(day)}: ${esc(label)}"></i>`)
          .join("")}</div>
        <b><i class="swatch box mt-${esc(type.label.toLowerCase())}"></i>${esc(type.label)}</b>
      </div>`
    : "";
  const recent = regime ? regime.history.slice(-RECENT_WEEKS) : [];
  const regimeRow = regime
    ? `<div class="mrow" title="${recent.map(([day, , stress]) => `${day}: ${pct(stress, 0)}`).join("&#10;")}">
        <span class="mlabel">Stress${help("Stress probability")}</span>
        ${sparkArea(recent.map(([, , stress]) => stress), regime.threshold, `Stress probability over the last ${recent.length} weeks, now ${pct(regime.stress_prob, 0)}`)}
        <b>${pct(regime.stress_prob, 0)}, ${esc(regime.label.toLowerCase())}</b>
      </div>`
    : "";
  const since = type ? `${esc(type.label)} since ${esc(type.since)}. ` : "";
  return `<div class="market">${typeRow}${regimeRow}
      <p class="note">Last ${RECENT_WEEKS} weeks, oldest on the left. ${since}<a href="#/results">Full history</a></p>
    </div>`;
}

// The one sentence the Today screen answers, read before the table
function finding(today) {
  if (!today.data_date || !today.picks.length) return "";
  const counts = Object.keys(KINDS)
    .map((kind) => [kind, today.picks.filter((p) => p.kind === kind).length])
    .filter(([, count]) => count);
  const stocks = `${today.picks.length} ${today.picks.length === 1 ? "pick" : "picks"}`;
  const split =
    counts.length === 1
      ? `${stocks}, all ${KINDS[counts[0][0]].toLowerCase()}.`
      : `${stocks}: ${counts.map(([kind, count]) => `${count} ${KINDS[kind].toLowerCase()}`).join(", ")}.`;
  const missingKinds = Object.keys(KINDS).filter((kind) => !counts.some(([k]) => k === kind));
  const market = today.market_type ? today.market_type.label : today.regime && today.regime.label;
  const quiet =
    missingKinds.length && market
      ? ` No ${missingKinds.map((kind) => KINDS[kind].toLowerCase()).join(" or ")} setups while the market is in ${esc(market)}.`
      : "";
  return `<p class="finding">${split}${quiet}</p>`;
}

function renderToday(today) {
  const picks = today.picks.filter((p) => filter === "all" || p.kind === filter);
  const buttons = [["all", "All"], ...Object.entries(KINDS)]
    .map(([key, label]) => `<button type="button" data-filter="${key}" aria-pressed="${key === filter}">${label}</button>`)
    .join("");
  const noData = today.refreshing
    ? "Fetching market data for the first time. This takes a few minutes."
    : "No data yet. Press Refresh to fetch it.";
  const quiet = today.picks.length ? "No picks of this type today." : "No stock qualifies today. A quiet day is a valid result.";
  const body = picks.length
    ? `<div class="tablewrap"><table>
        <thead><tr><th class="n">#</th><th>Stock</th><th>Play</th><th>Stop, buy zone, target</th>
        <th class="n">Chance of target${help(ENDINGS, "chance of target")}</th><th>Why today</th></tr></thead>
        <tbody>${pickRows(picks)}</tbody></table></div>`
    : `<div class="empty">${today.data_date ? quiet : noData}</div>`;

  app.innerHTML = `<h1>Today's picks</h1>
    <p class="sub">Ranked by reward to risk after costs${help("Ranking", "ranking")}. Click a row for the full playbook.</p>
    ${finding(today)}
    ${marketPanel(today.regime, today.market_type)}
    <div class="filters">${buttons}</div>${body}`;

  app.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      filter = button.dataset.filter;
      renderToday(today);
    });
  });
  app.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", () => {
      location.hash = row.dataset.href;
    });
  });
}

function timeLimit(play) {
  if (play.kind === "long") return "Review after each annual report, and leave after 12 months at most";
  if (play.kind === "short") return "Walk away after 2 weeks";
  return `Walk away after ${play.days} trading days`;
}

function accuracyNote(kind, backtest) {
  const check = backtest && backtest.calibration && backtest.calibration[kind];
  if (kind === "pair" || !check || !check.samples) {
    return "These odds haven't been checked against past data.";
  }
  const scope = kind === "long" ? "the same price levels, without the factor score" : "past signals";
  return `Accuracy check on ${scope}: ${pct(check.mean_predicted, 0)} predicted, ${pct(check.mean_actual, 0)} happened, across ${check.samples.toLocaleString("en-US")} cases.`;
}

function oddsBlock(play, backtest) {
  const mc = play.monte_carlo;
  if (!mc) return "";
  const width = (value) => (value * 100).toFixed(1);
  return `<div class="odds">
    <h3>Monte Carlo odds${topicHelp("montecarlo", "Monte Carlo")}</h3>
    <div class="oddsbar" role="img" aria-label="Target ${pct(mc.target_prob, 0)}, neither ${pct(mc.neither_prob, 0)}, stop ${pct(mc.stop_prob, 0)}">
      <span class="o-target" style="width:${width(mc.target_prob)}%"></span>
      <span class="o-neither" style="width:${width(mc.neither_prob)}%"></span>
      <span class="o-stop" style="width:${width(mc.stop_prob)}%"></span>
    </div>
    <div class="metrics">
      ${metric("Hits target", pct(mc.target_prob, 0), ENDINGS, true)}
      ${metric("Hits stop", pct(mc.stop_prob, 0), ENDINGS)}
      ${metric("Neither in time", pct(mc.neither_prob, 0), ENDINGS)}
      ${metric("Average outcome", signedPct(mc.expected_return), "Average outcome and range")}
    </div>
    <p class="note">Most paths end between ${signedPct(mc.return_p10)} and ${signedPct(mc.return_p90)} after costs.
      Based on ${mc.paths.toLocaleString("en-US")} simulated paths over ${mc.days} trading days of this stock's past volatility, with its past trend removed.
      It shows how far the stock tends to move, not whether the signal works.</p>
    <p class="note">${accuracyNote(play.kind, backtest)}</p>
  </div>`;
}

function playBlock(play, backtest) {
  const pairNote =
    play.kind === "pair"
      ? `<p class="note">Only the cheap stock is bought, so this trade still carries market risk.</p>`
      : "";
  return `<div class="play">
    ${tag(play.kind)}${help(PLAY_HELP[play.kind])} <span class="note">${esc(play.reason)}</span>
    <ol class="steps">
      <li>Buy between ${price(play.entry_low)} and ${price(play.entry_high)}</li>
      <li>Take profit at ${price(play.target)} (${signedPct(play.upside)} after costs)</li>
      <li>Exit below ${price(play.stop)} (${signedPct(-play.downside)} after costs)</li>
      <li>${timeLimit(play)}</li>
    </ol>${pairNote}${oddsBlock(play, backtest)}</div>`;
}

function chartSection(play, index) {
  const mc = play.monte_carlo;
  if (!mc || !mc.chart) return "";
  const entry = (name, kind) => `<span class="key"><i class="swatch ${kind}"></i>${name}</span>`;
  return `<section class="panel full">
    <h2>${esc(KINDS[play.kind])}: simulated paths${help("The chart", "the chart")}</h2>
    <p class="note chartnote">${mc.chart.paths.length} of ${mc.paths.toLocaleString("en-US")} paths shown. Each line stops when the trade ends.
      The shaded band covers the middle 80% of all paths. For illustration only.</p>
    <div class="legend">
      ${entry("Reached target", "s-target")}${entry("Reached stop or ran out of time", "s-time")}
      ${entry("Middle 80%", "s-band")}${entry("Median", "s-median")}
    </div>
    <div class="mc-chart" data-index="${index}"></div>
  </section>`;
}

function niceTicks(low, high, count = 5) {
  const rough = (high - low) / count;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
  const ticks = [];
  for (let tick = Math.ceil(low / step) * step; tick <= high; tick += step) ticks.push(tick);
  return ticks;
}

function drawChart(holder, play) {
  const { chart } = play.monte_carlo;
  const width = holder.clientWidth;
  const height = 300;
  const margin = { top: 12, right: 104, bottom: 34, left: 58 };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const lastDay = chart.days[chart.days.length - 1];
  const entry = play.entry_high;
  const values = [play.stop, play.target, entry, ...chart.p10, ...chart.p90];
  const pad = (Math.max(...values) - Math.min(...values)) * 0.06;
  const low = Math.min(...values) - pad;
  const high = Math.max(...values) + pad;
  const x = (day) => margin.left + (day / lastDay) * (plotRight - margin.left);
  const y = (value) => margin.top + ((high - value) / (high - low)) * (plotBottom - margin.top);
  const line = (points) => points.map(([day, value], i) => `${i ? "L" : "M"}${x(day).toFixed(1)} ${y(value).toFixed(1)}`).join("");

  const upper = chart.days.map((day, i) => [day, chart.p90[i]]);
  const lower = chart.days.map((day, i) => [day, chart.p10[i]]).reverse();
  const grid = niceTicks(low, high)
    .map((tick) => `<line class="grid" x1="${margin.left}" x2="${plotRight}" y1="${y(tick)}" y2="${y(tick)}"></line>
      <text class="axis" x="${margin.left - 8}" y="${y(tick) + 4}" text-anchor="end">${price(tick)}</text>`)
    .join("");
  const days = niceTicks(0, lastDay, 4)
    .map((tick) => `<text class="axis" x="${x(tick)}" y="${plotBottom + 18}" text-anchor="middle">${tick}</text>`)
    .join("");
  const level = (name, value, kind) => `<line class="level ${kind}" x1="${margin.left}" x2="${plotRight}" y1="${y(value)}" y2="${y(value)}"></line>
    <text class="levelname" x="${plotRight + 8}" y="${y(value) + 4}">${name} ${price(value)}</text>`;
  const paths = chart.paths.map((path) => `<path class="path p-${path.outcome}" d="${line(path.points)}"></path>`).join("");
  const label = `Simulated price paths from ${price(entry)}, with a target of ${price(play.target)} and a stop of ${price(play.stop)}.`;

  holder.innerHTML = `<svg width="${width}" height="${height}" role="img" aria-label="${label}">
      ${grid}
      <path class="band" d="${line(upper)}${line(lower).replace("M", "L")}Z"></path>
      ${paths}
      <path class="median" d="${line(chart.days.map((day, i) => [day, chart.p50[i]]))}"></path>
      ${level("Target", play.target, "l-target")}${level("Entry", entry, "l-entry")}${level("Stop", play.stop, "l-stop")}
      ${days}
      <text class="axis" x="${(margin.left + plotRight) / 2}" y="${height - 2}" text-anchor="middle">Trading days after entry</text>
      <line class="cross" y1="${margin.top}" y2="${plotBottom}" visibility="hidden"></line>
      <rect class="hit" x="${margin.left}" y="${margin.top}" width="${Math.max(plotRight - margin.left, 0)}" height="${plotBottom - margin.top}"></rect>
    </svg><div class="tip" hidden></div>`;

  const cross = holder.querySelector(".cross");
  const tip = holder.querySelector(".tip");
  const hit = holder.querySelector(".hit");
  hit.addEventListener("pointermove", (event) => {
    const box = holder.getBoundingClientRect();
    const day = ((event.clientX - box.left - margin.left) / (plotRight - margin.left)) * lastDay;
    const nearest = chart.days.reduce((best, value, i) => (Math.abs(value - day) < Math.abs(chart.days[best] - day) ? i : best), 0);
    const left = x(chart.days[nearest]);
    cross.setAttribute("x1", left);
    cross.setAttribute("x2", left);
    cross.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.innerHTML = `<b>Day ${chart.days[nearest]}</b><br>Median ${price(chart.p50[nearest])}<br>
      Middle 80%: ${price(chart.p10[nearest])} to ${price(chart.p90[nearest])}`;
    tip.style.left = `${Math.min(left + 10, Math.max(width - 180, 0))}px`;
  });
  hit.addEventListener("pointerleave", () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  });
}

function drawRegimeChart(holder, regime) {
  const points = regime.history;
  const width = holder.clientWidth;
  const height = 260;
  const margin = { top: 12, right: 16, bottom: 28, left: 58 };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const closes = points.map((point) => point[1]);
  const pad = (Math.max(...closes) - Math.min(...closes)) * 0.06;
  const low = Math.min(...closes) - pad;
  const high = Math.max(...closes) + pad;
  const x = (i) => margin.left + (i / (points.length - 1)) * (plotRight - margin.left);
  const y = (value) => margin.top + ((high - value) / (high - low)) * (plotBottom - margin.top);

  const bands = points
    .map((point, i) => {
      if (point[2] <= regime.threshold) return "";
      const left = x(Math.max(i - 0.5, 0));
      const right = x(Math.min(i + 0.5, points.length - 1));
      return `<rect class="stress" x="${left}" y="${margin.top}" width="${right - left}" height="${plotBottom - margin.top}"></rect>`;
    })
    .join("");
  const grid = niceTicks(low, high, 4)
    .map((tick) => `<line class="grid" x1="${margin.left}" x2="${plotRight}" y1="${y(tick)}" y2="${y(tick)}"></line>
      <text class="axis" x="${margin.left - 8}" y="${y(tick) + 4}" text-anchor="end">${price(tick)}</text>`)
    .join("");
  const yearStep = width < 520 ? 2 : 1;
  const firstOfYear = points.flatMap((point, i) =>
    i && point[0].slice(0, 4) !== points[i - 1][0].slice(0, 4) ? [i] : [],
  );
  const years = firstOfYear
    .filter((_, i) => i % yearStep === 0)
    .map((i) => `<text class="axis" x="${x(i)}" y="${plotBottom + 18}" text-anchor="middle">${points[i][0].slice(0, 4)}</text>`)
    .join("");
  const line = points.map((point, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(point[1]).toFixed(1)}`).join("");

  holder.innerHTML = `<svg width="${width}" height="${height}" role="img" aria-label="IHSG index over time with stressed periods shaded">
      ${bands}${grid}<path class="ihsg" d="${line}"></path>${years}
      <line class="cross" y1="${margin.top}" y2="${plotBottom}" visibility="hidden"></line>
      <rect class="hit" x="${margin.left}" y="${margin.top}" width="${Math.max(plotRight - margin.left, 0)}" height="${plotBottom - margin.top}"></rect>
    </svg><div class="tip" hidden></div>`;

  const cross = holder.querySelector(".cross");
  const tip = holder.querySelector(".tip");
  const hit = holder.querySelector(".hit");
  hit.addEventListener("pointermove", (event) => {
    const box = holder.getBoundingClientRect();
    const share = (event.clientX - box.left - margin.left) / (plotRight - margin.left);
    const nearest = Math.max(0, Math.min(points.length - 1, Math.round(share * (points.length - 1))));
    const left = x(nearest);
    cross.setAttribute("x1", left);
    cross.setAttribute("x2", left);
    cross.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.innerHTML = `<b>${points[nearest][0]}</b><br>IHSG ${price(points[nearest][1])}<br>Stress ${pct(points[nearest][2], 0)}`;
    tip.style.left = `${Math.min(left + 10, Math.max(width - 130, 0))}px`;
  });
  hit.addEventListener("pointerleave", () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  });
}

function drawTypeStrip(holder, type) {
  const weeks = type.history;
  const width = holder.clientWidth;
  const height = 70;
  const stripHeight = 36;
  const cell = width / weeks.length;
  const cells = weeks
    .map(([, label], i) => `<rect class="mt-${label.toLowerCase()}" x="${(i * cell).toFixed(2)}" y="0" width="${(cell + 0.5).toFixed(2)}" height="${stripHeight}"></rect>`)
    .join("");
  const yearStep = width < 520 ? 2 : 1;
  const starts = weeks.flatMap(([day], i) => (i && day.slice(0, 4) !== weeks[i - 1][0].slice(0, 4) ? [i] : []));
  const years = starts
    .filter((_, i) => i % yearStep === 0)
    .map((i) => `<text class="axis" x="${i * cell}" y="${stripHeight + 18}" text-anchor="middle">${weeks[i][0].slice(0, 4)}</text>`)
    .join("");
  holder.innerHTML = `<svg width="${width}" height="${height}" role="img" aria-label="Market type for each week. The table below lists them.">
      ${cells}${years}
      <line class="cross" y1="0" y2="${stripHeight}" visibility="hidden"></line>
      <rect class="hit" x="0" y="0" width="${width}" height="${stripHeight}"></rect>
    </svg><div class="tip" hidden></div>`;

  const cross = holder.querySelector(".cross");
  const tip = holder.querySelector(".tip");
  const hit = holder.querySelector(".hit");
  hit.addEventListener("pointermove", (event) => {
    const box = holder.getBoundingClientRect();
    const nearest = Math.max(0, Math.min(weeks.length - 1, Math.floor((event.clientX - box.left) / cell)));
    const left = (nearest + 0.5) * cell;
    cross.setAttribute("x1", left);
    cross.setAttribute("x2", left);
    cross.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.innerHTML = `<b>${weeks[nearest][0]}</b><br>${esc(weeks[nearest][1])}`;
    tip.style.left = `${Math.min(left + 10, Math.max(width - 110, 0))}px`;
  });
  hit.addEventListener("pointerleave", () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  });
}

function drawCharts() {
  app.querySelectorAll(".mc-chart[data-index]").forEach((holder) => drawChart(holder, chartPlays[holder.dataset.index]));
  const holder = app.querySelector(".regime-chart");
  if (holder && regimeData) drawRegimeChart(holder, regimeData);
  const strip = app.querySelector(".type-chart");
  if (strip && marketTypeData) drawTypeStrip(strip, marketTypeData);
  const equity = app.querySelector(".equity-chart");
  if (equity && equityData) drawEquityChart(equity, equityData);
}

// Grey label above its figure; the answer figure is drawn larger than its siblings
function metric(label, value, helpKey, answer = false) {
  return `<div class="metric${answer ? " answer" : ""}"><span>${label}${helpKey ? help(helpKey, label) : ""}</span><b>${value}</b></div>`;
}

function bar(label, value) {
  const width = missing(value) ? 0 : value;
  return `<div class="bar"><span>${label}${help(label)}</span><div class="track"><div class="fill" style="width:${width}%"></div></div>
    <span>${missing(value) ? DASH : Math.round(value)}</span></div>`;
}

function performance(kinds, backtest) {
  if (!backtest) return `<p class="note">No backtest yet.</p>`;
  const lines = [...new Set(kinds)].map((kind) => {
    if (kind === "long") {
      return `<p class="note">Long term: not backtested. Free data has too little financial history to test value and quality.</p>`;
    }
    const result = backtest[kind];
    return `<p class="note">${KINDS[kind]}: ${result.trades} past trades, ${pct(result.win_rate, 0)} winners,
      ${signedPct(result.avg_return)} average after costs.</p>`;
  });
  return lines.join("");
}

const GAP_LIMIT = 4;

// The gap over recent days, clipped to ±4σ, with the entry level dashed on both sides
function gapSpark(history) {
  if (!history || history.length < 2) return DASH;
  const entry = Math.abs(settings ? settings.z_active : 2);
  const y = (gap) => (((GAP_LIMIT - Math.max(-GAP_LIMIT, Math.min(GAP_LIMIT, gap))) / (2 * GAP_LIMIT)) * 30).toFixed(2);
  const last = history.length - 1;
  const points = history.map((gap, i) => `${((i / last) * 100).toFixed(2)},${y(gap)}`).join(" L");
  const label = `Gap over the last ${history.length} trading days, from ${history[0].toFixed(1)}σ to ${history[last].toFixed(1)}σ`;
  return `<svg class="spark gap" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="${label}">
      <title>${label}</title>
      <line class="spark-zero" x1="0" x2="100" y1="15" y2="15"></line>
      <line class="spark-mark" x1="0" x2="100" y1="${y(entry)}" y2="${y(entry)}"></line>
      <line class="spark-mark" x1="0" x2="100" y1="${y(-entry)}" y2="${y(-entry)}"></line>
      <path class="spark-line" d="M${points}"></path>
    </svg>`;
}

function pairRows(pairs) {
  return pairs
    .map(
      (p) => `<tr>
        <td><a class="tk" href="#/stock/${esc(p.with)}">${esc(p.with)}</a></td>
        <td class="sparkcell">${gapSpark(p.gap_history)}</td>
        <td class="n">${p.gap.toFixed(1)}σ ${p.gap < 0 ? "cheap" : "rich"}</td>
        <td class="n">~${Math.round(p.half_life)} days</td>
        <td>${esc(p.status)}</td>
      </tr>`,
    )
    .join("");
}

function renderStock(stock, today) {
  const v = stock.valuation;
  const plays = stock.plays.length
    ? stock.plays.map((play) => playBlock(play, today.backtest)).join("")
    : `<p class="note">No play for this stock today.</p>`;
  const dated = v.as_of
    ? `Financials from ${esc(v.as_of)}${v.stale ? ", which is out of date" : ""}.`
    : "No financial data available.";
  const pairs = stock.pairs.length
    ? `<table><thead><tr><th>Paired with</th><th>Gap, last ${settings ? settings.z_window : 60} days</th><th class="n">Gap now${help("Gap", "gap")}</th>
        <th class="n">Half-life${help("Half-life")}</th><th>Signal${help("Signal")}</th></tr></thead>
        <tbody>${pairRows(stock.pairs)}</tbody></table>`
    : `<p class="note" style="padding:0 16px 16px">No statistically sound pair today.</p>`;

  app.innerHTML = `<div class="head">
      <div><h1>${esc(stock.ticker)} <span class="sub">${esc(stock.name)}</span></h1>
      <span class="note">${esc(stock.sector)}</span></div>
      <div class="price">Rp ${price(stock.close)}</div>
    </div>
    <div class="grid">
      <section class="panel full"><h2>The playbook${topicHelp("picks", "how picks are chosen")}</h2>${plays}
        ${performance(stock.plays.map((p) => p.kind), today.backtest)}</section>
      <section class="panel full factors"><h2>Factor scores${topicHelp("factors", "factor scores")}</h2>
        ${bar("Combined score", stock.scores.composite)}
        ${bar("Value", stock.scores.value)}${bar("Quality", stock.scores.quality)}
        ${bar("Momentum", stock.scores.momentum)}${bar("Size", stock.scores.size)}
        <p class="note">0 to 100 against the stock list. Size is shown for information and isn't in the combined score.</p>
      </section>
      ${valuationDetails(stock, dated, today)}
      ${yearlyHistory(stock)}
      ${stock.plays.map(chartSection).join("")}
      <section class="panel flat full"><h2>Statistical arbitrage with other stocks${topicHelp("arbitrage", "statistical arbitrage")}</h2>${pairs}</section>
    </div>`;
  chartPlays = stock.plays;
  drawCharts();
}

function detailTable(title, rows, withSector = false) {
  const head = withSector ? `<th class="n">Stock</th><th class="n">Sector</th>` : `<th class="n">Stock</th>`;
  const body = rows
    .map(([label, key, value, sector]) => `<tr><td>${label}${help(key, label)}</td><td class="n">${value}</td>
      ${withSector ? `<td class="n">${sector}</td>` : ""}</tr>`)
    .join("");
  return `<div class="detail"><table><thead><tr><th>${title}</th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

const PEER_MEASURES = [
  ["PE", "PE (price to earnings)", "pe", times, true, "Cheaper", "Pricier"],
  ["PBV", "PBV (price to book value)", "pbv", times, true, "Cheaper", "Pricier"],
  ["Dividend yield", "Dividend yield", "dividend_yield", pct, false, "Lower", "Higher"],
  ["ROE", "ROE (return on equity)", "roe", pct, false, "Lower", "Higher"],
];

const quantile = (sorted, share) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(share * (sorted.length - 1))))];

// Each sector peer is a grey dot, the median a dark line, and this stock the blue dot
function peerStrip(stock, peers, [label, helpKey, field, format, ratioScale, lowWord, highWord]) {
  const usable = (value) => !missing(value) && Number.isFinite(value) && (!ratioScale || value > 0);
  const own = stock.valuation[field];
  const others = peers.filter((peer) => usable(peer.valuation[field]));
  if (!usable(own) || others.length < 2) return "";
  const values = [own, ...others.map((peer) => peer.valuation[field])].sort((a, b) => a - b);
  const scale = ratioScale ? Math.log : (value) => value;
  // The middle 90% sets the scale, so one extreme peer doesn't squash the rest; outliers sit on the edges
  const low = scale(values.length >= 8 ? quantile(values, 0.05) : values[0]);
  const high = scale(values.length >= 8 ? quantile(values, 0.95) : values[values.length - 1]);
  const at = (value) => (high === low ? 50 : Math.max(0, Math.min(100, ((scale(value) - low) / (high - low)) * 100))).toFixed(1);
  const median = stock.sector_medians[field];
  const dots = others
    .map((peer) => `<i class="peer" style="left:${at(peer.valuation[field])}%" title="${esc(peer.ticker)} ${format(peer.valuation[field])}"></i>`)
    .join("");
  const medianMark = usable(median) ? `<i class="median-mark" style="left:${at(median)}%" title="Sector median ${format(median)}"></i>` : "";
  return `<div class="peerrow">
      <span class="mlabel">${label}${help(helpKey, label)}</span>
      <div class="strip" role="img" aria-label="${label} ${format(own)} against ${others.length} sector peers, median ${format(median)}">
        <div class="strip-line"></div>${dots}${medianMark}
        <i class="own" style="left:${at(own)}%" title="${esc(stock.ticker)} ${format(own)}"></i>
        <span class="strip-end">${lowWord}</span><span class="strip-end right">${highWord}</span>
      </div>
      <b>${format(own)}</b>
    </div>`;
}

function peerStrips(stock, today) {
  const peers = Object.values((today && today.stocks) || {}).filter(
    (peer) => peer.sector === stock.sector && peer.ticker !== stock.ticker && peer.valuation,
  );
  const rows = PEER_MEASURES.map((measure) => peerStrip(stock, peers, measure)).join("");
  if (!rows) return "";
  return `<div class="peers">${rows}
      <p class="note">Against ${peers.length} other ${esc(stock.sector)} stocks. Grey dots are peers, the upright line is the sector median and blue is ${esc(stock.ticker)}. Hover a dot for its figure.</p>
    </div>`;
}

function valuationDetails(stock, dated, today) {
  const v = stock.valuation;
  const m = stock.sector_medians;
  const row = (label, key, format, field) => [label, key, format(v[field]), format(m[field])];
  const prices = [
    row("PE", "PE (price to earnings)", times, "pe"),
    row("PBV", "PBV (price to book value)", times, "pbv"),
    row("P/S", "P/S (price to sales)", times, "ps"),
    row("EV/EBITDA", "EV/EBITDA", times, "ev_ebitda"),
    row("Earnings yield", "Earnings yield", pct, "earnings_yield"),
    row("Free cash flow yield", "Free cash flow yield", pct, "fcf_yield"),
    row("Dividend yield", "Dividend yield", pct, "dividend_yield"),
  ];
  const profit = [
    row("Gross margin", "Margins", pct, "gross_margin"),
    row("Operating margin", "Margins", pct, "operating_margin"),
    row("Net margin", "Margins", pct, "net_margin"),
    row("ROE", "ROE (return on equity)", pct, "roe"),
    row("ROA", "ROA (return on assets)", pct, "roa"),
  ];
  const growth = [
    ["Revenue, latest year", "Growth", signedPct(v.revenue_growth)],
    ["EPS, latest year", "Growth", signedPct(v.eps_growth)],
    ["EPS per year", "Growth", signedPct(v.eps_cagr)],
  ];
  const health = [
    ["Debt to equity", "Market cap and debt to equity", times(v.debt_to_equity)],
    ["Net debt to EBITDA", "Net debt to EBITDA", times(v.net_debt_ebitda)],
    ["Current ratio", "Current ratio", times(v.current_ratio)],
    ["Interest cover", "Interest cover", times(v.interest_cover)],
  ];
  const perShare = [
    ["Earnings", "PE (price to earnings)", rupiah(v.eps_idr)],
    ["Book value", "PBV (price to book value)", rupiah(v.book_value_per_share)],
    ["Dividends, last year", "Dividend yield", rupiah(v.dividend_per_share)],
    ["Payout ratio", "Payout ratio", pct(v.payout_ratio, 0)],
    ["Graham value", "Graham value", rupiah(v.graham_value)],
    ["Market cap", "Market cap and debt to equity", money(v.market_cap)],
  ];
  return `<section class="panel full"><h2>Valuation${topicHelp("valuation", "valuation")}</h2>
    ${peerStrips(stock, today)}
    <details class="more"><summary>All valuation figures</summary>
    <div class="detailgrid">
      ${detailTable("Price", prices, true)}${detailTable("Profitability", profit, true)}
      ${detailTable("Per share and size", perShare)}${detailTable("Financial health", health)}
      ${detailTable("Growth", growth)}
    </div>
    <p class="note">The sector column is the median of the stock's peers${help("Sector median")}. A dash means the figure is missing or doesn't apply to this company.</p>
    </details>
    <p class="note">${dated}</p>
  </section>`;
}

function yearlyHistory(stock) {
  const years = (stock.years || []).slice().reverse();
  if (!years.length) return "";
  const rows = years
    .map((y) => `<tr><td>${esc(y.year)}</td><td class="n">${price(y.price)}</td><td class="n">${rupiah(y.eps)}</td><td class="n">${times(y.pe)}</td>
      <td class="n">${times(y.pbv)}</td><td class="n">${pct(y.roe, 0)}</td><td class="n">${pct(y.net_margin)}</td>
      <td class="n">${money(y.revenue)}</td><td class="n">${money(y.net_income)}</td></tr>`)
    .join("");
  return `<section class="panel flat full"><h2>Yearly history${help("Yearly history", "yearly history")}</h2>
    <table><thead><tr><th>Year</th><th class="n">Price</th><th class="n">EPS</th><th class="n">PE</th><th class="n">PBV</th>
    <th class="n">ROE</th><th class="n">Net margin</th><th class="n">Revenue</th><th class="n">Net income</th></tr></thead><tbody>${rows}</tbody></table>
  </section>`;
}

function winBar(share) {
  if (missing(share)) return DASH;
  return `<div class="chance" title="${pct(share, 0)} of trades made money after costs">
      <div class="track"><div class="fill" style="width:${(share * 100).toFixed(1)}%"></div></div><span>${pct(share, 0)}</span>
    </div>`;
}

function resultRow(label, result) {
  if (!result) return `<tr><td>${label}</td><td class="n">${DASH}</td><td class="n">${DASH}</td><td class="n">${DASH}</td><td class="n">${DASH}</td></tr>`;
  return `<tr><td>${label}</td><td class="n">${result.trades}</td><td class="n">${winBar(result.win_rate)}</td>
    <td class="n">${signedPct(result.avg_return)}</td><td class="n">${signedPct(result.max_drawdown)}</td></tr>`;
}

function calibrationRows(label, check) {
  if (!check || !check.samples) return `<tr><td>${label}</td><td colspan="3">Not enough past cases</td></tr>`;
  return check.buckets
    .map(
      (b) => `<tr><td>${label}</td><td>${pct(b.low, 0)} to ${pct(b.high, 0)}</td>
        <td class="n">${b.count.toLocaleString("en-US")}</td>
        <td class="n">${pct(b.predicted, 0)}</td><td class="n">${pct(b.actual, 0)}</td></tr>`,
    )
    .join("");
}

function calibrationPanel(calibration) {
  if (!calibration) return "";
  return `<section class="panel flat full"><h2>Monte Carlo accuracy check${help("Accuracy check", "the accuracy check")}</h2>
    <table><thead><tr><th>Play</th><th>Predicted odds of hitting target</th><th class="n">Past cases</th><th class="n">Predicted</th><th class="n">Actually hit</th></tr></thead>
    <tbody>${calibrationRows("Short term", calibration.short)}${calibrationRows("Long term price levels", calibration.long)}
    <tr><td>Pair trade</td><td colspan="4">Not checked: too few past trades</td></tr></tbody></table>
    <p class="note" style="padding:0 16px 16px">Each past prediction used only the data available at that date, and the two right-hand columns should be close.
    The long-term row tests the +${pct(calibration.long.target, 0)} and -${pct(calibration.long.stop, 0)} levels on every stock each quarter, not the factor score, and its cases overlap in time.</p>
  </section>`;
}

function regimeRows(label, split) {
  if (!split) return "";
  return ["calm", "stressed"]
    .map((state) => {
      const r = split[state];
      return `<tr><td>${label}</td><td>${state === "calm" ? "Calm" : "Stressed"}</td><td class="n">${r.trades}</td>
        <td class="n">${pct(r.win_rate, 0)}</td><td class="n">${signedPct(r.avg_return)}</td><td class="n">${signedPct(r.max_drawdown)}</td></tr>`;
    })
    .join("");
}

const EQUITY_LINES = [
  ["short", "Short term", "e-short"],
  ["pair", "Pair trade", "e-pair"],
  ["momentum", "Momentum", "e-momentum"],
];

function equityPanel(equity) {
  if (!equity || !EQUITY_LINES.some(([key]) => (equity[key] || []).length > 1)) return "";
  const key = (name, kind) => `<span class="key"><i class="swatch ${kind}"></i>${name}</span>`;
  return `<section class="panel full"><h2>Growth of Rp 1 in the backtest${help("Backtest")}</h2>
      <p class="note chartnote">Each month's average trade is compounded, so overlapping trades count once. Log scale: equal steps are equal percentage moves.</p>
      <div class="legend">${EQUITY_LINES.map(([, name, kind]) => key(name, kind)).join("")}</div>
      <div class="mc-chart equity-chart"></div>
    </section>`;
}

function drawEquityChart(holder, equity) {
  const series = EQUITY_LINES.map(([field, name, kind]) => [name, kind, equity[field] || []]).filter(([, , points]) => points.length > 1);
  const months = [...new Set(series.flatMap(([, , points]) => points.map(([month]) => month)))].sort();
  const width = holder.clientWidth;
  const height = 260;
  const margin = { top: 12, right: 16, bottom: 28, left: 52 };
  const plotRight = width - margin.right;
  const plotBottom = height - margin.bottom;
  const values = [1, ...series.flatMap(([, , points]) => points.map(([, value]) => value))].filter((value) => value > 0);
  const low = Math.log(Math.min(...values) * 0.95);
  const high = Math.log(Math.max(...values) * 1.05);
  const index = new Map(months.map((month, i) => [month, i]));
  const x = (i) => margin.left + (i / Math.max(months.length - 1, 1)) * (plotRight - margin.left);
  const y = (value) => margin.top + ((high - Math.log(Math.max(value, 1e-6))) / (high - low)) * (plotBottom - margin.top);
  // Doubling steps, so the gridlines are evenly spaced on the log scale
  const ticks = [0.125, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64].filter((tick) => Math.log(tick) >= low && Math.log(tick) <= high);
  const grid = ticks
    .map((tick) => `<line class="grid${tick === 1 ? " base" : ""}" x1="${margin.left}" x2="${plotRight}" y1="${y(tick)}" y2="${y(tick)}"></line>
      <text class="axis" x="${margin.left - 8}" y="${y(tick) + 4}" text-anchor="end">${tick}x</text>`)
    .join("");
  const yearStep = width < 520 ? 2 : 1;
  const years = months
    .flatMap((month, i) => (i && month.slice(0, 4) !== months[i - 1].slice(0, 4) ? [i] : []))
    .filter((_, i) => i % yearStep === 0)
    .map((i) => `<text class="axis" x="${x(i)}" y="${plotBottom + 18}" text-anchor="middle">${months[i].slice(0, 4)}</text>`)
    .join("");
  const lines = series
    .map(([, kind, points]) => `<path class="equity ${kind}" d="${points
      .map(([month, value], i) => `${i ? "L" : "M"}${x(index.get(month)).toFixed(1)} ${y(value).toFixed(1)}`)
      .join("")}"></path>`)
    .join("");
  holder.innerHTML = `<svg width="${width}" height="${height}" role="img" aria-label="Growth of Rp 1 for each backtested signal over time">
      ${grid}${lines}${years}
      <line class="cross" y1="${margin.top}" y2="${plotBottom}" visibility="hidden"></line>
      <rect class="hit" x="${margin.left}" y="${margin.top}" width="${Math.max(plotRight - margin.left, 0)}" height="${plotBottom - margin.top}"></rect>
    </svg><div class="tip" hidden></div>`;

  const lookup = series.map(([name, , points]) => [name, new Map(points)]);
  const cross = holder.querySelector(".cross");
  const tip = holder.querySelector(".tip");
  const hit = holder.querySelector(".hit");
  hit.addEventListener("pointermove", (event) => {
    const box = holder.getBoundingClientRect();
    const share = (event.clientX - box.left - margin.left) / (plotRight - margin.left);
    const nearest = Math.max(0, Math.min(months.length - 1, Math.round(share * (months.length - 1))));
    const month = months[nearest];
    const left = x(nearest);
    cross.setAttribute("x1", left);
    cross.setAttribute("x2", left);
    cross.setAttribute("visibility", "visible");
    tip.hidden = false;
    // Each line shows its latest value up to this month, since signals don't trade every month
    const rows = lookup.map(([name, points]) => {
      const seen = [...points.keys()].filter((m) => m <= month);
      return seen.length ? `${name} ${points.get(seen[seen.length - 1]).toFixed(2)}x` : `${name} ${DASH}`;
    });
    tip.innerHTML = `<b>${month}</b><br>${rows.join("<br>")}`;
    tip.style.left = `${Math.min(left + 10, Math.max(width - 160, 0))}px`;
  });
  hit.addEventListener("pointerleave", () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  });
}

const OUTCOME_ORDER = [
  ["Target hit", "o-target"],
  ["Stop hit", "o-stop"],
  ["Time limit", "o-neither"],
  ["Open", "o-open"],
];

function recordSummary(record) {
  if (!record.length) return "";
  const counts = OUTCOME_ORDER.map(([outcome, kind]) => [outcome, kind, record.filter((r) => r.outcome === outcome).length]).filter(
    ([, , count]) => count,
  );
  const keys = counts.map(([outcome, kind, count]) => `<span class="key"><i class="swatch box ${kind}"></i>${outcome} ${count}</span>`).join("");
  return `<div class="recordbar">
      <div class="oddsbar" role="img" aria-label="${counts.map(([outcome, , count]) => `${outcome} ${count}`).join(", ")}">
        ${counts.map(([, kind, count]) => `<span class="${kind}" style="width:${((count / record.length) * 100).toFixed(1)}%"></span>`).join("")}
      </div>
      <div class="legend">${keys}</div>
    </div>`;
}

function regimePanels(regime, splits) {
  if (!regime) return "";
  const key = (name, kind) => `<span class="key"><i class="swatch ${kind}"></i>${name}</span>`;
  const table = splits
    ? `<section class="panel flat full"><h2>Signals by market regime${help("Signals by market regime")}</h2>
        <table><thead><tr><th>Signal</th><th>Market</th><th class="n">Trades</th><th class="n">Winners</th><th class="n">Average</th><th class="n">Worst drawdown</th></tr></thead>
        <tbody>${regimeRows("Short term", splits.short)}${regimeRows("Pair trade", splits.pair)}${regimeRows("Momentum, per month held", splits.momentum)}</tbody></table>
        <p class="note" style="padding:0 16px 16px">Each trade is labelled by the state known on its signal day. The earliest years are left out, because the model needs 2 years of data to start.</p>
      </section>`
    : "";
  return `<section class="panel full"><h2>Market regime history${help("Market regime")}</h2>
      <p class="note chartnote">Now ${esc(regime.label.toLowerCase())}. Calm spells have lasted about ${Math.round(regime.calm_days)} trading days, and stressed spells about ${Math.round(regime.stressed_days)}. The market was stressed on ${pct(regime.stressed_share, 0)} of days.</p>
      <div class="legend">${key("IHSG", "s-ihsg")}${key("Stressed", "s-stress")}</div>
      <div class="mc-chart regime-chart"></div>
    </section>${table}`;
}

function typeRows(signal, split) {
  return MARKET_TYPES.filter((label) => split && split[label])
    .map((label) => {
      const r = split[label];
      const measured = r.trades >= settings.cluster_min_trades;
      const results = measured
        ? `<td class="n">${pct(r.win_rate, 0)}</td><td class="n">${signedPct(r.avg_return)}</td>`
        : `<td colspan="2" class="n">Too few trades</td>`;
      return `<tr><td>${signal}</td><td>${label}</td><td class="n">${r.trades}</td>${results}</tr>`;
    })
    .join("");
}

function marketTypePanels(type, splits) {
  if (!type) return "";
  const key = (label) => `<span class="key"><i class="swatch box mt-${label.toLowerCase()}"></i>${label}</span>`;
  const present = MARKET_TYPES.filter((label) => type.groups.some((group) => group.label === label));
  const groups = present
    .map((label) => type.groups.find((group) => group.label === label))
    .map((g) => `<tr><td>${esc(g.label)}</td><td class="n">${g.weeks}</td><td class="n">${pct(g.share, 0)}</td>
      <td class="n">${signedPct(change(g.ret))}</td><td class="n">${pct(g.vol, 0)}</td><td class="n">${pct(g.breadth, 0)}</td>
      <td class="n">${signedPct(change(g.rupiah))}</td><td class="n">${g.corr.toFixed(2)}</td></tr>`)
    .join("");
  const signals = splits
    ? `<section class="panel flat full"><h2>Signals by market type${help("Signals by market type")}</h2>
        <table><thead><tr><th>Signal</th><th>Market type</th><th class="n">Trades</th><th class="n">Winners</th><th class="n">Average</th></tr></thead>
        <tbody>${typeRows("Short term", splits.short)}${typeRows("Pair trade", splits.pair)}${typeRows("Momentum, per month held", splits.momentum)}</tbody></table>
        <p class="note" style="padding:0 16px 16px">Results with fewer than ${settings.cluster_min_trades} trades are hidden, because they'd mostly be noise. Market types are for information and don't change the picks.</p>
      </section>`
    : "";
  return `<section class="panel full"><h2>Market type history${help("Market type")}</h2>
      <p class="note chartnote">Now ${esc(type.label)}. Each stripe is one week, judged using only earlier weeks.</p>
      <div class="legend">${present.map(key).join("")}</div>
      <div class="mc-chart type-chart"></div>
    </section>
    <section class="panel flat full"><h2>What each market type looks like${help("Market type measures")}</h2>
      <table><thead><tr><th>Market type</th><th class="n">Weeks</th><th class="n">Share</th><th class="n">IHSG, 21 days</th><th class="n">Volatility</th>
      <th class="n">Above 50-day</th><th class="n">USD/IDR, 21 days</th><th class="n">Correlation</th></tr></thead><tbody>${groups}</tbody></table>
    </section>${signals}`;
}

function renderResults(results) {
  const backtest = results.backtest || {};
  const tested = results.backtest_at ? `Tested ${esc(results.backtest_at)}, on up to 10 years of prices. ` : "";
  const newest = results.track_record.slice().reverse();
  const shown = showAllRecord ? newest : newest.slice(0, RECORD_ROWS);
  const viewAll =
    newest.length > RECORD_ROWS && !showAllRecord
      ? `<p class="note" style="padding:0 16px 16px">Showing ${RECORD_ROWS} of ${newest.length.toLocaleString("en-US")}.
          <button type="button" class="textbutton" data-view-all>View all</button></p>`
      : "";
  const record = newest.length
    ? `<table><thead><tr><th>Picked</th><th>Stock</th><th>Play</th><th class="n">Entry</th><th>Outcome</th><th class="n">Return</th></tr></thead>
        <tbody>${shown
          .map(
            (r) => `<tr><td>${esc(r.picked_on)}</td><td class="tk">${esc(r.ticker)}</td><td>${tag(r.kind)}</td>
              <td class="n">${price(r.entry)}</td><td>${esc(r.outcome)}</td><td class="n">${signedPct(r.return)}</td></tr>`,
          )
          .join("")}</tbody></table>${viewAll}`
    : `<p class="note" style="padding:0 16px 16px">Picks are saved each day, and their real outcomes will appear here.</p>`;
  const reasons = [...new Set(results.skipped.map((s) => s.reason))];
  const skipped = results.skipped.length
    ? `<p class="note">Left out of the latest run, ${results.skipped.length} stocks. ${reasons
        .map((reason) => `${esc(reason)}: ${results.skipped.filter((s) => s.reason === reason).map((s) => esc(s.ticker)).join(", ")}.`)
        .join(" ")}</p>`
    : "";

  app.innerHTML = `<h1>Results</h1>
    <p class="sub">How each kind of signal did in past data, and how real picks turned out.</p>
    <div class="grid">
      <section class="panel flat full"><h2>Backtest, after costs${help("Backtest")}</h2>
        <table><thead><tr><th>Signal</th><th class="n">Trades</th><th class="n">Winners</th><th class="n">Average</th><th class="n">Worst drawdown</th></tr></thead>
        <tbody>${resultRow("Short term", backtest.short)}${resultRow("Pair trade, buying the cheap stock only", backtest.pair)}
        ${resultRow("Momentum, per month held", backtest.momentum)}
        <tr><td>Long term, value and quality</td><td colspan="4">Not backtested: free data has too little financial history</td></tr></tbody></table>
        <p class="note" style="padding:0 16px 16px">${tested}The stock list is today's index members, which flatters past results because
        companies that collapsed aren't in it. Drawdown compounds each month's average trade. Past results don't predict future ones.</p>
      </section>
      ${equityPanel(backtest.equity)}
      ${regimePanels(results.regime, backtest.regimes)}
      ${marketTypePanels(results.market_type, backtest.market_types)}
      ${calibrationPanel(backtest.calibration)}
      <section class="panel flat full"><h2>Track record of real picks</h2>${recordSummary(results.track_record)}${record}</section>
    </div>${skipped}`;
  app.querySelector("[data-view-all]")?.addEventListener("click", () => {
    showAllRecord = true;
    renderResults(results);
  });
  regimeData = results.regime;
  marketTypeData = results.market_type;
  equityData = backtest.equity;
  drawCharts();
}

function helpContent(key) {
  if (key.startsWith("topic:")) {
    const topic = helpTopics.find((item) => item.id === key.slice(6));
    return `<h4>${topic.title}</h4><p>${topic.intro}</p><a href="#/how/${topic.id}">Read the full explanation</a>`;
  }
  for (const topic of helpTopics) {
    const item = topic.items.find((entry) => entry.name === key);
    if (item) {
      return `<h4>${item.name}</h4><p>${item.means}</p><pre>${item.formula}</pre>
        <p><b>How to read it:</b> ${item.read}</p><p><b>Watch out:</b> ${item.caution}</p>
        <a href="#/how/${topic.id}">Read more</a>`;
    }
  }
  return "";
}

function hideHelp() {
  clearTimeout(helpTimer);
  helpBox.hidden = true;
}

function showHelp(button) {
  clearTimeout(helpTimer);
  const content = helpTopics.length ? helpContent(button.dataset.help) : "";
  if (!content) return;
  helpBox.innerHTML = content;
  helpBox.hidden = false;
  const gap = 8;
  const anchor = button.getBoundingClientRect();
  const box = helpBox.getBoundingClientRect();
  const left = Math.max(gap, Math.min(anchor.left, window.innerWidth - box.width - gap));
  const below = anchor.bottom + gap;
  const top = below + box.height <= window.innerHeight ? below : Math.max(gap, anchor.top - box.height - gap);
  helpBox.style.left = `${left}px`;
  helpBox.style.top = `${top}px`;
}

function hideHelpSoon() {
  clearTimeout(helpTimer);
  helpTimer = setTimeout(hideHelp, HELP_HIDE_DELAY);
}

const helpButton = (event) => event.target.closest?.(".help");

document.addEventListener("pointerover", (event) => {
  if (event.pointerType !== "touch" && helpButton(event)) showHelp(helpButton(event));
  else if (helpBox.contains(event.target)) clearTimeout(helpTimer);
});
document.addEventListener("pointerout", (event) => {
  if (event.pointerType !== "touch" && (helpButton(event) || helpBox.contains(event.target))) hideHelpSoon();
});
document.addEventListener("focusin", (event) => {
  if (helpButton(event)) showHelp(helpButton(event));
});
document.addEventListener("focusout", (event) => {
  if (helpButton(event)) hideHelpSoon();
});
document.addEventListener("click", (event) => {
  if (helpButton(event)) {
    event.stopPropagation();
    showHelp(helpButton(event));
  } else if (!helpBox.contains(event.target)) {
    hideHelp();
  }
}, true);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideHelp();
});
window.addEventListener("scroll", hideHelp, { passive: true });

// The page's final shape in flat grey, shown while data loads. No shimmer.
function placeholder() {
  const rows = Array.from({ length: 6 }, () => `<div class="sk sk-row"></div>`).join("");
  return `<div class="sk sk-title"></div><div class="sk sk-line"></div><div class="panel sk-panel">${rows}</div>`;
}

function loadError() {
  const when = lastDataDate ? ` The last data loaded was from ${esc(lastDataDate)}.` : "";
  return `<div class="empty">Couldn't load this page.${when}
    <button type="button" class="textbutton" data-retry>Retry</button></div>`;
}

async function route() {
  const hash = location.hash || "#/";
  hideHelp();
  if (!hash.startsWith("#/results")) showAllRecord = false;
  const waiting = setTimeout(() => {
    app.innerHTML = placeholder();
  }, LOADING_DELAY);
  try {
    if (!helpTopics.length) {
      settings = await getJson("/api/methods");
      helpTopics = methodTopics(settings);
    }
    const today = await getJson("/api/today");
    lastDataDate = today.data_date;
    showStatus(today);
    const match = hash.match(/^#\/stock\/(.+)$/);
    const how = hash.match(/^#\/how(?:\/(\w+))?$/);
    if (how) {
      setNav("how");
      renderMethods(app, await getJson("/api/methods"), how[1]);
    } else if (match) {
      setNav("");
      renderStock(await getJson(`/api/stock/${encodeURIComponent(match[1])}`), today);
    } else if (hash === "#/results") {
      setNav("results");
      renderResults(await getJson("/api/results"));
    } else {
      setNav("today");
      renderToday(today);
    }
  } catch (error) {
    clearTimeout(waiting);
    app.innerHTML = loadError();
    app.querySelector("[data-retry]").addEventListener("click", route);
  }
  clearTimeout(waiting);
  window.scrollTo(0, 0);
}

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  refreshButton.textContent = "Refreshing…";
  await fetch("/api/refresh", { method: "POST" });
  pollRefresh();
});

window.addEventListener("hashchange", route);
window.addEventListener("resize", drawCharts);
route();
