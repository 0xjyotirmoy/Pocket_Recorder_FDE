import { Link, useNavigate } from 'react-router-dom'
import { Empty, ErrorBox, Section, Skeleton, Stat, StatusPill } from '../components.jsx'
import { SOURCE_LABEL, fmtClock, fmtDay, fmtDuration, fmtLongDate, recPath, todayYmd, useApi } from '../lib.js'
import { ItemRow } from './ActionItems.jsx'

export function Chip({ children, onClick, tone = '' }) {
  const cls = `inline-flex items-center rounded-full border border-rule px-2 py-[2px] text-[11.5px] leading-5 ${tone || 'text-muted'}`
  return onClick ? <button onClick={onClick} className={`${cls} hover:border-ink hover:text-ink`}>{children}</button> : <span className={cls}>{children}</span>
}

/** One session (recording) row: time, title, topics, keywords, source. Click opens the session. */
export function RecordingRow({ r, rich = true }) {
  return (
    <li className="fade-in">
      <Link to={recPath(r.id)} className="group grid grid-cols-[52px_minmax(0,1fr)_auto] items-start gap-4 py-4">
        <span className="pt-[3px] font-mono text-[13px] text-muted tnum">{fmtClock(r.recorded_at)}</span>
        <span className="min-w-0">
          <span className="block truncate text-[16px] font-medium group-hover:underline group-hover:decoration-rule group-hover:underline-offset-4">{r.title}</span>
          {rich && r.topics?.length > 0 && (
            <span className="mt-0.5 block truncate font-serif text-[15px] italic text-muted">{r.topics.join(' · ')}</span>
          )}
          {rich && r.keywords?.length > 0 && (
            <span className="mt-2 flex flex-wrap gap-1.5">{r.keywords.slice(0, 6).map((k) => <Chip key={k}>{k}</Chip>)}</span>
          )}
          <span className="mt-2 block font-mono text-[11.5px] text-muted tnum">
            {SOURCE_LABEL[r.source] || r.source} · {r.device_id} · {fmtDuration(r.duration_ms)}{r.open_items ? ` · ${r.open_items} open` : ''}
          </span>
        </span>
        <span className="pt-1"><StatusPill status={r.status} /></span>
      </Link>
    </li>
  )
}

export default function Today() {
  const nav = useNavigate()
  const { data, error, loading, reload, setData } = useApi('/dashboard', { poll: 30000 })
  const q = data?.queue || {}
  const busy = (q.queued || 0) + (q.transcribing || 0) + (q.extracting || 0)
  const t = data?.totals
  const maxKw = Math.max(1, ...(data?.keywords || []).map((k) => k.count))

  return (
    <>
      <header className="mb-10">
        <p className="label mb-3">Overview · {fmtLongDate(todayYmd())}</p>
        <h1 className="font-serif text-[44px] leading-[1.02] tracking-[-0.01em] sm:text-[54px]">Meeting intelligence</h1>
        {t && (
          <dl className="mt-7 grid grid-cols-2 gap-y-5 border-t-2 border-ink pt-4 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Sessions" value={t.meetings} />
            <Stat label="Audio (min)" value={t.minutes} />
            <Stat label="From recorder" value={t.from_device} tone={t.from_device ? 'text-signal' : ''} />
            <Stat label="Upload / import" value={t.from_dashboard + t.from_import} />
            <Stat label="Open items" value={t.open_items} />
            <Stat label="Upcoming" value={t.upcoming} />
          </dl>
        )}
      </header>

      <ErrorBox error={error} onRetry={reload} />

      {busy > 0 && (
        <div className="fade-in mb-10 flex items-center gap-3 border-y border-rule py-3 font-mono text-[12px] text-proc tnum">
          <span className="lamp live" />
          {[q.transcribing && `${q.transcribing} transcribing`, q.extracting && `${q.extracting} analysing`, q.queued && `${q.queued} queued`].filter(Boolean).join(' · ')}
        </div>
      )}

      {loading && !data ? <Skeleton rows={6} /> : data && (data.totals.meetings === 0 ? (
        <Empty title="No sessions yet.">
          Clips from the recorder appear here the moment they arrive. You can also upload audio or import the samples on the <Link className="underline" to="/recordings">Recordings</Link> page.
        </Empty>
      ) : (
        <div className="grid gap-x-12 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div>
            {data.keywords.length > 0 && (
              <Section label="What the recordings are about">
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 py-2">
                  {data.keywords.map((k) => (
                    <button key={k.word} onClick={() => nav(`/search?q=${encodeURIComponent(k.word)}`)}
                      title={`${k.count} session${k.count > 1 ? 's' : ''}`}
                      className="font-serif leading-none text-ink/80 transition hover:text-signal"
                      style={{ fontSize: `${15 + (k.count / maxKw) * 13}px` }}>
                      {k.word}
                    </button>
                  ))}
                </div>
                {data.topics.length > 0 && (
                  <p className="mt-3 text-[13px] text-muted">Topics: {data.topics.map((x) => x.topic).join(' · ')}</p>
                )}
              </Section>
            )}

            <Section label="Sessions" action={<Link to="/recordings" className="text-[12.5px] text-muted hover:text-ink">All recordings →</Link>}>
              {data.days.map((d) => (
                <div key={d.date} className="mb-6">
                  <h3 className="mt-2 flex items-baseline justify-between border-b border-ink pb-1.5">
                    <span className="font-serif text-[21px]">{fmtLongDate(d.date)}</span>
                    <span className="font-mono text-[11px] text-muted">{d.recordings.length} session{d.recordings.length > 1 ? 's' : ''}</span>
                  </h3>
                  <ul className="divide-y divide-rule">{d.recordings.map((r) => <RecordingRow key={r.id} r={r} />)}</ul>
                </div>
              ))}
            </Section>
          </div>

          <div>
            <Section label="Open action items" action={<Link to="/actions" className="text-[12.5px] text-muted hover:text-ink">All →</Link>}>
              {data.open_items.length ? (
                <ul className="divide-y divide-rule">
                  {data.open_items.map((it) => (
                    <ItemRow key={it.id} item={it} compact
                      onChange={() => setData((d) => ({ ...d, open_items: d.open_items.filter((x) => x.id !== it.id) }))} />
                  ))}
                </ul>
              ) : <p className="py-4 text-[14px] text-muted">No open commitments.</p>}
            </Section>

            <Section label="Coming up" action={<Link to="/calendar" className="text-[12.5px] text-muted hover:text-ink">Calendar →</Link>}>
              {data.totals.suggestions > 0 && (
                <Link to="/calendar" className="mb-2 flex items-center justify-between rounded-md border border-dashed border-signal/60 px-3 py-2.5 text-[13.5px] hover:border-signal">
                  <span><span className="font-medium text-signal">{data.totals.suggestions}</span> meeting{data.totals.suggestions > 1 ? 's' : ''} or deadline{data.totals.suggestions > 1 ? 's' : ''} heard in recordings, not on your calendar</span>
                  <span className="text-muted">Review →</span>
                </Link>
              )}
              {data.upcoming.length ? (
                <ul className="divide-y divide-rule">
                  {data.upcoming.map((e) => (
                    <li key={e.id} className="grid grid-cols-[64px_minmax(0,1fr)] gap-3 py-3">
                      <span className="font-mono text-[12px] leading-5 text-muted tnum">{fmtDay(e.start)}<br />{fmtClock(e.start)}</span>
                      <span className="text-[15px]">{e.title}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="py-3 text-[14px] text-muted">Nothing confirmed yet.</p>}
            </Section>

            <Section label="Storage">
              <p className="font-mono text-[12px] leading-6 text-muted tnum">
                {data.storage.audio_files} audio files · {data.storage.audio_mb} MB<br />
                database · {data.storage.db_mb} MB<br />
                <span className="break-all">{data.storage.path}</span>
              </p>
            </Section>
          </div>
        </div>
      ))}
    </>
  )
}
