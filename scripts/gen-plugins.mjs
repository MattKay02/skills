// Generates the install manifests from skills.json and each SKILL.md, so adding a
// skill stays a one-file job (SKILL.md + a skills.json entry) and the installers
// pick it up on push:
//
//   <skill>/.claude-plugin/plugin.json   each skill folder is a single-skill Claude
//                                        Code plugin (SKILL.md at the plugin root)
//   .claude-plugin/marketplace.json      lists them, so people can run
//                                        /plugin marketplace add MattKay02/skills
//                                        /plugin install <skill>@mattkay02
//
// `npx skills add MattKay02/skills` needs nothing extra: it reads the SKILL.md files.
// Run by .github/workflows/sync.yml on push, or by hand:  node scripts/gen-plugins.mjs

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const REPO = 'https://github.com/MattKay02/skills'
const MARKETPLACE = 'mattkay02'
const AUTHOR = { name: 'Matthew Kay', url: 'https://github.com/MattKay02' }

const { skills } = JSON.parse(readFileSync(join(ROOT, 'skills.json'), 'utf8'))

/** The first sentence of a description: the line people see when browsing plugins. */
const firstSentence = (text) => (text.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? text).trim()

/** The `name` in a SKILL.md's frontmatter, which must match its folder. */
function skillName(dir) {
  const file = join(ROOT, dir, 'SKILL.md')
  if (!existsSync(file)) throw new Error(`skills.json lists "${dir}" but ${dir}/SKILL.md doesn't exist`)
  const front = readFileSync(file, 'utf8').split(/\r?\n---\r?\n/)[0]
  // An unquoted YAML value can't contain ": " or " #". Installers then fail to parse
  // the frontmatter and skip the skill without saying so, so fail loudly here instead.
  const desc = front.match(/^description:\s*(.*)$/m)?.[1] ?? ''
  if (!/^["']/.test(desc) && /: | #/.test(desc)) {
    throw new Error(`${dir}/SKILL.md: the description contains ": " or " #", which breaks its YAML and makes installers skip the skill. Reword it or wrap it in quotes.`)
  }
  return front.match(/^name:\s*(.+)$/m)?.[1].trim()
}

const write = (path, data) => {
  mkdirSync(dirname(path), { recursive: true })
  const next = JSON.stringify(data, null, 2) + '\n'
  const prev = existsSync(path) ? readFileSync(path, 'utf8') : ''
  if (next !== prev) writeFileSync(path, next)
  return next !== prev
}

let changed = 0
const entries = skills.map((s) => {
  const name = skillName(s.name)
  if (name !== s.name) throw new Error(`${s.name}/SKILL.md is named "${name}"; the folder, SKILL.md and skills.json must agree`)
  const description = firstSentence(s.description)
  // No "version": installs then track commits, so a push reaches people on their next update.
  changed += write(join(ROOT, s.name, '.claude-plugin', 'plugin.json'), {
    name: s.name,
    description,
    author: AUTHOR,
    homepage: `${REPO}/tree/main/${s.name}`,
    repository: REPO,
    license: 'MIT',
    keywords: [...new Set([s.label, ...(s.stack ?? [])].map((k) => k.toLowerCase().replace(/\s+/g, '-')))],
  })
  return { name: s.name, source: `./${s.name}`, description }
})

changed += write(join(ROOT, '.claude-plugin', 'marketplace.json'), {
  name: MARKETPLACE,
  owner: AUTHOR,
  description: 'Claude Code skills I build for my own workflow: UI evidence and review, mobile QA and CI, web performance, reliability sweeps and motion design. Each skill installs on its own.',
  plugins: entries,
})

console.log(changed ? `Install manifests synced (${skills.length} skills).` : 'Install manifests already up to date.')
