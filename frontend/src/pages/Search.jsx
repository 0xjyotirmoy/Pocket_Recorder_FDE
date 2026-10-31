import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Empty, ErrorBox, PageHead, Skeleton, Snippet } from '../components.jsx'
import { api, fmtLongDate, fmtWhen, mmss, recPath } from '../lib.js'
import { RecordingRow } from './Today.jsx'

const EXAMPLES = ['purchase order', 'nov 3', 'priya', 'yesterday', 'last week', 'delivery 3 nov']

export default function Search() {
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') || '')
  const [state, setState] = useState({ res: null, error: null, loading: false })

  useEffect(() => {
    const term = q.trim()
    setParams(term ? { q: term } : {}, { replace: true })
    if (!term) { setState({ res: null, error: null, loading: false }); return }
    setState((s) => ({ ...s, loading: true }))
    const h = setTimeout(async () => {
      try {
        setState({ res: await api(`/search?q=${encodeURIComponent(term)}`), error: null, loading: false })
      } catch (e) {
        setState({ res: null, error: e.message, loading: false })
      }
    }, 250)
    return () => clearTimeout(h)
  }, [q])

  const res = state.res
  const groups = useMemo(() => {
    const m = new Map()
    for (const h of res?.hits || []) {
      if (!m.has(h.recording_id)) m.set(h.recording_id, { title: h.title, recorded_at: h.recorded_at, hits: [] })
      m.get(h.recording_id).hits.push(h)
    }
    return [...m.entries()]
  }, [res])
  const dateLabel = res?.date_from
    ? res.date_to && res.date_to !== res.date_from
      ? `${fmtLongDate(res.date_from, { day: 'numeric', month: 'short' })} – ${fmtLongDate(res.date_to, { day: 'numeric', month: 'short' })}`
      : fmtLongDate(res.date_from)
    : null
  const nothing = res && !res.recordings.length && !res.hits.length

  return (
    <>
      <PageHead kicker="Words, names, topics or dates" title="Search" />
      <div className="relative mb-4">
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="purchase order, priya, nov 3, last week…"
          className="w-full border-0 border-b-2 border-ink bg-transparent pb-3 font-serif text-[28px] text-ink placeholder:text-muted/50 focus:outline-none" />
        {res && <span className="absolute right-0 bottom-4 font-mono text-[11.5px] text-muted tnum">{res.recordings.length} sessions · {res.hits.length} lines</span>}
      </div>
      {!q.trim() && (
        <p className="mb-10 flex flex-wrap items-center gap-2 text-[13px] text-muted">
          Try:{EXAMPLES.map((e) => <button key={e} onClick={() => setQ(e)} className="rounded-full border border-rule px-2.5 py-0.5 hover:border-ink hover:text-ink">{e}</button>)}
        </p>
      )}
      {dateLabel && (
        <p className="mb-8 font-mono text-[12px] text-muted">
          Date: <span className="text-signal">{dateLabel}</span>{res.text ? <> · words: <span className="text-ink">{res.text}</span></> : ''}
        </p>
      )}
      <ErrorBox error={state.error} />
      {state.loading && !res ? <Skeleton /> : res && (nothing ? (
        <Empty title={`Nothing matches “${q.trim()}”.`}>
          {dateLabel ? `No sessions on ${dateLabel}${res.text ? ` mentioning “${res.text}”` : ''}.` : 'Try fewer or different words, a name, or a date like “nov 3”.'}
        </Empty>
      ) : (
        <>
          {res.recordings.length > 0 && (
            <section className="mb-10">
              <h2 className="label mb-1 border-b border-rule pb-2">Sessions {dateLabel ? `on ${dateLabel}` : 'matching'}</h2>
              <ul className="divide-y divide-rule">{res.recordings.map((r) => <RecordingRow key={r.id} r={r} />)}</ul>
            </section>
          )}
          {groups.length > 0 && (
            <section>
              <h2 className="label mb-3 border-b border-rule pb-2">Said in recordings</h2>
              {groups.map(([rid, g]) => (
                <div key={rid} className="fade-in mb-8">
                  <div className="mb-1 flex items-baseline justify-between border-b border-rule pb-2">
                    <Link to={recPath(rid)} className="font-serif text-[21px] hover:underline hover:decoration-rule hover:underline-offset-4">{g.title}</Link>
                    <span className="font-mono text-[11.5px] text-muted">{fmtWhen(g.recorded_at)}</span>
                  </div>
                  <ul className="divide-y divide-rule">
                    {g.hits.map((h) => (
                      <li key={h.segment_id}>
                        <Link to={`${recPath(rid)}?t=${Math.floor(h.start_s)}`} className="grid grid-cols-[56px_minmax(0,1fr)] gap-3 py-3 hover:bg-surface/60">
                          <span className="pt-[3px] font-mono text-[11.5px] text-muted tnum">{mmss(h.start_s)}</span>
                          <span className="text-[15px] leading-relaxed"><Snippet text={h.snippet} /></span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          )}
        </>
      ))}
    </>
  )
}
