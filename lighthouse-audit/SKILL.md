---
name: lighthouse-audit
description: Run a Lighthouse audit on a local web app and turn the result into an actionable punch list. Builds/serves a PRODUCTION build, runs mobile Lighthouse several times for a stable median, extracts category scores + the specific failing audits, and supports before/after comparisons. Use when asked to measure or improve web performance, run Lighthouse, check Core Web Vitals / LCP / CLS, or compare perf before and after a change.
---

# Lighthouse audit

You're being asked to measure a web app's quality with Lighthouse and report
something the user can act on — not just a number, but *which* audits failed and
why. When it's a before/after, capture a baseline before touching code.

## When to use

- "Run Lighthouse" / "check the performance" / "what's my LCP" / "Core Web Vitals"
- "Get this to 90+ on performance/accessibility/SEO"
- Before *and* after a perf pass, to prove the delta

## Prerequisites (check first)

- **Chrome installed.** Find it:
  - Win: `C:\Program Files\Google\Chrome\Application\chrome.exe`
  - macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
  - Linux: `which google-chrome || which chromium`
  - Export as `CHROME_PATH` for the Lighthouse CLI.
- **Lighthouse** via `npx -y lighthouse@12` (no install needed).
- A **production build**, not the dev server — dev builds are unminified and
  unbundled and give meaningless numbers.

## Process

### 1. Build and serve a production build

Detect the toolchain and use its real build + static-serve commands:

- **Vite:** `npm run build` → `npm run preview -- --port <P> --strictPort`
- **Next.js:** `npm run build` → `npm start -- -p <P>`
- **CRA / static `dist`/`build`:** build, then `npx -y serve -l <P> <outDir>`

Start the server in the background, then poll until it answers:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:<P>/
```

> Windows note: a backgrounded `vite preview` can keep a file handle on the
> served dir. If you later rebuild/convert files and hit `EBUSY`, stop the
> server first (find the PID with `Get-NetTCPConnection -LocalPort <P>`).

### 2. Run Lighthouse (mobile, simulated throttling)

```bash
CHROME_PATH="<chrome>" npx -y lighthouse@12 http://localhost:<P>/ \
  --only-categories=performance,accessibility,best-practices,seo \
  --form-factor=mobile --screenEmulation.mobile \
  --throttling-method=simulate --quiet \
  --chrome-flags="--headless=new --no-sandbox" \
  --output=json --output-path=./lh.json
```

Use `--preset=desktop` instead of the mobile flags for a desktop audit. Mobile
is the stricter, default-reported profile.

### 3. Run it 3–5 times and take the MEDIAN

Single runs are noisy — simulated Lighthouse can swing ±5 points between
identical runs. Never report one run. Loop, collect the perf score, report the
median (and mention the spread if it's wide):

```bash
for i in 1 2 3 4 5; do
  CHROME_PATH="<chrome>" npx -y lighthouse@12 http://localhost:<P>/ \
    --only-categories=performance --form-factor=mobile --screenEmulation.mobile \
    --throttling-method=simulate --quiet \
    --chrome-flags="--headless=new --no-sandbox" \
    --output=json --output-path=./lh-$i.json >/dev/null 2>&1
  node -e "const r=require('./lh-$i.json');console.log(Math.round(r.categories.performance.score*100))"
done
```

### 4. Parse scores + key metrics

```bash
node -e "const r=require('./lh.json'),c=r.categories,a=r.audits;
for(const k in c)console.log(k.padEnd(16),Math.round(c[k].score*100));
['first-contentful-paint','largest-contentful-paint','total-blocking-time','cumulative-layout-shift','speed-index']
  .forEach(m=>console.log(m.padEnd(28),a[m].displayValue));"
```

### 5. Extract the FAILING audits — this is the punch list

Scores alone aren't actionable. Pull the audits that actually failed, per
category, with savings and the offending DOM nodes:

```bash
node -e "const r=require('./lh.json'),a=r.audits,c=r.categories;
for(const cat of ['performance','accessibility','best-practices','seo']){
  console.log('\n=== '+cat.toUpperCase()+' ===');
  c[cat].auditRefs.forEach(ref=>{const au=a[ref.id];
    if(au&&au.score!==null&&au.score<1&&au.scoreDisplayMode!=='notApplicable'){
      const save=au.details&&au.details.overallSavingsMs;
      console.log('-',ref.id,save?('~'+Math.round(save)+'ms'):'','|',au.title);
      (au.details&&au.details.items||[]).slice(0,3).forEach(it=>{
        const s=(it.node&&it.node.snippet)||''; if(s)console.log('     ↳',s.slice(0,110));});
    }});}"
```

For a **slow LCP**, get the phase breakdown — it tells you *which* lever to pull:

```bash
node -e "const a=require('./lh.json').audits,el=a['largest-contentful-paint-element'];
const t=(el.details.items||[]).find(i=>i.type==='table');
(t&&t.items||[]).forEach(p=>console.log(p.phase,Math.round(p.timing)+'ms',(p.percent||'')));"
```

- High **Load Delay** → resource discovered/started late → preload it
  (`<link rel=preload as=image fetchpriority=high>`); for a hashed bundled asset,
  move it to a stable URL (e.g. a `public/` dir) so it's preloadable.
- High **Render Delay** → element loaded but painted late → render-blocking CSS/JS,
  or an overlay/JS gate. For a pure client-rendered SPA there's a first-paint
  floor (the bundle must parse before anything paints) — say so honestly; only
  SSR/prerendering moves it much further.

### 6. Before / after

Capture the baseline (steps 1–5) BEFORE any change → `lh-before.json`. Make the
changes, rebuild, re-serve, re-run → `lh-after.json`. Report a before→after table.

### 7. Clean up

Delete the temp `lh-*.json` files and stop the background server when done.

## Reliable wins to check for (most web apps)

- **Images:** convert to WebP/AVIF, downscale to *rendered* size, `loading="lazy"`
  + `decoding="async"` below the fold, explicit `width`/`height` (kills CLS).
  Mark the LCP image eager + `fetchpriority="high"` and preload it.
- **Fonts:** load non-render-blocking (`media="print"` → `onload="this.media='all'"`,
  `<noscript>` fallback) with `&display=swap`.
- **Render-blocking CSS:** inline small CSS to skip a round-trip.
- **A11y:** colour-contrast (WCAG AA = 4.5:1 body, 3:1 large text), image alt,
  control names matching visible text, target-size ≥24px.
- **SEO:** `<meta name="description">`, valid `robots.txt`, a title, crawlable links.
- Beware **code-splitting on throttled mobile** — the dynamic-import waterfall can
  *regress* LCP vs. a single bundle. Measure it; don't assume it helps.

## Output format

- One table: category scores (and before→after if applicable) + key metrics
  (FCP, LCP, TBT, CLS, SI).
- A grouped punch list of the failing audits with the concrete fix for each.
- If a target is missed, say so plainly and explain what's actually capping it
  (e.g. CSR first-paint floor) rather than padding the number.

## What NOT to do

- Don't audit the dev server or report a single noisy run.
- Don't claim a fix worked without re-running and showing the new number.
- Don't recommend a fix you didn't see in the failing-audit list.
