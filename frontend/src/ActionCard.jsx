import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from './components.jsx'
import { api, fmtWhen, fromLocalInput, toLocalInput } from './lib.js'

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="label mb-1 block">{label}</span>
      {children}
    </label>
  )
}
export const inputCls = 'w-full rounded-md border border-rule bg-paper px-3 py-2 text-[14px] text-ink focus:border-ink focus:outline-none'

/** Proposal card: the user reviews/edits, then confirms. Nothing is saved before Confirm; emails are never sent. */
export function ActionCard({ action, onResolved, onClose }) {
  const [args, setArgs] = useState(action.args)
  const [state, setState] = useState(action.status || 'pending')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const cal = action.tool === 'create_calendar_event'
  const set = (k) => (e) => setArgs((a) => ({ ...a, [k]: e.target.value }))

  async function resolve(kind) {
    setErr(null)
    setBusy(true)
    try {
      const body = cal
        ? { ...args, attendees: Array.isArray(args.attendees) ? args.attendees : String(args.attendees || '').split(',').map((s) => s.trim()).filter(Boolean) }
        : args
      const r = await api(`/actions/${action.id}/${kind}`, { method: 'POST', body: kind === 'confirm' ? { args: body } : undefined })
      setState(r.status)
      onResolved?.(r)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (state === 'confirmed')
    return (
      <div className="fade-in mt-3 border-l-2 border-done pl-4 text-[14px]">
        <p className="label mb-1 !text-done">{cal ? 'Added to calendar' : 'Draft saved — never sent'}</p>
        <p>
          {cal ? `${args.title} · ${fmtWhen(args.start)}` : `${args.subject} → ${args.to}`}{' '}
          <Link to={cal ? '/calendar' : '/drafts'} className="text-muted underline decoration-rule underline-offset-4 hover:text-ink">Open {cal ? 'calendar' : 'drafts'}</Link>
        </p>
      </div>
    )
  if (state === 'rejected')
    return (
      <p className="mt-3 font-mono text-[12px] text-muted">
        Discarded. Nothing was saved.{onClose && <button onClick={onClose} className="ml-2 underline">Close</button>}
      </p>
    )

  return (
    <div className="fade-in mt-4 rounded-lg border border-ink bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="label">{cal ? 'Confirm calendar event' : 'Confirm email draft'} · nothing is saved until you confirm</p>
        {onClose && <button onClick={onClose} aria-label="Close" className="text-muted hover:text-ink">×</button>}
      </div>
      <div className="grid gap-3">
        {cal ? (
          <>
            <Field label="Title"><input className={inputCls} value={args.title || ''} onChange={set('title')} /></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Starts"><input type="datetime-local" className={inputCls} value={toLocalInput(args.start)}
                onChange={(e) => setArgs((a) => ({ ...a, start: fromLocalInput(e.target.value, a.start) }))} /></Field>
              <Field label="Ends"><input type="datetime-local" className={inputCls} value={toLocalInput(args.end)}
                onChange={(e) => setArgs((a) => ({ ...a, end: fromLocalInput(e.target.value, a.end) }))} /></Field>
            </div>
            <Field label="Attendees (comma separated)">
              <input className={inputCls} value={Array.isArray(args.attendees) ? args.attendees.join(', ') : args.attendees || ''} onChange={set('attendees')} />
            </Field>
            {args.notes && <p className="text-[12.5px] text-muted">{args.notes}</p>}
          </>
        ) : (
          <>
            <Field label="To"><input className={inputCls} placeholder="name@company.com" value={args.to || ''} onChange={set('to')} /></Field>
            <Field label="Subject"><input className={inputCls} value={args.subject || ''} onChange={set('subject')} /></Field>
            <Field label="Body"><textarea rows={8} className={`${inputCls} leading-relaxed`} value={args.body || ''} onChange={set('body')} /></Field>
          </>
        )}
      </div>
      {err && <p className="mt-3 text-[13px] text-signal">{err}</p>}
      <div className="mt-4 flex gap-2">
        <Button variant="primary" disabled={busy} onClick={() => resolve('confirm')}>{cal ? 'Add to calendar' : 'Save draft'}</Button>
        <Button disabled={busy} onClick={() => resolve('reject')}>Discard</Button>
      </div>
    </div>
  )
}

/** A button that asks the server for a proposal (POST endpoint returning a pending action) and shows the card. */
export function ProposeButton({ endpoint, children, variant = 'ghost', className = '', onDone }) {
  const [action, setAction] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  async function go() {
    setBusy(true)
    setErr(null)
    try { setAction(await api(endpoint, { method: 'POST' })) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className={className}>
      {!action && <Button variant={variant} onClick={go} disabled={busy}>{busy ? 'Preparing…' : children}</Button>}
      {err && <p className="mt-1 text-[12.5px] text-signal">{err}</p>}
      {action && <ActionCard action={action} onResolved={onDone} onClose={() => setAction(null)} />}
    </div>
  )
}
