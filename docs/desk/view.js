// The desk page's words: desk.json turned into what docs/desk/index.html shows. No DOM here,
// so tests/test_desk_page.py runs it in Node. No model wrote any of it.
//
// The words follow scripts/desk_post.py, which writes the same facts as the "Kitden desk"
// issue; the test checks that the shared texts (CHECKS, OVERALL, KINDS, MEANS, SEARCHES) are
// the same. Text is never HTML: a piece is a string, {code} or {text, href}, and the page puts
// each one in with textContent. A link is made only to github.com, or to a usage page that
// config/agents.json names (only the owner changes it): every title and `why` was written by a
// person or a model.

export const DATA = 'https://raw.githubusercontent.com/KonstantinStarovoytov/kitden-sdlc/numbers/desk.json';
export const ROSTER = 'https://raw.githubusercontent.com/KonstantinStarovoytov/kitden-sdlc/main/config/agents.json';
export const DATA_PAGE = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/desk.json';
export const HOW_TO = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/main/docs/owner.md';
export const RUNS = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/actions/workflows/desk.yml';
export const REPO = 'KonstantinStarovoytov/kitden';
export const SINCE_DAYS = 90; // count_reviews.SINCE_DAYS
export const OLD_HOURS = 30; // the desk runs every day at 06:41 UTC; later than this, a run was missed
export const GREY_SHOWN = 2;
export const NOT_MEASURED_YET = 'not measured yet';

export const STATES = ['green', 'amber', 'red', 'grey'];
export const WORDS = { green: 'ok', amber: 'look', red: 'wrong', grey: 'not measured' };
export const OVERALL = {
  green: 'All five lights are green.',
  amber: 'Something needs a look.',
  red: 'Something is wrong.',
  grey: 'Some lights are not measured yet; none is amber or red.',
};
export const CHECKS = {
  works: 'the checks on `main` pass',
  clients: 'no confirmed client change waits long',
  bugs: 'open bugs do not keep growing',
  agents: 'the bots run and are not paused',
  queue: 'nothing waits for you long',
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
export const SEARCHES = [
  ['Open issues from people', 'issues', 'is:issue is:open -label:automated'],
  ['Open issues from bots', 'issues', 'is:issue is:open label:automated'],
  ['Open pull requests by the release bot', 'pulls', 'is:pr is:open author:app/kitden-beacon'],
  ["The watcher's weekly summaries", 'issues', 'is:issue label:client-change label:summary'],
];
const NOT_APPLICABLE = { 'release-prep': ['agreed', 'disagreed'] };
export const DASH = Object.freeze({ dash: true }); // a cell that does not apply to its row

const GITHUB = /^https:\/\/github\.com\/[\w.~/#?=&%+-]*$/;
const USAGE = /^https:\/\/[\w.-]+\/[\w.~/#?=&%+-]*$/;
const SLUG = /^[\w-]+\/[\w.-]+$/;

// --- Small pieces ---

export const isNumber = v => typeof v === 'number' && Number.isFinite(v);
const isText = v => typeof v === 'string';
const rows = (desk, key) => (Array.isArray(desk[key]) ? desk[key].filter(r => r && typeof r === 'object' && !Array.isArray(r)) : []);
const list = (desk, key) => (desk[key] === null || desk[key] === undefined ? null : Array.isArray(desk[key]) ? desk[key] : []);

/** Text on one line: runs of white space become one space. */
export const line = v => (isText(v) ? v.split(/\s+/).filter(Boolean).join(' ') : '');

/** The address when it may be a link: github.com, or a usage page the roster names. */
export function href(url, usage = new Set()) {
  if (!isText(url)) return null;
  return GITHUB.test(url) || (usage.has(url) && USAGE.test(url)) ? url : null;
}

export const figure = v => (Number.isInteger(v) ? v.toLocaleString('en-US') : String(Math.round(v * 10) / 10));
export const count = (v, one, many) => `${figure(v)} ${v === 1 ? one : many}`;
export const days = v => (v >= 0 && v < 0.05 ? 'under 0.1 days' : count(v, 'day', 'days'));

/** "`a` b" as pieces: the backticked parts become {code}. */
export function ticks(text) {
  return String(text).split('`').map((part, i) => (i % 2 ? { code: part } : part)).filter(p => p !== '');
}

/** A piece that is a link when the address may be one, else the text alone. */
export const linked = (text, url, usage) => (href(url, usage) ? { text, href: href(url, usage) } : text);

export function when(text) {
  const t = isText(text) ? Date.parse(text) : NaN;
  if (Number.isNaN(t)) return 'an unknown time';
  return new Date(t).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

export const state = v => (STATES.includes(v) ? v : 'grey');
export const repoOf = desk => (isText(desk.repo) && SLUG.test(desk.repo) ? desk.repo : REPO);

// --- The parts ---

function lights(desk, usage) {
  return rows(desk, 'lights').map(l => {
    const s = state(l.state);
    let why = line(l.why);
    if (s === 'green') why = '';
    else if (s === 'grey') why = why.replace(new RegExp(`^${NOT_MEASURED_YET}:?\\s*`, 'i'), '');
    return {
      id: line(l.id), name: line(l.name) || line(l.id) || '?', state: s, word: WORDS[s],
      checks: CHECKS[l.id] ? ticks(CHECKS[l.id]) : [],
      why: why ? [s === 'grey' ? why : linked(why, l.url, usage)] : [],
    };
  });
}

function waiting(desk, usage) {
  const items = list(desk, 'waiting');
  if (items === null) return null;
  return items.filter(i => i && typeof i === 'object').map(i => ({
    kind: KINDS[i.kind] || line(i.kind) || 'Item',
    title: [linked(line(i.title) || '(no title)', i.url, usage)],
    do: i.do ? ticks(line(i.do)) : [],
    days: isNumber(i.days) ? `Waiting ${days(i.days)}.` : '',
  }));
}

/** Since when a nightly part is red, or has had no finished run (desk_post._part_mark). */
function partNote(r, s) {
  const since = isText(r.since) ? line(r.since) : null;
  const greySince = isText(r.grey_since) ? line(r.grey_since) : null;
  if (s === 'red') return since ? `red since ${since}` : 'red';
  if (s !== 'grey') return '';
  if (since) return `red since ${since}` + (greySince ? `; no finished run since ${greySince}` : '');
  if (greySince && Number.isInteger(r.grey_nights) && r.grey_nights >= GREY_SHOWN) return `no finished run since ${greySince}`;
  return line(r.why);
}

function nightly(desk, usage) {
  if (!Array.isArray(desk.nightly)) return null;
  return rows(desk, 'nightly').map(r => {
    const s = r.state === 'green' || r.state === 'red' ? r.state : 'grey';
    const failed = Array.isArray(r.failed) ? r.failed.filter(f => f && typeof f === 'object') : [];
    return {
      part: line(r.part) || '?', state: s, word: WORDS[s],
      workflow: line(r.name) || line(r.workflow) || 'Nightly run',
      night: isText(r.night) ? `the night of ${line(r.night)}` : 'the night is not known',
      run: href(r.run, usage), note: partNote(r, s),
      means: s === 'red' ? (MEANS[r.part] || MEANS_ELSE) : '',
      failed: failed.map(f => ({
        job: [linked(line(f.job) || '?', f.url, usage)],
        step: isText(f.step) ? `the step "${line(f.step)}" failed` : 'no failed step is named',
      })),
    };
  });
}

function use(desk) {
  const u = desk.use && typeof desk.use === 'object' ? desk.use : {};
  return [
    ['Issues from others', u.issues_from_others, 'this month'],
    ['Pull requests from others', u.pulls_from_others, 'this month'],
    ['Stars', u.stars, 'on GitHub'],
    ['Downloads', u.downloads, 'from PyPI last month'],
  ].map(([label, v, note]) => ({ label, value: isNumber(v) ? figure(v) : null, note }));
}

function review(desk) {
  const r = desk.review && typeof desk.review === 'object' ? desk.review : {};
  const { clean, fixed, days_to_merge: d } = r;
  if (![clean, fixed, d].some(isNumber)) return `Reviews: ${NOT_MEASURED_YET}.`;
  return 'Reviews: ' + [
    isNumber(clean) ? `${count(clean, 'review', 'reviews')} found nothing` : `reviews that found nothing: ${NOT_MEASURED_YET}`,
    isNumber(fixed) ? `${count(fixed, 'finding was', 'findings were')} fixed before the merge` : `findings fixed: ${NOT_MEASURED_YET}`,
    isNumber(d) ? `a reviewed pull request took ${days(d)} to merge (the median)` : `days to merge: ${NOT_MEASURED_YET}`,
  ].join('; ') + '.';
}

/** A table: a column with no value in any row is left out and, unless it applies to no row,
 * named in `missing` (desk_post._table). null when no row or no column is left. */
export function table(items, columns) {
  const values = items.map(r => columns.map(([, get]) => get(r)));
  const keep = [0, ...columns.map((_, i) => i).slice(1).filter(i =>
    values.some(v => v[i] !== null && v[i] !== undefined && v[i] !== DASH))];
  if (!items.length || keep.length === 1) return null;
  const cell = v => (v === null || v === undefined ? 'not measured' : v === DASH ? '—'
    : isNumber(v) ? figure(v) : Array.isArray(v) ? v.map(line).join(', ') : typeof v === 'object' ? v : line(String(v)) || 'not given');
  return {
    head: keep.map(i => columns[i][0]),
    rows: values.map(v => keep.map(i => cell(v[i]))),
    missing: columns.filter((_, i) => !keep.includes(i) && values.some(v => v[i] === null || v[i] === undefined)).map(c => c[0]),
  };
}

const applies = (r, key) => ((NOT_APPLICABLE[r.agent] || []).includes(key) ? DASH : r[key]);

function week(desk) {
  return table(rows(desk, 'week'), [
    ['Agent', r => r.name || r.agent],
    ['Runs', r => r.runs], ['Failed', r => r.failed], ['Did', r => r.did],
    ['No answer', r => ('no_answer' in r ? r.no_answer : DASH)],
    ['You agreed', r => applies(r, 'agreed')], ['You disagreed', r => applies(r, 'disagreed')],
  ]);
}

function foundBy(desk) {
  return table(rows(desk, 'found_by'), [
    ['Month', r => r.month],
    ...[['Review', 'review'], ['Nightly', 'nightly'], ['Tester', 'tester'], ['Watcher', 'watcher'],
      ['You', 'owner'], ['Others', 'others']].map(([h, k]) => [h, r => r[k]]),
  ]);
}

function misses(desk, usage) {
  const items = list(desk, 'misses');
  if (items === null) return null;
  const ref = v => (Number.isInteger(v) ? `#${v}` : line(String(v)));
  return items.filter(i => i && typeof i === 'object').map(i => [
    linked(`Issue ${ref(i.issue)}`, i.url, usage), `, caused by pull request ${ref(i.pull)}`]);
}

function budget(desk, usage) {
  const b = desk.budget && typeof desk.budget === 'object' ? desk.budget : {};
  const names = Object.fromEntries(rows(desk, 'week').map(r => [r.agent, r.name]));
  const agents = (Array.isArray(b.agents) ? b.agents : []).filter(r => r && typeof r === 'object');
  const keys = (Array.isArray(b.keys) ? b.keys : []).filter(r => r && typeof r === 'object');
  return {
    caps: table(agents, [['Agent', r => names[r.agent] || r.agent], ['Runs', r => r.runs], ['Cap', r => r.cap]]),
    keys: table(keys, [
      ['Key', r => r.name], ['Stored in', r => r.stored], ['Used by', r => r.used_by],
      ['Money cap', r => r.money_cap],
      ['Usage page', r => (!isText(r.dashboard) || !r.dashboard.trim() ? 'not given'
        : href(r.dashboard, usage) ? { text: r.dashboard, href: href(r.dashboard, usage) } : { code: line(r.dashboard) })],
    ]),
  };
}

function links(desk) {
  const repo = repoOf(desk);
  return SEARCHES.map(([what, page, query]) => ({
    text: what, href: `https://github.com/${repo}/${page}?q=${encodeURIComponent(query).replace(/%20/g, '+')}`,
  }));
}

/** The usage pages the roster (config/agents.json) names. */
export function usagePages(roster) {
  try {
    return new Set(roster.keys.map(k => k.dashboard).filter(d => isText(d) && USAGE.test(d)));
  } catch {
    return new Set();
  }
}

/** Everything the page shows. `now` is a Date; `usage` a Set from usagePages. */
export function view(desk, now = new Date(), usage = new Set()) {
  if (!desk || typeof desk !== 'object' || Array.isArray(desk)) throw new Error('desk.json is not an object');
  const overall = state(desk.overall);
  const updated = Date.parse(desk.updated);
  const map = desk.map && typeof desk.map === 'object' && Array.isArray(desk.map.stale) ? desk.map.stale.length : 0;
  return {
    overall, lead: OVERALL[overall],
    updated: when(desk.updated),
    old: Number.isNaN(updated) || now - updated > OLD_HOURS * 3600e3,
    lights: lights(desk, usage),
    waiting: waiting(desk, usage),
    nightly: nightly(desk, usage),
    setAside: Number.isInteger(desk.set_aside) ? desk.set_aside : null,
    setAsideUrl: `https://github.com/${repoOf(desk)}/blob/main/tests/set-aside.txt`,
    map: map ? `The workflow map is out of date in ${count(map, 'place', 'places')}. Run \`scripts/map_text.py --write\`.` : '',
    use: use(desk),
    week: week(desk),
    weekNote: `Reviews are counted over the last ${SINCE_DAYS} days, the weekly columns over the last 7 (the watcher's verdicts over 30).`,
    review: review(desk),
    foundBy: foundBy(desk),
    misses: misses(desk, usage),
    budget: budget(desk, usage),
    links: links(desk),
  };
}
