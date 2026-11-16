// The desk page's words: desk.json turned into what docs/desk/index.html shows. No DOM here,
// so tests/test_desk_page.py runs it in Node. No model wrote any of it.
//
// The page shows less than the "Kitden desk" issue (scripts/desk_post.py): the five lights,
// what waits for the owner, the nightly tests and one link. The texts both say (CHECKS,
// OVERALL, KINDS, MEANS, the watcher's search) are the same; the test checks it. Text is never
// HTML: a piece is a string, {code} or {text, href}, and the page puts each in with textContent.
// A link is made only to github.com: every title and `why` was written by a person or a model.

export const DATA = 'https://raw.githubusercontent.com/KonstantinStarovoytov/kitden-sdlc/numbers/desk.json';
export const DATA_PAGE = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/desk.json';
export const HOW_TO = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/main/docs/owner.md';
export const RUNS = 'https://github.com/KonstantinStarovoytov/kitden-sdlc/actions/workflows/desk.yml';
export const REPO = 'KonstantinStarovoytov/kitden';
export const OLD_HOURS = 30; // the desk runs every day at 06:41 UTC; later than this, a run was missed
export const GREY_SHOWN = 2;
export const NOT_MEASURED_YET = 'not measured yet';

export const STATES = ['green', 'amber', 'red', 'grey'];
export const WORDS = { green: 'OK', amber: 'Needs a look', red: 'Wrong', grey: 'No data' };
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
// The one link the page keeps of the issue's searches (desk_post.SEARCHES).
export const SUMMARIES = ["The watcher's weekly summaries", 'issues', 'is:issue label:client-change label:summary'];

const GITHUB = /^https:\/\/github\.com\/[\w.~/#?=&%+-]*$/;
const SLUG = /^[\w-]+\/[\w.-]+$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// --- Small pieces ---

export const isNumber = v => typeof v === 'number' && Number.isFinite(v);
const isText = v => typeof v === 'string';
const rows = (desk, key) => (Array.isArray(desk[key]) ? desk[key].filter(r => r && typeof r === 'object' && !Array.isArray(r)) : []);

/** Text on one line: runs of white space become one space. */
export const line = v => (isText(v) ? v.split(/\s+/).filter(Boolean).join(' ') : '');

/** The address when it may be a link: github.com only. */
export const href = url => (isText(url) && GITHUB.test(url) ? url : null);

export const figure = v => (Number.isInteger(v) ? v.toLocaleString('en-US') : String(Math.round(v * 10) / 10));
export const count = (v, one, many) => `${figure(v)} ${v === 1 ? one : many}`;
export function days(v) {
  if (v >= 1) return count(v, 'day', 'days');
  const hours = Math.round(v * 24);
  return hours < 1 ? 'under an hour' : count(hours, 'hour', 'hours');
}
const own = (table, key) => (typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : undefined);
const capital = s => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** "`a` b" as pieces: the backticked parts become {code}. */
export function ticks(text) {
  return String(text).split('`').map((part, i) => (i % 2 ? { code: part } : part)).filter(p => p !== '');
}

/** A piece that is a link when the address may be one, else the text alone. */
export const linked = (text, url) => (href(url) ? { text, href: href(url) } : text);

/** "16 Nov" for "2026-11-16"; the text as it is when it is no such date. */
export function day(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(line(text));
  return m && MONTHS[+m[2] - 1] ? `${+m[3]} ${MONTHS[+m[2] - 1]}` : line(text);
}

/** "16 Nov 2026, 16:26 UTC". */
export function when(ms) {
  const d = new Date(ms);
  const hm = d.toISOString().slice(11, 16);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hm} UTC`;
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

// --- The parts ---

/** A light: its name, state and word; when green, what it checks (the issue's words, as a
 * sentence); when not, why, and a link to what it names. */
function lights(desk) {
  return rows(desk, 'lights').map(l => {
    const s = state(l.state);
    let why = line(l.why);
    if (s === 'green') why = '';
    else if (s === 'grey') why = why.replace(new RegExp(`^${NOT_MEASURED_YET}:?\\s*`, 'i'), '');
    const checks = own(CHECKS, l.id);
    return {
      id: line(l.id), name: line(l.name) || line(l.id) || '?', state: s, word: WORDS[s],
      checks: checks ? ticks(capital(checks)) : [],
      why: capital(why), open: s === 'grey' ? null : href(l.url),
    };
  });
}

function waiting(desk) {
  const items = desk.waiting;
  if (items === null || items === undefined) return null;
  return (Array.isArray(items) ? items : []).filter(i => i && typeof i === 'object').map(i => ({
    kind: own(KINDS, i.kind) || line(i.kind) || 'Item',
    title: [linked(line(i.title) || '(no title)', i.url)],
    do: i.do ? ticks(line(i.do)) : [],
    days: isNumber(i.days) ? `Waiting ${days(i.days)}.` : '',
  }));
}

/** Since when a nightly part is red, or has had no finished run (desk_post._part_mark). */
function partNote(r, s) {
  const since = isText(r.since) ? day(r.since) : null;
  const greySince = isText(r.grey_since) ? day(r.grey_since) : null;
  if (s === 'red') return since ? `Red since ${since}` : '';
  if (s !== 'grey') return '';
  if (since) return `Red since ${since}` + (greySince ? `; no finished run since ${greySince}` : '');
  if (greySince && Number.isInteger(r.grey_nights) && r.grey_nights >= GREY_SHOWN) return `No finished run since ${greySince}`;
  return line(r.why);
}

function nightly(desk) {
  if (!Array.isArray(desk.nightly)) return null;
  const parts = rows(desk, 'nightly').map(r => {
    const s = r.state === 'green' || r.state === 'red' ? r.state : 'grey';
    const failed = Array.isArray(r.failed) ? r.failed.filter(f => f && typeof f === 'object') : [];
    return {
      part: line(r.part) || '?', state: s, word: WORDS[s],
      workflow: line(r.name) || line(r.workflow) || 'Nightly run',
      night: isText(r.night) ? day(r.night) : null,
      run: href(r.run), note: partNote(r, s),
      means: s === 'red' ? (own(MEANS, r.part) || MEANS_ELSE) : '',
      failed: failed.map(f => ({
        job: [linked(line(f.job) || '?', f.url)],
        step: isText(f.step) ? `the step "${line(f.step)}" failed` : 'no failed step is named',
      })),
    };
  });
  // The night, and the workflow most parts come from, are said once, on top; a part says its
  // own only when it differs.
  const nights = [...new Set(parts.map(p => p.night))];
  const tally = parts.reduce((m, p) => m.set(p.workflow, (m.get(p.workflow) || 0) + 1), new Map());
  const common = [...tally].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  parts.forEach(p => { p.of = p.workflow === common ? '' : p.workflow; });
  return { night: nights.length === 1 ? nights[0] : null, mixed: nights.length > 1, common, parts };
}

/** Everything the page shows. `now` is a Date. */
export function view(desk, now = new Date()) {
  if (!desk || typeof desk !== 'object' || Array.isArray(desk)) throw new Error('desk.json is not an object');
  // No light read: the headline cannot say they are green.
  const overall = rows(desk, 'lights').length ? state(desk.overall) : 'grey';
  const updated = isText(desk.updated) ? Date.parse(desk.updated) : NaN;
  const known = !Number.isNaN(updated);
  const map = desk.map && typeof desk.map === 'object' && Array.isArray(desk.map.stale) ? desk.map.stale.length : 0;
  const [what, page, query] = SUMMARIES;
  return {
    overall, lead: OVERALL[overall],
    updated: known ? `Updated ${ago(updated, now)}` : 'Updated at an unknown time',
    updatedAt: known ? when(updated) : '',
    old: !known || now - updated > OLD_HOURS * 3600e3,
    lights: lights(desk),
    waiting: waiting(desk),
    nightly: nightly(desk),
    map: map ? `The workflow map is out of date in ${count(map, 'place', 'places')}. Run \`scripts/map_text.py --write\`.` : '',
    summaries: { text: what, href: `https://github.com/${repoOf(desk)}/${page}?q=${encodeURIComponent(query).replace(/%20/g, '+')}` },
  };
}
