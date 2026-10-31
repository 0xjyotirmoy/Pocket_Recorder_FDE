import { useMemo, useRef, useState } from 'react'
import { Button, Empty, ErrorBox, PageHead, Skeleton } from '../components.jsx'
import { api, fmtLongDate, nowIsoWithOffset, useApi } from '../lib.js'
import { RecordingRow } from './Today.jsx'

export default function Recordings() {
  const { data, error, loading, reload } = useApi('/recordings', { poll: 5000 })
  const [note, setNote] = useState(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)

  const days = useMemo(() => {
    const map = new Map()
    for (const r of data || []) {
      if (!map.has(r.local_date)) map.set(r.local_date, [])
      map.get(r.local_date).push(r)
    }
    return [...map.entries()]
  }, [data])

  async function importSamples() {
    setBusy(true)
    setNote(null)
    try {
      const r = await api('/import', { method: 'POST' })
      const parts = [`${r.imported.length} imported`, `${r.skipped.length} already here`]
      if (r.errors.length) parts.push(`${r.errors.length} skipped with errors (${r.errors.map((e) => e.file).join(', ')})`)
      setNote(parts.join(' · '))
      reload()
    } catch (e) {
      setNote(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function uploadFile(file) {
    if (!file) return
    setBusy(true)
    setNote(null)
    const fd = new FormData()
    fd.append('audio', file)
    fd.append('device_id', 'dashboard')
    fd.append('recorded_at', nowIsoWithOffset())
    fd.append('duration_ms', '')
    fd.append('battery_pct', '')
    try {
      const r = await api('/upload', { method: 'POST', body: fd })
      setNote(`Uploaded as ${r.id}. Transcription has started.`)
      reload()
    } catch (e) {
      setNote(e.message)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <>
      <PageHead kicker="Log" title="Recordings">
        <Button onClick={importSamples} disabled={busy}>Import samples</Button>
        <Button variant="ink" onClick={() => fileRef.current?.click()} disabled={busy}>Upload audio</Button>
        <input ref={fileRef} type="file" accept="audio/*,.wav,.mp3,.m4a,.ogg,.aac,.webm,.mpeg" className="hidden" onChange={(e) => uploadFile(e.target.files?.[0])} />
      </PageHead>
      {note && <p className="fade-in -mt-6 mb-8 font-mono text-[12px] text-muted">{note}</p>}
      <ErrorBox error={error} onRetry={reload} />

      {loading && !data ? <Skeleton rows={6} /> : days.length ? days.map(([day, rows]) => (
        <section key={day} className="mb-10">
          <div className="mb-1 flex items-baseline justify-between border-b border-ink pb-2">
            <h2 className="font-serif text-[24px]">{fmtLongDate(day)}</h2>
            <span className="font-mono text-[11.5px] text-muted tnum">{rows.length} {rows.length === 1 ? 'recording' : 'recordings'}</span>
          </div>
          <ul className="divide-y divide-rule">{rows.map((r) => <RecordingRow key={r.id} r={r} />)}</ul>
        </section>
      )) : (
        <Empty title="The log is empty.">
          Put WAV files and a <span className="font-mono">manifest.json</span> in <span className="font-mono">sample-recordings/</span> and press Import samples. Clips from the recorder appear here automatically.
        </Empty>
      )}
    </>
  )
}
