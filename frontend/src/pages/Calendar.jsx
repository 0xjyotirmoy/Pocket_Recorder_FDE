import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ActionCard } from '../ActionCard.jsx'
import { Button, Empty, ErrorBox, PageHead, Skeleton, TimeLink } from '../components.jsx'
import { api, fmtClock, fmtDay, fmtLongDate, recPath, todayYmd, useApi } from '../lib.js'

const pad = (n) => String(n).padStart(2, '0')
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

function weekDays(offset) {
  const now = new Date()
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7) + offset * 7)
  return Array.from({ length: 7 }, (_, i) => ymd(new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i)))
}
function weekOffsetFor(date) {
  const now = new Date()
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7))
  const [y, m, d] = date.split('-').map(Number)
  return Math.floor((new Date(y, m - 1, d) - monday) / (7 * 864e5))
}

function EventBlock({ e, onDelete }) {
  return (
    <div className="group fade-in mb-2 border-l-2 border-signal bg-surface px-2.5 py-2">
      <p className="font-mono text-[11px] text-muted tnum">{fmtClock(e.start)}–{fmtClock(e.end)}</p>
      <p className="text-[13.5px] leading-snug">{e.title}</p>
      {e.attendees?.length > 0 && <p className="mt-0.5 truncate text-[11.5px] text-muted">{e.attendees.join(', ')}</p>}
      <div className="mt-1 flex gap-3 text-[11.5px] text-muted opacity-0 transition group-hover:opacity-100">
        {e.source_recording_id && <Link to={recPath(e.source_recording_id)} className="hover:text-ink">Source</Link>}
        <button onClick={() => onDelete(e)} className="hover:text-signal">Delete</button>
      </div>
    </div>
  )
}

function SuggestionBlock({ s, onPick }) {
  return (
    <button onClick={() => onPick(s)} title="Heard in a recording. Click to review and add."
      className="fade-in mb-2 block w-full border border-dashed border-signal/60 px-2.5 py-2 text-left transition hover:border-signal">
      <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-signal">{s.kind === 'deadline' ? 'Deadline' : 'Heard'} · {fmtClock(s.start)}</p>
      <p className="text-[13px] leading-snug text-muted">{s.title}</p>
    </button>
  )
}

export default function Calendar() {
  const { data, error, loading, reload, setData } = useApi('/calendar')
  const { data: sugg, reload: reloadSugg } = useApi('/calendar/suggestions')
  const [offset, setOffset] = useState(0)
  const [pending, setPending] = useState(null) // {suggestion, action}
  const days = weekDays(offset)
  const today = todayYmd()
  const byDay = useMemo(() => {
    const m = {}
    for (const e of data || []) (m[e.start.slice(0, 10)] ||= { events: [], sugg: [] }).events.push(e)
    for (const s of sugg || []) (m[s.date] ||= { events: [], sugg: [] }).sugg.push(s)
    return m
  }, [data, sugg])
  const upcoming = (data || []).filter((e) => e.start.slice(0, 10) >= today)

  async function remove(e) {
    if (!confirm(`Delete “${e.title}”?`)) return
    try { await api(`/calendar/${e.id}`, { method: 'DELETE' }); setData((d) => d.filter((x) => x.id !== e.id)); reloadSugg() } catch (err) { alert(err.message) }
  }
  async function pick(s) {
    try { setPending({ s, action: await api(`/calendar/suggestions/${encodeURIComponent(s.ref)}`, { method: 'POST' }) }) } catch (e) { alert(e.message) }
  }

  return (
    <>
      <PageHead kicker="Schedule" title="Calendar">
        <Button onClick={() => setOffset((o) => o - 1)} aria-label="Previous week">←</Button>
        <Button onClick={() => setOffset(0)} disabled={offset === 0}>This week</Button>
        <Button onClick={() => setOffset((o) => o + 1)} aria-label="Next week">→</Button>
      </PageHead>
      <ErrorBox error={error} onRetry={reload} />

      {sugg?.length > 0 && (
        <section className="mb-10">
          <h2 className="label mb-1 border-b border-rule pb-2">Heard in recordings · not on your calendar yet</h2>
          <ul className="divide-y divide-rule">
            {sugg.map((s) => (
              <li key={s.ref} className="py-3">
                <div className="grid grid-cols-[96px_minmax(0,1fr)_auto] items-start gap-4">
                  <span className="font-mono text-[12px] leading-5 text-muted tnum">
                    <button className="hover:text-ink" onClick={() => setOffset(weekOffsetFor(s.date))}>{fmtDay(s.date)} · {fmtClock(s.start)}</button>
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[15px]">{s.title}</span>
                    <span className="mt-0.5 block text-[12.5px] text-muted">
                      {s.kind === 'deadline' ? 'Deadline' : 'Meeting'}{s.said_as ? ` · said as “${s.said_as}”` : ''} ·{' '}
                      <Link to={recPath(s.recording_id)} className="hover:text-ink">{s.recording_title}</Link>
                      {s.attendees?.length ? ` · ${s.attendees.join(', ')}` : ''}
                    </span>
                  </span>
                  {pending?.s.ref !== s.ref && <Button onClick={() => pick(s)}>Review & add</Button>}
                </div>
                {pending?.s.ref === s.ref && (
                  <ActionCard action={pending.action} onClose={() => setPending(null)}
                    onResolved={(r) => { if (r.status === 'confirmed') { reload(); reloadSugg() } setTimeout(() => setPending(null), 1500) }} />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="label mb-3">{fmtLongDate(days[0], { day: 'numeric', month: 'long' })} – {fmtLongDate(days[6], { day: 'numeric', month: 'long', year: 'numeric' })}</p>
      {loading && !data ? <Skeleton /> : (
        <div className="mb-12 grid grid-cols-1 border-t border-ink sm:grid-cols-7">
          {days.map((d) => (
            <div key={d} className={`min-h-[150px] border-b border-rule p-2 sm:border-r sm:last:border-r-0 ${d === today ? 'bg-surface' : ''}`}>
              <p className={`mb-2 font-mono text-[11px] uppercase tracking-[0.08em] tnum ${d === today ? 'text-signal' : 'text-muted'}`}>
                {fmtLongDate(d, { weekday: 'short' })} {fmtDay(d)}
              </p>
              {(byDay[d]?.events || []).map((e) => <EventBlock key={e.id} e={e} onDelete={remove} />)}
              {(byDay[d]?.sugg || []).map((s) => <SuggestionBlock key={s.ref} s={s} onPick={pick} />)}
            </div>
          ))}
        </div>
      )}

      <h2 className="label mb-3 border-b border-rule pb-2">Confirmed · upcoming</h2>
      {upcoming.length ? (
        <ul className="divide-y divide-rule">
          {upcoming.map((e) => (
            <li key={e.id} className="grid grid-cols-[110px_minmax(0,1fr)_auto] items-baseline gap-4 py-3">
              <span className="font-mono text-[12px] text-muted tnum">{fmtDay(e.start)} · {fmtClock(e.start)}</span>
              <span className="text-[15px]">
                {e.title}{e.attendees?.length ? <span className="text-muted"> · {e.attendees.join(', ')}</span> : null}
                {e.source_recording_id && <Link to={recPath(e.source_recording_id)} className="ml-2 text-[12px] text-muted hover:text-ink">source</Link>}
              </span>
              <button onClick={() => remove(e)} className="text-[12px] text-muted hover:text-signal">Delete</button>
            </li>
          ))}
        </ul>
      ) : (
        <Empty title="Nothing confirmed yet.">
          Review the meetings heard in your recordings above, or ask the assistant: “Schedule the review call on 5 Nov at 3pm with Ravi”.
        </Empty>
      )}
    </>
  )
}
