import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ProposeButton } from '../ActionCard.jsx'
import { Empty, ErrorBox, PageHead, Skeleton, TimeLink } from '../components.jsx'
import { api, dueLabel, fmtDay, isOverdue, mmss, recPath, useApi } from '../lib.js'

/** One commitment heard in a recording. Tick = done (moves to the Done tab). Follow-up actions open a
 *  confirm card: draft an email (saved, never sent) or put the deadline on the calendar. */
export function ItemRow({ item, onChange, showSource = true, compact = false }) {
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(null) // 'email' | 'schedule'
  const done = item.status === 'done'
  async function toggle() {
    setBusy(true)
    try {
      const next = await api(`/action-items/${item.id}`, { method: 'PATCH', body: { status: done ? 'open' : 'done' } })
      onChange?.({ ...item, status: next.status }, item)
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <li className="fade-in py-3.5">
      <div className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-3">
        <button onClick={toggle} disabled={busy} title={done ? 'Mark as open' : 'Mark as done'}
          aria-label={done ? 'Mark as open' : 'Mark as done'}
          className={`mt-0.5 grid size-[18px] place-items-center rounded-[4px] border transition ${
            done ? 'border-done bg-done text-paper' : 'border-muted/60 hover:border-ink'}`}>
          {done && <svg viewBox="0 0 12 12" className="size-3"><path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" strokeWidth="1.8" /></svg>}
        </button>
        <div className="min-w-0">
          <p className={`text-[15px] leading-snug ${done ? 'text-muted line-through decoration-rule' : ''}`}>
            <span className="font-medium">{item.who}</span><span className="text-muted"> — </span>{item.what}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[12.5px] text-muted">
            {showSource && item.recording_title && (
              <>
                <Link to={recPath(item.recording_id)} className="hover:text-ink">{item.recording_title}</Link>
                <span>·</span><span>{fmtDay(item.recorded_at)}</span><span>·</span>
              </>
            )}
            {item.start_s != null && <TimeLink recordingId={item.recording_id} start={item.start_s}>said at {mmss(item.start_s)}</TimeLink>}
            {!compact && !done && (
              <>
                <span>·</span>
                <button onClick={() => setOpen(open === 'email' ? null : 'email')} className="hover:text-ink">Draft email</button>
                <span>·</span>
                <button onClick={() => setOpen(open === 'schedule' ? null : 'schedule')} className="hover:text-ink">Add to calendar</button>
              </>
            )}
          </p>
        </div>
        <span className={`whitespace-nowrap pt-0.5 font-mono text-[12px] tnum ${isOverdue(item) ? 'text-signal' : 'text-muted'}`}>
          {isOverdue(item) ? 'Overdue · ' : ''}{dueLabel(item)}
        </span>
      </div>
      {open && (
        <div className="ml-[34px]">
          <ProposeButton key={open} variant="ink"
            endpoint={`/action-items/${item.id}/${open === 'email' ? 'email' : 'schedule'}`}>
            {open === 'email' ? 'Prepare follow-up email' : 'Prepare calendar event'}
          </ProposeButton>
        </div>
      )}
    </li>
  )
}

const FILTERS = [['open', 'Open'], ['done', 'Done'], ['', 'All']]

export default function ActionItems() {
  const [filter, setFilter] = useState('open')
  const [undo, setUndo] = useState(null)
  const { data, error, loading, reload, setData } = useApi(`/action-items${filter ? `?status=${filter}` : ''}`)
  function update(it, before) {
    setData((list) => (filter && it.status !== filter ? list.filter((x) => x.id !== it.id) : list.map((x) => (x.id === it.id ? it : x))))
    if (filter && it.status !== filter) setUndo({ it, before })
  }
  async function doUndo() {
    const { before } = undo
    setUndo(null)
    await api(`/action-items/${before.id}`, { method: 'PATCH', body: { status: before.status } })
    reload()
  }
  return (
    <>
      <PageHead kicker="Commitments heard in your recordings" title="Action items">
        <div className="flex rounded-md border border-rule p-0.5">
          {FILTERS.map(([v, l]) => (
            <button key={l} onClick={() => { setFilter(v); setUndo(null) }}
              className={`rounded px-3 py-1 text-[13px] transition ${filter === v ? 'bg-ink text-paper' : 'text-muted hover:text-ink'}`}>{l}</button>
          ))}
        </div>
      </PageHead>
      <p className="-mt-6 mb-6 max-w-2xl text-[13.5px] text-muted">
        Tick a box when it's done; it moves to <b className="font-medium text-ink">Done</b>. Use <b className="font-medium text-ink">Draft email</b> to write a follow-up
        (saved to Drafts, never sent) or <b className="font-medium text-ink">Add to calendar</b> to put the deadline on your calendar. Both ask you to confirm first.
      </p>
      {undo && (
        <div className="fade-in mb-4 flex items-center justify-between rounded-md border border-rule bg-surface px-4 py-2.5 text-[13.5px]">
          <span>Marked “{undo.it.what}” as {undo.it.status}.</span>
          <button onClick={doUndo} className="font-medium text-signal hover:underline">Undo</button>
        </div>
      )}
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Skeleton /> : data?.length ? (
        <ul className="divide-y divide-rule">{data.map((it) => <ItemRow key={it.id} item={it} onChange={update} />)}</ul>
      ) : (
        <Empty title={filter === 'open' ? 'Nothing open.' : 'No action items yet.'}>
          Action items appear once recordings are transcribed and analysed. Each one links back to the moment it was said.
        </Empty>
      )}
    </>
  )
}
