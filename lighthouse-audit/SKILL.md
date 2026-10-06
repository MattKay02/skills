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

### 6. Check the numbers are real before acting on them

Simulated throttling *estimates* mobile timings from one unthrottled load, and
it can be badly wrong. Two checks catch most of it.

**a. Cross-check the simulation against a real throttled load.** Signs the
simulation is off: the observed first paint lands long after the observed load
event, or the LCP element is server-rendered text yet shows seconds of Render
Delay.

```bash
node -e "const m=require('./lh.json').audits.metrics.details.items[0];
['observedFirstContentfulPaint','observedLargestContentfulPaint','observedLoad','largestContentfulPaint']
  .forEach(k=>console.log(k.padEnd(32),Math.round(m[k])+'ms'));"
```

If so, re-run 2–3 times with `--throttling-method=devtools` in place of
`simulate`. That throttling is applied for real (CPU slowed, slow 4G), so its
LCP and TBT are measured, not estimated. Also time the same page in an ordinary
browser with the same phone emulation (a `PerformanceObserver` on `paint` and
`largest-contentful-paint`). When the three disagree, report the measured
numbers and say why the simulated ones are off. Don't chase an LCP that only
exists in the estimate.

**b. Look for scripts the hosting adds.** A CDN or proxy can inject scripts
that are nowhere in the codebase, so audit the **deployed URL** too, not only
localhost. Cloudflare's proxy, for example, adds
`/cdn-cgi/challenge-platform/.../jsd/main.js` (bot detection). It shows up as a
top entry in `bootup-time` and `long-tasks` and as a best-practices
`deprecations` failure, on every page.

```bash
curl -sI https://<site>/ | grep -iE "^(server|cf-ray|via|x-cache)"
node -e "const a=require('./lh.json').audits;
(a['bootup-time'].details.items||[]).slice(0,8).forEach(i=>console.log(Math.round(i.scripting)+'ms',i.url));"
```

The fix for those is in the host's settings (turn the feature off, or take the
proxy out of the path), not in the code. Also check embedded iframes: one on a
subdomain of the same site shares the page's main thread, while one on another
domain usually doesn't.

### 7. Before / after

Capture the baseline (steps 1–5) BEFORE any change → `lh-before.json`. Make the
changes, rebuild, re-serve, re-run → `lh-after.json`. Report a before→after table.

### 8. Clean up

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
- **Text that fades in above the fold:** an LCP element animated from
  `opacity: 0` can't count as painted until the JavaScript runs. Animate
  position (`transform`) instead of visibility for anything on screen at load.
- Beware **code-splitting on throttled mobile** — the dynamic-import waterfall can
  *regress* LCP vs. a single bundle. Measure it; don't assume it helps.

## Output format

- One table: category scores (and before→after if applicable) + key metrics
  (FCP, LCP, TBT, CLS, SI).
- A grouped punch list of the failing audits with the concrete fix for each.
- If a target is missed, say so plainly and explain what's actually capping it
  (e.g. CSR first-paint floor) rather than padding the number.
- Where the simulated and measured (devtools) numbers disagree, show both and
  say which to believe.

## What NOT to do

- Don't audit the dev server or report a single noisy run.
- Don't claim a fix worked without re-running and showing the new number.
- Don't recommend a fix you didn't see in the failing-audit list.
- Don't blame code for a script the hosting injects, or fix an LCP that only the
  simulation shows.
