// Writes tests.json, a summary of each skill's latest eval results, so the portfolio
// can show test status without anyone typing it. Run it after running evals:
//
//   cd <skill> && claude plugin eval . [--scaffold]     (results stay local, gitignored)
//   node scripts/gen-tests.mjs                          (then commit tests.json)
//
// For each case it keeps the newest complete run with at least 3 runs per arm, so a
// quick one-run check while debugging never replaces a real result.

import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const MIN_RUNS = 3
const { skills } = JSON.parse(readFileSync(join(ROOT, 'skills.json'), 'utf8'))

const mean = (runs) => (runs?.length ? runs.reduce((s, r) => s + r.score, 0) / runs.length : null)
const round = (n) => (n === null ? null : Math.round(n * 100) / 100)
/** A trigger case only checks whether the skill loaded; anything else is a behaviour case. */
const kindOf = (c) => (c.graders.every((g) => g.type === 'tool_used' && g.config?.tool === 'Skill') ? 'trigger' : 'behaviour')

const out = { generated: new Date().toISOString().slice(0, 10), skills: {} }
for (const { name } of skills) {
  const dir = join(ROOT, name, 'evals', 'results')
  if (!existsSync(dir)) continue
  const latest = new Map()
  for (const run of readdirSync(dir).sort()) {
    const file = join(dir, run, 'aggregate-result.json')
    if (!existsSync(file)) continue
    const result = JSON.parse(readFileSync(file, 'utf8'))
    if (result.partial) continue
    for (const c of result.cases) {
      const runs = c.arms.with?.length ?? 0
      if (runs < MIN_RUNS) continue
      latest.set(c.name, {
        name: c.name,
        kind: kindOf(c),
        runs,
        with: round(mean(c.arms.with)),
        without: round(mean(c.arms.without)),
        date: result.startedAt.slice(0, 10),
      })
    }
  }
  if (latest.size) {
    const cases = [...latest.values()]
    out.skills[name] = { lastRun: cases.map((c) => c.date).sort().at(-1), cases }
  }
}

writeFileSync(join(ROOT, 'tests.json'), JSON.stringify(out, null, 2) + '\n')
const counted = Object.values(out.skills).reduce((n, s) => n + s.cases.length, 0)
console.log(`tests.json: ${counted} cases across ${Object.keys(out.skills).length} skills.`)
