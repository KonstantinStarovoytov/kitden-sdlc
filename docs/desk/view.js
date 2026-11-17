// The desk page's words: desk.json turned into what docs/desk/index.html shows. No DOM here,
// so tests/test_desk_page.py runs it in Node. No model wrote any of it.
//
// The page reads desk.json's `bench` (scripts/desk_bench.py): main's checks, the nightly rows,
// the start-up times by release, the stores, the bugs and the upstream changes; and of desk.py's
// facts the lights, what waits and the agents' week. MEANS is what desk_post.py's ci-failure
// issues say a red part means; the test checks they are the same. Text is never HTML: a piece is
// a string, {code} or {text, href}, and the page puts each in with textContent. A link goes only
// to the hosts in LINKS: every title and `why` was written by a person or a model.

export const DATA = 'https://raw.githubusercontent.com/KonstantinStarovoytov/kitden-sdlc/numbers/desk.json';
export const DATA_PAGE = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/desk.json';
export const HOW_TO = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/main/docs/owner.md';
export const RUNS = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/actions/workflows/desk.yml';
export const REPO = 'KonstantinStarovoytov/kitden';
export const OLD_HOURS = 30; // the desk runs every day at 06:41 UTC; later than this, a run was missed
export const NIGHTS = 14; // desk_bench.NIGHTS
export const NOT_MEASURED_YET = 'not measured yet';
// A release is slower on a system than the one before it when both of these hold: the times
// are printed to a tenth of a second and one run differs from the next by about that much.
export const SLOWER_SECONDS = 0.2;
export const SLOWER_SHARE = 0.2;

export const STATES = ['green', 'amber', 'red', 'grey'];
export const WORDS = { green: 'OK', amber: 'Needs a look', red: 'Wrong', grey: 'No data' };
export const HEAD = {
  green: 'All good.',
  amber: 'Something needs a look.',
  red: 'Something is wrong.',
  grey: 'Some parts were not read.',
};
export const KINDS = {
  pull: 'Pull request', verdict: 'Verdict', release: 'Release',
  paused: 'Paused agent', 'spot-check': 'Spot check',
};
export const MEANS = {
  systems: 'Kitden may not work on that system or Python.',
  clients: 'The newest Claude Code or Codex writes or answers something Kitden\'s tests do not expect.',
  browser: 'A main flow of the page is broken in a real browser.',
};
export const MEANS_ELSE = 'A scheduled test run failed.';
export const SUMMARIES = ["The watcher's weekly summaries", 'issues', 'is:issue label:client-change label:summary'];
export const MEASURES = [
  { id: 'first', label: 'First usable', dash: '',
    tip: 'How long until you can use the page after it starts. Measured with one client slow on purpose (Codex takes 10 s to list its plugins), so the page has to show what it has without waiting for it.' },
  { id: 'complete', label: 'Complete', dash: '6 4',
    tip: 'How long until the first scan has read everything: every client, project, plugin and server, with every client answering at once.' },
];
export const SUPPORTED = 'Supported: macOS and Linux, Python 3.13 and 3.14.';
export const NOT_SUPPORTED = 'Not supported: Windows.';

// The hosts a link may go to: GitHub, and the stores Kitden is published in.
const LINKS = [
  /^https:\/\/github\.com\/[\w.~/#?=&%+-]*$/,
  /^https:\/\/pypi\.org\/project\/kitden\/[\w.]*\/?$/,
  /^https:\/\/registry\.modelcontextprotocol\.io\/v0\/servers\?search=[\w./-]+$/,
  /^https:\/\/glama\.ai\/mcp\/servers\/[\w./-]+$/,
  /^https:\/\/mcprush\.com\/konstantinstarovoytov\/kitden-mcp$/,
];
const SLUG = /^[\w-]+\/[\w.-]+$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const PLATFORM_PARTS = { 'End-to-end in Chromium': 'browser' };

// --- Small pieces ---

export const isNumber = v => typeof v === 'number' && Number.isFinite(v);
const isText = v => typeof v === 'string';
const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const list = v => (Array.isArray(v) ? v.filter(isObject) : []);
const own = (table, key) => (typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : undefined);
const capital = s => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Text on one line: runs of white space become one space. */
export const line = v => (isText(v) ? v.split(/\s+/).filter(Boolean).join(' ') : '');

/** The address when it may be a link (LINKS); null otherwise. */
export const href = url => (isText(url) && LINKS.some(re => re.test(url)) ? url : null);

export const figure = v => (Number.isInteger(v) ? v.toLocaleString('en-US') : String(Math.round(v * 10) / 10));
export const count = (v, one, many) => `${figure(v)} ${v === 1 ? one : many}`;
export function days(v) {
  if (v >= 1) return count(Math.round(v * 10) / 10, 'day', 'days');
  const hours = Math.round(v * 24);
  return hours < 1 ? 'under an hour' : count(hours, 'hour', 'hours');
}

/** "`a` b" as pieces: the backticked parts become {code}. */
export function ticks(text) {
  return String(text).split('`').map((part, i) => (i % 2 ? { code: part } : part)).filter(p => p !== '');
}

/** A piece that is a link when the address may be one, else the text alone. */
export const linked = (text, url) => (href(url) ? { text, href: href(url) } : text);

/** "16 Nov" for "2026-11-16" or a full time; the text as it is when it is no date. */
export function day(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(line(text));
  return m && MONTHS[+m[2] - 1] ? `${+m[3]} ${MONTHS[+m[2] - 1]}` : line(text);
}

/** "16 Nov 2026, 16:26 UTC". */
export function when(ms) {
  const d = new Date(ms);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${d.toISOString().slice(11, 16)} UTC`;
}

/** "just now", "12 minutes ago", "3 hours ago", "2 days ago". */
export function ago(ms, now) {
  const minutes = Math.max(0, Math.round((now - ms) / 60e3));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${count(minutes, 'minute', 'minutes')} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${count(hours, 'hour', 'hours')} ago`;
  return `${count(Math.round(hours / 24), 'day', 'days')} ago`;
}

export const state = v => (STATES.includes(v) ? v : 'grey');
export const repoOf = desk => (isText(desk.repo) && SLUG.test(desk.repo) ? desk.repo : REPO);
const known = ['green', 'amber', 'red', 'grey', 'none', 'planned'];
const cellState = v => (known.includes(v) ? v : 'grey');
/** Seconds as the page shows them: "450 ms", "1.8 s". */
export const seconds = v => (v < 1 ? `${Math.round(v * 1000)} ms` : `${Math.round(v * 100) / 100} s`);

// --- The parts ---

function waiting(desk) {
  const items = desk.waiting;
  if (items === null || items === undefined) return null;
  return list(items).map(i => ({
    kind: own(KINDS, i.kind) || line(i.kind) || 'Item',
    title: [linked(line(i.title) || '(no title)', i.url)],
    do: i.do ? ticks(line(i.do)) : [],
    days: isNumber(i.days) ? `Waiting ${days(i.days)}.` : '',
  }));
}

function lightOf(desk, id) {
  const l = list(desk.lights).find(x => x.id === id);
  if (!l) return null;
  const s = state(l.state);
  let why = line(l.why);
  if (s === 'green') why = '';
  else if (s === 'grey') why = why.replace(new RegExp(`^${NOT_MEASURED_YET}:?\\s*`, 'i'), '');
  return { state: s, word: WORDS[s], why: capital(why), open: s === 'grey' ? null : href(l.url) };
}

function gate(bench, now) {
  const g = bench.gate;
  if (!isObject(g)) return null;
  const at = isText(g.at) ? Date.parse(g.at) : NaN;
  return {
    state: cellState(g.state),
    sha: isText(g.sha) ? g.sha.slice(0, 7) : '',
    url: href(g.url),
    at: Number.isNaN(at) ? '' : ago(at, now),
    steps: list(g.steps).map(s => ({ name: line(s.name) || '?', state: cellState(s.state), url: href(s.url) })),
  };
}

function nightOf(n) {
  return {
    night: isText(n.night) ? day(n.night) : '',
    state: cellState(n.state),
    url: href(n.url),
  };
}

/** A row's strip: its nights, padded at the start to NIGHTS so every strip lines up. */
function strip(nights) {
  const shown = list(nights).slice(-NIGHTS).map(nightOf);
  return [...Array.from({ length: NIGHTS - shown.length }, () => ({ night: '', state: 'empty', url: null })), ...shown];
}

function bench(benchData) {
  if (!Array.isArray(benchData.rows)) return null;
  const rows = list(benchData.rows).map(r => {
    const s = cellState(r.state);
    const part = own(PLATFORM_PARTS, r.name) || (r.group === 'compatibility' ? 'clients' : 'systems');
    return {
      group: r.group === 'compatibility' ? 'compatibility' : 'platforms',
      name: line(r.name) || '?',
      state: s,
      word: own(WORDS, s) || WORDS.grey,
      startup: r.name === 'Start-up time',
      cells: list(r.cells).map(c => ({ label: line(c.label) || '?', state: cellState(c.state), url: href(c.url) })),
      since: isText(r.since) ? `Red since ${day(r.since)}` : '',
      means: s === 'red' ? (r.name === 'Start-up time' ? 'A start-up budget is missed on that system.'
        : r.name === 'Newest dependencies' ? MEANS_ELSE : own(MEANS, part) || MEANS_ELSE) : '',
      failed: list(r.failed).map(f => ({
        job: [linked(line(f.job) || '?', f.url)],
        step: isText(f.step) ? `the step "${line(f.step)}" failed` : 'no failed step is named',
      })),
      run: href(r.url),
      nights: strip(r.nights),
    };
  });
  const nights = rows.map(r => r.nights.at(-1)?.night).filter(Boolean);
  return {
    night: nights.length ? nights[0] : '',
    platforms: rows.filter(r => r.group === 'platforms'),
    compatibility: rows.filter(r => r.group === 'compatibility'),
  };
}

function stores(benchData) {
  const s = benchData.stores;
  if (!isObject(s)) return null;
  const newest = isObject(s.newest) && isText(s.newest.version) ? s.newest.version : null;
  const tiles = list(s.stores).map(t => {
    const st = cellState(t.state);
    let note = line(t.note);
    if (!note && isText(t.at)) note = `Since ${day(t.at)}, ${line(t.at).slice(11, 16)} UTC`;
    if (!note && st === 'amber' && newest) note = `Behind: the newest is ${newest}`;
    return {
      name: line(t.name) || '?',
      state: st,
      version: isText(t.version) ? t.version : (st === 'planned' ? 'Planned' : t.listed === true && st === 'green' ? 'Listed' : '—'),
      note,
      url: href(t.url),
    };
  });
  const behind = tiles.filter(t => t.state === 'amber');
  const unread = tiles.filter(t => t.state === 'grey');
  let says = '';
  if (newest) {
    if (behind.length) says = `Kitden ${newest} is the newest release; ${behind.map(t => `${t.name} is on ${t.version}`).join(', ')}.`;
    else if (unread.length) says = `Kitden ${newest} is the newest release; ${unread.map(t => t.name).join(' and ')} could not be read.`;
    else says = `Kitden ${newest} is the newest release, and every store has it.`;
  }
  return { newest, tiles, says, behind: behind.length > 0, newestAt: isObject(s.newest) && isText(s.newest.at) ? day(s.newest.at) : '' };
}

/** The start-up chart's data: one line per system and measure, by version. */
function startup(benchData) {
  const s = benchData.startup;
  if (!isObject(s) || !Array.isArray(s.versions) || !s.versions.length) return null;
  const versions = s.versions.filter(isText);
  const n = versions.length;
  const num = v => (isNumber(v) ? v : null);
  const systems = list(s.systems).map(x => ({
    id: line(x.id), label: `${line(x.os)} · ${line(x.arch)}`,
    first: (Array.isArray(x.first) ? x.first : []).slice(0, n).map(num),
    complete: (Array.isArray(x.complete) ? x.complete : []).slice(0, n).map(num),
    measured: (Array.isArray(x.runs) ? x.runs : []).slice(0, n).map(v => (Number.isInteger(v) ? v : 0)),
  }));
  const budgets = isObject(s.budgets) ? { first: num(s.budgets.first), complete: num(s.budgets.complete) } : {};
  // The newest version each system was measured on, and the one before it there.
  const lastTwo = vals => {
    const idx = vals.map((v, i) => (v === null ? -1 : i)).filter(i => i >= 0);
    return idx.slice(-2);
  };
  const newest = versions[n - 1];
  const fastest = Math.min(...systems.map(x => x.first[n - 1]).filter(v => v !== null));
  const rows = systems.map(x => {
    const [a, b] = lastTwo(x.first);
    const firstNow = x.first[n - 1];
    let change = '';
    let slower = false;
    for (const key of ['first', 'complete']) {
      const [i, j] = lastTwo(x[key]);
      if (j === n - 1 && i !== undefined) {
        const was = x[key][i], now = x[key][j];
        const grew = now - was;
        if (grew >= SLOWER_SECONDS - 1e-9 && grew / was >= SLOWER_SHARE - 1e-9) slower = true; // tenths: 0.7 - 0.5 is 0.19999…
      }
    }
    if (b === n - 1 && a !== undefined) {
      const pct = Math.round(((x.first[b] - x.first[a]) / x.first[a]) * 100);
      change = `${pct > 0 ? '+' : ''}${pct}% vs ${versions[a]}`;
    }
    return {
      label: x.label, id: x.id,
      first: firstNow === null ? '—' : seconds(firstNow),
      complete: x.complete[n - 1] === null ? '—' : seconds(x.complete[n - 1]),
      fastest: firstNow === null || !isFinite(fastest) ? '—'
        : firstNow / fastest < 1.05 ? 'fastest' : `${(firstNow / fastest).toFixed(1)}× slower`,
      change: change || '—',
      slower,
    };
  });
  const mainNight = isText(s.main_night) ? day(s.main_night) : '';
  return { versions, newest, systems, budgets, rows, mainNight };
}

function cards(desk, benchData) {
  const bugs = isObject(benchData.bugs) ? benchData.bugs : null;
  const up = isObject(benchData.upstream) ? benchData.upstream : null;
  const repo = repoOf(desk);
  const [what, page, query] = SUMMARIES;
  const agents = list(desk.week).map(w => ({
    name: line(w.name) || line(w.agent) || '?',
    runs: isNumber(w.runs) ? count(w.runs, 'run', 'runs') : 'runs not read',
    failed: isNumber(w.failed) ? `${figure(w.failed)} failed` : '',
  }));
  const watched = up && isNumber(up.watcher_days)
    ? (up.watcher_days < 1 ? 'The watcher read the release notes today.'
      : `The watcher read the release notes ${days(up.watcher_days)} ago.`) : '';
  return {
    bugs: { light: lightOf(desk, 'bugs'), open: bugs && isNumber(bugs.open) ? bugs.open : null, url: bugs ? href(bugs.url) : null },
    upstream: {
      light: lightOf(desk, 'clients'),
      confirmed: up && isNumber(up.confirmed) ? up.confirmed : null,
      unconfirmed: up && isNumber(up.unconfirmed) ? up.unconfirmed : null,
      watched,
      url: up ? href(up.url) : null,
      summaries: { text: what, href: `https://github.com/${repo}/${page}?q=${encodeURIComponent(query).replace(/%20/g, '+')}` },
    },
    agents: { light: lightOf(desk, 'agents'), list: agents },
  };
}

/** The headline. Red only for what blocks: a supported platform, or a check on main (the gate,
 * or the Works light, which also reads the checks main requires). Amber for anything else that
 * needs a look: a light that is amber or red (a red Clients, Bugs, Agents or Queue light needs a
 * look, it does not block), compatibility, a store behind. Grey when a part that blocks was not
 * read; green otherwise. */
function headline(g, b, st, desk) {
  const red = b ? b.platforms.find(r => r.state === 'red') : null;
  if (red) return { state: 'red', text: `Blocked: ${red.name} is red.` };
  const works = lightOf(desk, 'works');
  if ((g && g.state === 'red') || (works && works.state === 'red')) return { state: 'red', text: 'A check on main failed.' };
  const lights = ['works', 'bugs', 'clients', 'agents', 'queue'].map(id => lightOf(desk, id)).filter(Boolean);
  const amber = lights.some(l => l.state === 'amber' || l.state === 'red')
    || (b && b.compatibility.some(r => r.state === 'red'))
    || (st && st.behind);
  if (amber) return { state: 'amber', text: HEAD.amber };
  // Only what blocks a release can make the page grey; compatibility only informs.
  const unread = !g || g.state !== 'green' || !b || b.platforms.some(r => r.state !== 'green');
  return unread ? { state: 'grey', text: HEAD.grey } : { state: 'green', text: HEAD.green };
}

/** Everything the page shows. `now` is a Date. */
export function view(desk, now = new Date()) {
  if (!isObject(desk)) throw new Error('desk.json is not an object');
  const benchData = isObject(desk.bench) ? desk.bench : {};
  const updated = isText(desk.updated) ? Date.parse(desk.updated) : NaN;
  const known_ = !Number.isNaN(updated);
  const map = isObject(desk.map) && Array.isArray(desk.map.stale) ? desk.map.stale.length : 0;
  const g = gate(benchData, now);
  const b = bench(benchData);
  const st = stores(benchData);
  return {
    head: headline(g, b, st, desk),
    says: st ? st.says : '',
    updated: known_ ? `Updated ${ago(updated, now)}` : 'Updated at an unknown time',
    updatedAt: known_ ? when(updated) : '',
    old: !known_ || now - updated > OLD_HOURS * 3600e3,
    map: map ? `The workflow map is out of date in ${count(map, 'place', 'places')}. Run \`scripts/map_text.py --write\`.` : '',
    waiting: waiting(desk),
    stores: st,
    gate: g,
    bench: b,
    startup: startup(benchData),
    cards: cards(desk, benchData),
    supported: SUPPORTED,
    notSupported: NOT_SUPPORTED,
  };
}
