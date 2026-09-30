// Visits all 8 screens in headless Chromium against a running stack, saves a screenshot of each to
// reports/screenshots/, and reports errors, empty states and stale values (page numbers compared
// with a fresh API read). Exit code 1 if any screen shows an error, a console error, a failed
// request or a stale value.
//
//   node scripts/screenshots.mjs [UI_URL=http://localhost:8080] [API_URL=http://localhost:8000/api/v1]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const UI = process.argv[2] ?? 'http://localhost:8080';
const API = process.argv[3] ?? 'http://localhost:8000/api/v1';
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '../../reports/screenshots');
mkdirSync(OUT, { recursive: true });

const SCREENS = ['lots', 'ingest', 'outliers', 'drift', 'components', 'decisions', 'model', 'reports'];
const EMPTY_MARKERS = ['No parts in this lot', 'No part selected', 'Select a part', ': no data', 'No audit events', 'No explanation available'];
const pct = x => `${(100 * x).toFixed(1)}%`;

const api = async p => (await fetch(API + p)).json();
const lots = await api('/lots');
const firstLot = lots[0];
const metrics = await api('/metrics/benchmark');

// Values each screen must show, computed from a fresh API read at the time of the check.
const expected = {
  lots: [`${firstLot.pass_count} pass / ${firstLot.review_count} review / ${firstLot.reject_count} reject`, `Status: ${firstLot.status}`],
  model: [pct(metrics.recall), pct(metrics.precision), metrics.weighted_cost.toFixed(0)],
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const results = [];
for (const screen of SCREENS) {
  const consoleErrors = [];
  const failed = [];
  const onConsole = m => m.type() === 'error' && consoleErrors.push(m.text());
  const onResponse = r => r.status() >= 400 && failed.push(`${r.status()} ${r.url()}`);
  page.on('console', onConsole);
  page.on('response', onResponse);
  await page.goto(`${UI}/${screen}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const text = await page.locator('body').innerText();
  const errorBanner = /Could not load|failed with HTTP/.test(text);
  const loading = /Loading/.test(text);
  const empty = EMPTY_MARKERS.filter(m => text.includes(m));
  const stale = (expected[screen] ?? []).filter(v => !text.includes(v));
  await page.screenshot({ path: `${OUT}/${screen}.png`, fullPage: true });
  page.off('console', onConsole);
  page.off('response', onResponse);
  results.push({ screen, errorBanner, loading, empty, stale, consoleErrors, failed });
}
await browser.close();

let bad = false;
for (const r of results) {
  const problems = [];
  if (r.errorBanner) problems.push('ERROR BANNER');
  if (r.consoleErrors.length) problems.push(`console errors: ${r.consoleErrors.join(' | ')}`);
  if (r.failed.length) problems.push(`failed requests: ${r.failed.join(' | ')}`);
  if (r.stale.length) problems.push(`STALE (expected from API but not shown): ${r.stale.join(', ')}`);
  if (problems.length) bad = true;
  const notes = [...problems];
  if (r.loading) notes.push('still shows "Loading"');
  if (r.empty.length) notes.push(`empty-state text: ${r.empty.join(', ')}`);
  console.log(`${r.screen.padEnd(11)} ${notes.length ? notes.join('; ') : 'OK'}  -> reports/screenshots/${r.screen}.png`);
}
process.exit(bad ? 1 : 0);
