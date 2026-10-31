import { Link } from 'react-router-dom'
import { fmtWhen, mmss, recPath } from './lib.js'

const STATUS = {
  queued: { text: 'Queued', cls: 'text-muted', live: false },
  transcribing: { text: 'Transcribing', cls: 'text-proc', live: true },
  extracting: { text: 'Analysing', cls: 'text-proc', live: true },
  done: { text: 'Ready', cls: 'text-done', live: false },
  failed: { text: 'Failed', cls: 'text-signal', live: false },
}

export function StatusPill({ status }) {
  const s = STATUS[status] || { text: status, cls: 'text-muted' }
  return (
    <span className={`inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.1em] ${s.cls}`}>
      <span className={`lamp !size-1.5 ${s.live ? 'live' : ''}`} />
      {s.text}
    </span>
  )
}

export function PageHead({ kicker, title, children }) {
  return (
    <header className="mb-10 border-b border-rule pb-6">
      {kicker && <p className="label mb-3">{kicker}</p>}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="font-serif text-[40px] leading-[1.05] tracking-[-0.01em] sm:text-[48px]">{title}</h1>
        {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
      </div>
    </header>
  )
}

export function Section({ label, action, children, className = '' }) {
  return (
    <section className={`mb-12 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-4 border-b border-rule pb-2">
        <h2 className="label">{label}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Button({ children, variant = 'ghost', className = '', ...rest }) {
  const styles = {
    primary: 'bg-signal text-white border-signal hover:brightness-110',
    ink: 'bg-ink text-paper border-ink hover:opacity-90',
    ghost: 'bg-transparent text-ink border-rule hover:border-ink',
  }
  return (
    <button
      className={`inline-flex h-9 items-center gap-2 rounded-md border px-3.5 text-[13px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}

export function SourceChip({ s }) {
  return (
    <Link
      to={`${recPath(s.recording_id)}?t=${Math.floor(s.start_s || 0)}`}
      title={s.text}
      className="inline-flex max-w-full items-center gap-2 rounded-md border border-rule bg-surface px-2.5 py-1 font-mono text-[11.5px] text-muted transition hover:border-ink hover:text-ink"
    >
      <span className="size-1.5 shrink-0 rounded-full bg-signal" />
      <span className="truncate text-ink">{s.title}</span>
      <span className="shrink-0">· {fmtWhen(s.recorded_at)} · at {mmss(s.start_s)}</span>
    </Link>
  )
}

export function TimeLink({ recordingId, start, children }) {
  if (start == null) return children || null
  return (
    <Link to={`${recPath(recordingId)}?t=${Math.floor(start)}`} className="font-mono text-[11.5px] text-muted hover:text-signal tnum">
      {children || mmss(start)}
    </Link>
  )
}

/** Renders FTS snippets safely: text stays text, \u0002…\u0003 become <mark>. */
export function Snippet({ text }) {
  const out = []
  const re = /\u0002(.*?)\u0003/g
  let last = 0
  let m
  let i = 0
  while ((m = re.exec(text || ''))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(<mark key={i++}>{m[1]}</mark>)
    last = re.lastIndex
  }
  out.push((text || '').slice(last))
  return <>{out}</>
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="my-4 flex items-start justify-between gap-4 border-l-2 border-signal bg-surface px-4 py-3 text-[14px]">
      <div>
        <p className="label mb-1 !text-signal">Something went wrong</p>
        <p>{error}</p>
      </div>
      {onRetry && <Button onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function Empty({ title, children }) {
  return (
    <div className="border border-dashed border-rule px-6 py-10 text-center">
      <p className="font-serif text-xl">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-[14px] text-muted">{children}</div>}
    </div>
  )
}

export function Skeleton({ rows = 4 }) {
  return (
    <div className="divide-y divide-rule">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 py-4">
          <div className="h-3 w-12 animate-pulse rounded bg-wash" />
          <div className="h-3 flex-1 animate-pulse rounded bg-wash" />
          <div className="h-3 w-16 animate-pulse rounded bg-wash" />
        </div>
      ))}
    </div>
  )
}

export function Stat({ label, value, tone = '' }) {
  return (
    <div className="pr-4">
      <dt className="label">{label}</dt>
      <dd className={`mt-1 font-serif text-[34px] leading-none tnum ${tone}`}>{value}</dd>
    </div>
  )
}

const SUN = <svg viewBox="0 0 16 16" className="size-3.5"><circle cx="8" cy="8" r="3" fill="currentColor" /><g stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">{[0, 45, 90, 135, 180, 225, 270, 315].map((a) => <line key={a} x1="8" y1="1.6" x2="8" y2="3" transform={`rotate(${a} 8 8)`} />)}</g></svg>
const MOON = <svg viewBox="0 0 16 16" className="size-3.5"><path d="M13.5 9.6A5.6 5.6 0 0 1 6.4 2.5a5.6 5.6 0 1 0 7.1 7.1z" fill="currentColor" /></svg>
const AUTO = <svg viewBox="0 0 16 16" className="size-3.5"><circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" strokeWidth="1.4" /><path d="M8 2.4a5.6 5.6 0 0 1 0 11.2z" fill="currentColor" /></svg>

export function ThemeToggle({ theme, setTheme, compact = false }) {
  const opts = [['light', 'Day', SUN], ['dark', 'Night', MOON], ['auto', 'Auto', AUTO]]
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-full border border-rule bg-surface p-0.5">
      {opts.map(([v, label, icon]) => (
        <button key={v} role="radio" aria-checked={theme === v} title={`${label} mode`} onClick={() => setTheme(v)}
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] transition ${
            theme === v ? 'bg-ink text-paper' : 'text-muted hover:text-ink'}`}>
          {icon}{!compact && <span>{label}</span>}
        </button>
      ))}
    </div>
  )
}
