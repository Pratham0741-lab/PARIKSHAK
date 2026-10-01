// Screenshots of every route at 1440x900 (and 1280x800 for layout overflow), reporting console errors,
// failed requests, error banners and horizontal overflow.
//   node scripts/routes_shots.mjs [UI_URL=http://localhost:8080] [OUT=../reports/screenshots/reskin]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const UI = process.argv[2] ?? 'http://localhost:8080';
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), process.argv[3] ?? '../../reports/screenshots/reskin');
mkdirSync(OUT, { recursive: true });
const ROUTES = [['overview', '/'], ['lot', '/lot'], ['part', '/part'], ['review', '/review'], ['trends', '/trends'], ['model', '/model'], ['ingest', '/ingest'], ['reports', '/reports']];

const browser = await chromium.launch();
let bad = false;
for (const [w, h] of [[1440, 900], [1280, 800]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  for (const [name, path] of ROUTES) {
    const errs = [];
    const onC = m => m.type() === 'error' && errs.push(m.text().slice(0, 200));
    const onE = e => errs.push('pageerror ' + e.message.slice(0, 200));
    const onR = r => r.status() >= 400 && errs.push(`HTTP ${r.status()} ${r.url()}`);
    page.on('console', onC); page.on('pageerror', onE); page.on('response', onR);
    await page.goto(UI + path, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const banner = await page.locator('[role=alert]').allInnerTexts();
    if (w === 1440) await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
    page.off('console', onC); page.off('pageerror', onE); page.off('response', onR);
    const problems = [...errs, ...(overflow > 0 ? [`horizontal overflow ${overflow}px`] : []), ...banner.map(b => `alert: ${b.slice(0, 120)}`)];
    if (problems.length) bad = true;
    console.log(`${w}x${h} ${name.padEnd(9)} ${problems.length ? problems.join(' | ') : 'OK'}`);
  }
  await page.close();
}
await browser.close();
process.exit(bad ? 1 : 0);
