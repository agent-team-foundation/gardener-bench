import { chromium } from 'playwright';

const file = 'file:///tmp/gardener-report-deploy/index.html';
const dir = 'screenshots';

const shots = [
  { name: 'v2-desktop-top', vw: 1440, vh: 900, scroll: 0 },
  { name: 'v2-desktop-accuracy', vw: 1440, vh: 900, scroll: 700 },
  { name: 'v2-desktop-cards', vw: 1440, vh: 900, scroll: 2400 },
  { name: 'v2-mobile-top', vw: 375, vh: 812, scroll: 0 },
  { name: 'v2-mobile-accuracy', vw: 375, vh: 812, scroll: 900 },
  { name: 'v2-mobile-cards', vw: 375, vh: 812, scroll: 2800 },
];

const browser = await chromium.launch();
for (const s of shots) {
  const ctx = await browser.newContext({ viewport: { width: s.vw, height: s.vh } });
  const page = await ctx.newPage();
  await page.goto(file, { waitUntil: 'networkidle' });
  await page.evaluate((y) => window.scrollTo(0, y), s.scroll);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${dir}/${s.name}.png` });
  console.log(`  ${s.name}.png`);
  await ctx.close();
}
await browser.close();
