// Regenerates the skill list in README.md from skills.json — the single source
// of truth. Run by .github/workflows/sync-readme.yml on every push, so adding a
// skill stays a one-file job (SKILL.md + skills.json); the README updates itself.
//
//   node scripts/gen-readme.mjs
//
// It rewrites only the block between the SKILLS markers; everything else in the
// README is left untouched.

import { readFileSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const START = '<!-- SKILLS:START -->'
const END = '<!-- SKILLS:END -->'

const { skills } = JSON.parse(readFileSync(join(ROOT, 'skills.json'), 'utf8'))

const block = skills
  .map((s) => {
    const lines = [`### [${s.name}](./${s.name}) · ${s.label}`, s.description]
    const meta = []
    if (s.why) meta.push(`**Why:** ${s.why}`)
    if (Array.isArray(s.stack) && s.stack.length) meta.push(`**Stack:** ${s.stack.join(', ')}`)
    if (meta.length) lines.push(meta.join(' · '))
    return lines.join('\n\n')
  })
  .join('\n\n')

const readmePath = join(ROOT, 'README.md')
const readme = readFileSync(readmePath, 'utf8')

const startIdx = readme.indexOf(START)
const endIdx = readme.indexOf(END)
if (startIdx === -1 || endIdx === -1 || endIdx < startIdx) {
  console.error(`Could not find ${START} / ${END} markers in README.md`)
  process.exit(1)
}

const before = readme.slice(0, startIdx + START.length)
const after = readme.slice(endIdx)
const next = `${before}\n\n${block}\n\n${after}`

if (next !== readme) {
  writeFileSync(readmePath, next)
  console.log(`README skill list synced (${skills.length} skills).`)
} else {
  console.log('README already up to date.')
}
