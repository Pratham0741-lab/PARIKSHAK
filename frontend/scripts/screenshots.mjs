// Visits all 9 screens (then runs the judge-mode predict + score flow on examples/judge/) in headless Chromium against a running stack, saves a screenshot of each to
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

const SCREENS = ['lots', 'ingest', 'outliers', 'drift', 'components', 'decisions', 'model', 'reports', 'judge'];
const EMPTY_MARKERS = ['No parts in this lot', 'No part selected', 'Select a part', ': no data', 'No audit events', 'No explanation available'];
const pct = x => `${(100 * x).toFixed(1)}%`;

const api = async p => (await fetch(API + p)).json();
const lots = await api('/lots');
const firstLot = lots[0];
const metrics = await api('/metrics/benchmark');
const judgeModel = (await api('/judge/model')).model;

// Values each screen must show, computed from a fresh API read at the time of the check.
const expected = {
  lots: [`${firstLot.pass_count} pass / ${firstLot.review_count} review / ${firstLot.reject_count} reject`, `Status: ${firstLot.status}`],
  model: [pct(metrics.recall), pct(metrics.precision), metrics.weighted_cost.toFixed(0)],
  judge: judgeModel ? [`Trained on ${judgeModel.file}, ${judgeModel.n_parts} parts, ${judgeModel.n_lots} lots`,
    pct(judgeModel.oof_metrics.detection.recall)] : [],
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

// Judge flow: predict from examples/judge/test.csv, score against examples/judge/truth.csv, and check that
// the UI shows exactly the numbers the scoring API returns for the same files.
if (judgeModel) {
  const EX = resolve(dirname(fileURLToPath(import.meta.url)), '../../examples/judge');
  const { readFileSync } = await import('node:fs');
  const consoleErrors = [];
  const failed = [];
  page.on('console', m => m.type() === 'error' && consoleErrors.push(m.text()));
  page.on('response', r => r.status() >= 400 && failed.push(`${r.status()} ${r.url()}`));
  await page.goto(`${UI}/judge`, { waitUntil: 'networkidle' });
  await page.setInputFiles('[data-testid="file-Predict from CSV"]', `${EX}/test.csv`);
  await page.waitForSelector('text=preds.csv', { timeout: 60000 });
  await page.setInputFiles('[data-testid="file-Upload truth CSV"]', `${EX}/truth.csv`);
  await page.waitForSelector('[data-testid="judge-score"]', { timeout: 60000 });
  const text = await page.locator('[data-testid="judge-score"]').innerText();
  const preds = await (await fetch(`${API}/judge/predictions.csv`)).text();
  const ref = await (await fetch(`${API}/judge/score`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ truth_csv: readFileSync(`${EX}/truth.csv`, 'utf8'), truth_filename: 'truth.csv', predictions_csv: preds }) })).json();
  const want = [pct(ref.detection.recall), pct(ref.detection.precision), ref.regression.mae.toFixed(4),
    `TP ${ref.confusion_matrix.tp}`, `FN ${ref.confusion_matrix.fn}`, `FP ${ref.confusion_matrix.fp}`, `TN ${ref.confusion_matrix.tn}`];
  await page.screenshot({ path: `${OUT}/judge-flow.png`, fullPage: true });
  results.push({ screen: 'judge-flow', errorBanner: /failed|HTTP \d{3}/.test(text), loading: false, empty: [],
    stale: want.filter(v => !text.includes(v)), consoleErrors, failed });
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
