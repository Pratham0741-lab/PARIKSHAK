// Visits all 9 screens, checks the data-source tag on each and the Recompute button, (then runs the judge-mode predict + score flow on examples/judge/) in headless Chromium against a running stack, saves a screenshot of each to
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
// T7: the permanent data-source tag expected for the active (first) lot, from its stored provenance.
const sd = firstLot.source_detail ?? {};
const expectedTag = sd.kind === 'SYNTHETIC' ? `SYNTHETIC seed=${sd.seed} generator=${sd.generator}`
  : sd.kind === 'UPLOADED' ? (sd.file && sd.file !== '(pasted CSV)' ? `UPLOADED: ${sd.file}` : 'MANUAL ENTRY')
  : firstLot.source === 'SYNTHETIC' ? 'SYNTHETIC (seed/generator not recorded: seeded before provenance tracking)' : 'UNKNOWN';

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
let recomputeNote = '';
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
  const tag = (await page.locator('[data-testid="data-source-tag"]').innerText().catch(() => '')).trim();
  if (screen === 'judge' ? !tag.startsWith('UPLOADED') && !tag.startsWith('JUDGE MODE') : tag !== expectedTag) {
    stale.push(`data-source tag "${tag}" (expected "${screen === 'judge' ? 'UPLOADED: <judge file>' : expectedTag}")`);
  }
  if (screen === 'model') {  // T7 debug: recompute visible metrics from raw rows; all must match
    await page.getByRole('button', { name: 'Recompute' }).click();
    const res = await page.locator('[data-testid="recompute-result"]').innerText({ timeout: 30000 });
    if (!/^all \d+ visible values match raw data$/.test(res)) stale.push(`recompute: ${res}`);
    else recomputeNote = res;
  }
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
// Ingest flow (validation only, nothing stored): examples/ingest_messy.csv has nA/ps units, aliased headers,
// a blank cell, a non-numeric cell and a duplicate ID. Ingest must stay disabled until the units are confirmed,
// and clicking an issue must show its file line.
{
  const MESSY = resolve(dirname(fileURLToPath(import.meta.url)), '../../examples/ingest_messy.csv');
  const consoleErrors = [];
  const failed = [];
  page.on('console', m => m.type() === 'error' && consoleErrors.push(m.text()));
  page.on('response', r => r.status() >= 400 && failed.push(`${r.status()} ${r.url()}`));
  await page.goto(`${UI}/ingest`, { waitUntil: 'networkidle' });
  await page.setInputFiles('input[type=file]', MESSY);
  await page.waitForSelector('[data-testid="detected-units"]', { timeout: 30000 });
  const button = page.getByRole('button', { name: 'Ingest and screen lot' });
  const lockedBefore = await button.isDisabled();
  await page.check('[data-testid="confirm-units"]');
  const unlockedAfter = !(await button.isDisabled());
  await page.getByText('non-numeric value').first().click();
  const rowText = await page.locator('[data-testid="issue-row"]').innerText();
  const text = await page.locator('body').innerText();
  await page.screenshot({ path: `${OUT}/ingest-flow.png`, fullPage: true });
  const stale = [];
  if (!lockedBefore) stale.push('ingest not locked before unit confirmation');
  if (!unlockedAfter) stale.push('ingest still locked after unit confirmation');
  if (!rowText.includes('n.a.?')) stale.push('issue click did not show the offending line');
  for (const want of ['na (file header)', 'ps (file header)', '1 non-numeric', 'Layout: wide']) if (!text.includes(want)) stale.push(want);
  results.push({ screen: 'ingest-flow', errorBanner: false, loading: false, empty: [], stale, consoleErrors, failed });
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
console.log(`data-source tag on every screen: "${expectedTag}" (judge: its own files); recompute on Model screen: ${recomputeNote || 'not run'}`);
process.exit(bad ? 1 : 0);
