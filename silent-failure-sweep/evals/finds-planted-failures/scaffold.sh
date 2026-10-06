#!/usr/bin/env bash
# Writes the order service into the empty workspace. Five planted silent failures
# (summarise, inventory, jobs, report, export), three decoys that look similar but
# are handled properly (assistant, search, reminders), and ordinary code around them.
set -euo pipefail
mkdir -p service
cat > service/summarise.ts <<'TS_EOF'
import Anthropic from '@anthropic-ai/sdk'

const client = new Anthropic()

// Summarises a customer's whole order history for the support team.
export async function summariseHistory(history: string): Promise<string> {
  const res = await client.messages.create({
    model: 'claude-sonnet-5',
    max_tokens: 400,
    messages: [{ role: 'user', content: `Summarise this order history:\n\n${history}` }],
  })
  return res.content[0].type === 'text' ? res.content[0].text : ''
}
TS_EOF
cat > service/inventory.ts <<'TS_EOF'
import { db } from './db'

// Checkout calls this to show which allergens a product contains.
export async function allergensFor(productId: string): Promise<string[]> {
  try {
    const rows = await db.query('select allergen from product_allergens where product_id = $1', [productId])
    return rows.map((r: { allergen: string }) => r.allergen)
  } catch {
    return []
  }
}
TS_EOF
cat > service/jobs.ts <<'TS_EOF'
import { db } from './db'
import { sendReceipt } from './email'

export async function processOrder(orderId: string) {
  await db.query("update orders set status = 'processing' where id = $1", [orderId])
  await sendReceipt(orderId)
  await db.query("update orders set status = 'done' where id = $1", [orderId])
}

// Runs every minute.
export async function runQueue() {
  const pending = await db.query("select id from orders where status = 'pending'")
  for (const row of pending) processOrder(row.id)
}
TS_EOF
cat > service/report.ts <<'TS_EOF'
import { postToTeamChannel } from './alerts'

// Nightly: checks that every product has a price, and tells the team.
export async function nightlyPriceCheck(products: { id: string; price?: number }[]) {
  const missing = products.filter((p) => p.price == null)
  await postToTeamChannel(`Price check done. ${missing.length} products couldn't be priced.`)
}
TS_EOF
cat > service/export.ts <<'TS_EOF'
import { db } from './db'

// "Download all orders" button in the admin area. Returns a CSV.
export async function exportOrdersCsv(): Promise<string> {
  const rows = await db.query('select id, customer, total, created_at from orders order by created_at desc limit 1000')
  const lines = rows.map((r: any) => [r.id, r.customer, r.total, r.created_at].join(','))
  return ['id,customer,total,created_at', ...lines].join('\n')
}
TS_EOF
cat > service/assistant.ts <<'TS_EOF'
import Anthropic from '@anthropic-ai/sdk'

const client = new Anthropic()

// Short replies in the in-app help chat.
export async function helpReply(question: string): Promise<string> {
  const res = await client.messages.create({
    model: 'claude-sonnet-5',
    max_tokens: 300,
    messages: [{ role: 'user', content: question }],
  })
  if (res.stop_reason === 'max_tokens') {
    throw new Error('Help reply was cut off at the token limit; not showing a partial answer.')
  }
  return res.content[0].type === 'text' ? res.content[0].text : ''
}
TS_EOF
cat > service/search.ts <<'TS_EOF'
import { db } from './db'
import { alertOnce } from './alerts'

// Product suggestions under the search box. Optional: the page works without them,
// so a failure shows no suggestions, and on-call is paged (at most once an hour).
export async function suggestions(term: string): Promise<string[]> {
  try {
    const rows = await db.query('select name from products where name ilike $1 limit 5', [`${term}%`])
    return rows.map((r: { name: string }) => r.name)
  } catch (err) {
    await alertOnce('search_suggestions_failed', { error: String(err) })
    return []
  }
}
TS_EOF
cat > service/reminders.ts <<'TS_EOF'
import { db } from './db'
import { alert } from './alerts'
import { sendReminderEmail } from './email'

// Sends one reminder. A failed send is marked 'failed' with an attempt count, pages
// on-call after the third failure, and rethrows so the caller's log records it too.
export async function sendReminder(id: string) {
  await db.query("update reminders set status = 'sending' where id = $1", [id])
  try {
    await sendReminderEmail(id)
    await db.query("update reminders set status = 'sent' where id = $1", [id])
  } catch (err) {
    const [row] = await db.query(
      "update reminders set status = 'failed', attempts = attempts + 1 where id = $1 returning attempts", [id])
    if (row.attempts >= 3) await alert('reminder_failed_3_times', { id, error: String(err) })
    throw err
  }
}

// Every 10 minutes: retries reminders that have failed fewer than 3 times, and any
// stuck in 'sending' for over 10 minutes (a crash mid-send).
export async function retryReminders() {
  const rows = await db.query(
    "select id from reminders where (status = 'failed' and attempts < 3) or (status = 'sending' and updated_at < now() - interval '10 minutes')")
  for (const row of rows) {
    try {
      await sendReminder(row.id)
    } catch (err) {
      console.error('reminder retry failed', row.id, err) // already marked failed; pages after 3 tries
    }
  }
}
TS_EOF
cat > service/pricing.ts <<'TS_EOF'
export function orderTotal(items: { price: number; qty: number }[], discountPct = 0): number {
  const subtotal = items.reduce((sum, i) => sum + i.price * i.qty, 0)
  const total = subtotal * (1 - discountPct / 100)
  return Math.round(total * 100) / 100
}
TS_EOF
cat > service/routes.ts <<'TS_EOF'
import { allergensFor } from './inventory'
import { exportOrdersCsv } from './export'
import { suggestions } from './search'
import { helpReply } from './assistant'

export const routes = {
  'GET /products/:id/allergens': (req: { params: { id: string } }) => allergensFor(req.params.id),
  'GET /admin/orders.csv': () => exportOrdersCsv(),
  'GET /search/suggestions': (req: { query: { q: string } }) => suggestions(req.query.q),
  'POST /help': (req: { body: { question: string } }) => helpReply(req.body.question),
}
TS_EOF
cat > service/db.ts <<'TS_EOF'
import { Pool } from 'pg'

const pool = new Pool()

export const db = {
  async query(sql: string, params: unknown[] = []) {
    const { rows } = await pool.query(sql, params)
    return rows
  },
}
TS_EOF
cat > service/email.ts <<'TS_EOF'
async function post(path: string, body: unknown) {
  const res = await fetch(`https://mail.example.com/${path}`, { method: 'POST', body: JSON.stringify(body) })
  if (!res.ok) throw new Error(`Mail ${path} failed: ${res.status}`)
}

export const sendReceipt = (orderId: string) => post('receipts', { orderId })
export const sendReminderEmail = (id: string) => post('reminders', { id })
TS_EOF
cat > service/alerts.ts <<'TS_EOF'
// Pages on-call (alert, alertOnce) or posts to the team's channel (postToTeamChannel).
// A failed page or post throws, so a broken alerting setup is never silent.
async function send(url: string, body: unknown) {
  const res = await fetch(url, { method: 'POST', body: JSON.stringify(body) })
  if (!res.ok) throw new Error(`Alert delivery failed: ${res.status} ${url}`)
}

export const alert = (name: string, detail: Record<string, unknown>) =>
  send('https://alerts.example.com/page', { name, detail })

// At most one page per name per hour (per process), so an outage doesn't page on-call per request.
// The slot is claimed before sending so simultaneous failures page once, and released if the page
// fails, so the next failure tries again instead of being skipped for an hour.
const lastPaged = new Map<string, number>()
export async function alertOnce(name: string, detail: Record<string, unknown>) {
  const now = Date.now()
  if (now - (lastPaged.get(name) ?? 0) < 60 * 60 * 1000) return
  lastPaged.set(name, now)
  try {
    await alert(name, detail)
  } catch (err) {
    lastPaged.delete(name)
    throw err
  }
}

export const postToTeamChannel = (text: string) =>
  send('https://chat.example.com/hooks/team', { text })
TS_EOF
