import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Button, Empty, ErrorBox, Skeleton, StatusPill, TimeLink } from '../components.jsx'
import { SOURCE_LABEL, api, audioUrl, fmtDay, fmtDuration, fmtWhen, mmss, recPath, useApi, useWaveform } from '../lib.js'
import { ItemRow } from './ActionItems.jsx'
import { Chip } from './Today.jsx'
import { ProposeButton } from '../ActionCard.jsx'

function Waveform({ peaks, pct, duration, markers, onSeek }) {
  const [hover, setHover] = useState(null)
  const pos = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width))
  }
  const n = peaks?.length || 0
  return (
    <div className="relative h-14 cursor-pointer select-none" role="slider" aria-label="Seek"
      aria-valuemin={0} aria-valuemax={Math.round(duration || 0)} aria-valuenow={Math.round((pct / 100) * (duration || 0))}
      onClick={(e) => onSeek(pos(e) * duration)} onMouseMove={(e) => setHover(pos(e))} onMouseLeave={() => setHover(null)}>
      {n > 0 ? (
        <svg viewBox={`0 0 ${n * 3} 40`} preserveAspectRatio="none" className="absolute inset-x-0 top-0 h-11 w-full">
          {peaks.map((v, i) => {
            const h = v * 38
            const played = (i / n) * 100 < pct
            return <rect key={i} x={i * 3} y={20 - h / 2} width="2" height={h} rx="1"
              style={{ fill: played ? 'var(--color-signal)' : 'color-mix(in oklab, var(--color-muted) 45%, transparent)' }} />
          })}
        </svg>
      ) : (
        <div className="absolute inset-x-0 top-[21px] h-[2px] bg-rule">
          <div className="h-full bg-signal" style={{ width: `${pct}%` }} />
        </div>
      )}
      {hover != null && duration > 0 && (
        <div className="pointer-events-none absolute top-0 h-11 w-px bg-ink/60" style={{ left: `${hover * 100}%` }}>
          <span className="absolute -top-5 -translate-x-1/2 rounded bg-ink px-1.5 py-0.5 font-mono text-[10px] text-paper tnum">{mmss(hover * duration)}</span>
        </div>
      )}
      {/* moments: where tasks and meetings were said */}
      {duration > 0 && markers.map((m, i) => (
        <button key={i} title={`${mmss(m.t)} · ${m.label}`} onClick={(e) => { e.stopPropagation(); onSeek(m.t) }}
          className="absolute bottom-0 -translate-x-1/2 text-signal transition hover:scale-125" style={{ left: `${(m.t / duration) * 100}%` }}>
          <svg viewBox="0 0 10 8" className="size-2.5"><path d="M5 0l5 8H0z" fill="currentColor" /></svg>
        </button>
      ))}
    </div>
  )
}

function Player({ id, durationMs, audioRef, current, duration, playing, markers }) {
  const peaks = useWaveform(audioUrl(id), durationMs)
  const toggle = () => (audioRef.current.paused ? audioRef.current.play() : audioRef.current.pause())
  const seek = (t) => { if (duration) { audioRef.current.currentTime = t } }
  const pct = duration ? (current / duration) * 100 : 0
  return (
    <div className="sticky top-0 z-10 -mx-4 mb-8 border-y border-rule bg-paper/95 px-4 pt-3 pb-2 backdrop-blur lg:mx-0 lg:px-0">
      <div className="flex items-center gap-4">
        <button onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}
          className="grid size-11 shrink-0 place-items-center rounded-full bg-ink text-paper transition hover:opacity-90">
          {playing ? (
            <svg viewBox="0 0 12 12" className="size-3.5"><rect x="2.5" y="2" width="2.5" height="8" fill="currentColor" /><rect x="7" y="2" width="2.5" height="8" fill="currentColor" /></svg>
          ) : (
            <svg viewBox="0 0 12 12" className="ml-0.5 size-3.5"><path d="M3 1.8v8.4L10 6z" fill="currentColor" /></svg>
          )}
        </button>
        <div className="min-w-0 flex-1"><Waveform peaks={peaks} pct={pct} duration={duration} markers={markers} onSeek={seek} /></div>
        <span className="shrink-0 whitespace-nowrap text-right font-mono text-[12px] text-muted tnum">
          <span className="text-ink">{mmss(current)}</span> / {mmss(duration)}
        </span>
      </div>
      {markers.length > 0 && <p className="mt-1 pl-[60px] font-mono text-[10.5px] text-muted"><span className="text-signal">▲</span> moments with a task or meeting · click to jump</p>}
      <audio ref={audioRef} src={audioUrl(id)} preload="metadata" className="hidden" />
    </div>
  )
}

function SideBlock({ label, children }) {
  return (
    <section className="mb-9">
      <h3 className="label mb-3 border-b border-rule pb-2">{label}</h3>
      {children}
    </section>
  )
}

export default function Recording() {
  const { id } = useParams()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const t = params.get('t')
  const { data: rec, error, loading, reload, setData } = useApi(recPath(id), { poll: 0 })
  const audioRef = useRef(null)
  const rowRefs = useRef({})
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [busy, setBusy] = useState(false)
  const processing = rec && ['queued', 'transcribing', 'extracting'].includes(rec.status)

  // poll only while processing
  useEffect(() => {
    if (!processing) return
    const h = setInterval(reload, 3000)
    return () => clearInterval(h)
  }, [processing, reload])

  // audio wiring
  useEffect(() => {
    const a = audioRef.current
    if (!a) return
    const onTime = () => setCurrent(a.currentTime)
    const onMeta = () => setDuration(a.duration || (rec?.duration_ms || 0) / 1000)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    a.addEventListener('timeupdate', onTime)
    a.addEventListener('loadedmetadata', onMeta)
    a.addEventListener('play', onPlay)
    a.addEventListener('pause', onPause)
    return () => {
      a.removeEventListener('timeupdate', onTime)
      a.removeEventListener('loadedmetadata', onMeta)
      a.removeEventListener('play', onPlay)
      a.removeEventListener('pause', onPause)
    }
  }, [rec?.id])

  // deep link ?t=seconds: seek + scroll to the segment
  useEffect(() => {
    if (t == null || !rec?.segments?.length) return
    const sec = Number(t)
    const seg = [...rec.segments].reverse().find((s) => s.start_s <= sec + 0.5) || rec.segments[0]
    rowRefs.current[seg.id]?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    const a = audioRef.current
    if (!a) return
    const go = () => { a.currentTime = sec; setCurrent(sec) }
    if (a.readyState >= 1) go()
    else a.addEventListener('loadedmetadata', go, { once: true })
  }, [t, rec?.segments?.length])

  const activeId = rec?.segments?.find((s) => current >= s.start_s && current < Math.max(s.end_s, s.start_s + 0.5))?.id
    ?? (t != null ? [...(rec?.segments || [])].reverse().find((s) => s.start_s <= Number(t) + 0.5)?.id : undefined)

  function seekTo(s) {
    const a = audioRef.current
    a.currentTime = s
    setCurrent(s)
    a.play().catch(() => {})
  }

  async function remove() {
    if (!confirm('Delete this recording, its transcript and audio? This cannot be undone.')) return
    try { await api(recPath(id), { method: 'DELETE' }); nav('/recordings') } catch (e) { alert(e.message) }
  }

  async function act(path) {
    setBusy(true)
    try { await api(`${recPath(id)}/${path}`, { method: 'POST' }); await reload() } catch (e) { alert(e.message) } finally { setBusy(false) }
  }

  if (loading && !rec) return <Skeleton rows={8} />
  if (error && !rec) return <ErrorBox error={error} onRetry={reload} />
  if (!rec) return null
  const ins = rec.insights

  return (
    <>
      <Link to="/recordings" className="label hover:text-ink">← Recordings</Link>
      <header className="mt-4 mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <h1 className="font-serif text-[40px] leading-[1.05] tracking-[-0.01em] sm:text-[46px]">{rec.title}</h1>
          <div className="flex items-center gap-2 pt-3">
            <StatusPill status={rec.status} />
            {rec.status === 'failed' && <Button onClick={() => act('retry')} disabled={busy}>Retry</Button>}
            {rec.status === 'done' && <Button onClick={() => act('reextract')} disabled={busy} title="Regenerate summary, topics and action items">Re-analyse</Button>}
            <Button onClick={remove} disabled={busy || processing} title="Delete recording">Delete</Button>
          </div>
        </div>
        <p className="mt-3 font-mono text-[12px] text-muted tnum">
          {fmtWhen(rec.recorded_at)} · {rec.device_id} · {fmtDuration(rec.duration_ms)}
          {rec.language ? ` · ${rec.language}` : ''}{rec.battery_pct != null ? ` · battery ${rec.battery_pct}%` : ''}
          {` · ${SOURCE_LABEL[rec.source] || rec.source}`}
        </p>
      </header>

      {(rec.topics?.length > 0 || rec.keywords?.length > 0) && (
        <div className="-mt-2 mb-6">
          {rec.topics?.length > 0 && <p className="font-serif text-[19px] italic text-muted">{rec.topics.join(' · ')}</p>}
          {rec.keywords?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {rec.keywords.map((k) => <Chip key={k} onClick={() => nav(`/search?q=${encodeURIComponent(k)}`)}>{k}</Chip>)}
            </div>
          )}
        </div>
      )}

      {rec.error && <ErrorBox error={rec.error} onRetry={rec.status === 'failed' ? () => act('retry') : undefined} />}

      <Player id={rec.id} durationMs={rec.duration_ms} audioRef={audioRef} current={current} playing={playing}
        duration={duration || (rec.duration_ms || 0) / 1000}
        markers={[...rec.action_items.map((a) => ({ t: a.start_s, label: `${a.who}: ${a.what}` })),
                  ...rec.meetings.map((m) => ({ t: m.start_s, label: m.what }))].filter((m) => m.t != null)} />

      <div className="grid gap-x-12 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0">
          <h2 className="label mb-2 border-b border-rule pb-2">Transcript</h2>
          {rec.segments.length ? (
            <ol>
              {rec.segments.map((s) => {
                const active = s.id === activeId
                return (
                  <li key={s.id} ref={(el) => (rowRefs.current[s.id] = el)}>
                    <button onClick={() => seekTo(s.start_s)}
                      className={`grid w-full grid-cols-[56px_minmax(0,1fr)] gap-3 border-l-2 py-2.5 pl-3 pr-2 text-left transition ${
                        active ? 'border-signal bg-surface' : 'border-transparent hover:bg-surface/60'}`}>
                      <span className={`pt-[3px] font-mono text-[11.5px] tnum ${active ? 'text-signal' : 'text-muted'}`}>{mmss(s.start_s)}</span>
                      <span lang={rec.language || undefined} className="text-[15.5px] leading-relaxed">
                        {s.speaker && <span className="mr-2 font-mono text-[11px] uppercase text-muted">{s.speaker}</span>}
                        {s.text}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ol>
          ) : processing ? (
            <div className="py-8"><p className="font-mono text-[12px] text-proc"><span className="pulse">●</span> {rec.status === 'queued' ? 'Waiting in queue…' : 'Transcribing…'}</p></div>
          ) : <Empty title="No speech found.">The recording was processed but contained no transcribable speech.</Empty>}
        </section>

        <aside className="mt-12 xl:mt-0">
          {processing && rec.segments.length > 0 && <p className="mb-6 font-mono text-[12px] text-proc"><span className="pulse">●</span> Analysing…</p>}
          {ins ? (
            <>
              <SideBlock label="Summary">
                <p className="font-serif text-[17px] leading-relaxed">{ins.summary}</p>
                <ProposeButton className="mt-4" endpoint={`${recPath(rec.id)}/followup-email`}>Draft follow-up email</ProposeButton>
              </SideBlock>
              {ins.key_points?.length > 0 && (
                <SideBlock label="Key points">
                  <ul className="space-y-1.5 text-[14px]">{ins.key_points.map((k, i) => <li key={i} className="flex gap-2"><span className="text-muted">—</span>{k}</li>)}</ul>
                </SideBlock>
              )}
              {ins.decisions?.length > 0 && (
                <SideBlock label="Decisions">
                  <ul className="space-y-1.5 text-[14px]">{ins.decisions.map((k, i) => <li key={i} className="flex gap-2"><span className="text-done">✓</span>{k}</li>)}</ul>
                </SideBlock>
              )}
            </>
          ) : rec.status === 'done' && <SideBlock label="Summary"><p className="text-[14px] text-muted">No summary available. Try Re-analyse.</p></SideBlock>}

          {rec.action_items.length > 0 && (
            <SideBlock label="Action items">
              <ul className="divide-y divide-rule">
                {rec.action_items.map((a) => (
                  <ItemRow key={a.id} item={a} showSource={false}
                    onChange={(it) => setData((d) => ({ ...d, action_items: d.action_items.map((x) => (x.id === it.id ? it : x)) }))} />
                ))}
              </ul>
            </SideBlock>
          )}

          {rec.meetings.length > 0 && (
            <SideBlock label="Meetings & dates">
              <ul className="space-y-2.5 text-[14px]">
                {rec.meetings.map((m) => (
                  <li key={m.id}>
                    <p>{m.what}</p>
                    <p className="font-mono text-[11.5px] text-muted">
                      {m.when ? fmtDay(m.when) : m.when_text || 'date not stated'}{m.when && m.when_text ? ` (“${m.when_text}”)` : ''}
                      {m.start_s != null && <> · <TimeLink recordingId={rec.id} start={m.start_s} /></>}
                    </p>
                  </li>
                ))}
              </ul>
            </SideBlock>
          )}

          {rec.people.length > 0 && (
            <SideBlock label="People">
              <ul className="flex flex-wrap gap-2">
                {rec.people.map((p) => (
                  <li key={p.id} className="rounded-md border border-rule bg-surface px-2.5 py-1 text-[13px]">
                    {p.name}{p.role && <span className="text-muted"> · {p.role}</span>}
                  </li>
                ))}
              </ul>
            </SideBlock>
          )}
        </aside>
      </div>
    </>
  )
}
