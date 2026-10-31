import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProposeButton, inputCls } from '../ActionCard.jsx'
import { Button, Empty, ErrorBox, PageHead, Skeleton } from '../components.jsx'
import { api, fmtLocal, fmtWhen, recPath, useApi } from '../lib.js'

export default function Drafts() {
  const { data, error, loading, reload, setData } = useApi('/drafts')
  const { data: recs } = useApi('/recordings')
  const [selId, setSelId] = useState(null)
  const [edit, setEdit] = useState(null)
  const [copied, setCopied] = useState(false)
  useEffect(() => { if (data?.length && !data.find((d) => d.id === selId)) setSelId(data[0].id) }, [data])
  useEffect(() => setEdit(null), [selId])
  const sel = data?.find((d) => d.id === selId)
  const drafted = new Set((data || []).map((d) => d.source_recording_id).filter(Boolean))
  const candidates = (recs || []).filter((r) => r.status === 'done' && !drafted.has(r.id)).slice(0, 6)

  async function copy() {
    const text = `To: ${sel.to}\nSubject: ${sel.subject}\n\n${sel.body}`
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { alert('Copy failed') }
  }
  async function save() {
    try {
      const d = await api(`/drafts/${sel.id}`, { method: 'PATCH', body: edit })
      setData((list) => list.map((x) => (x.id === d.id ? d : x)))
      setEdit(null)
    } catch (e) { alert(e.message) }
  }
  async function remove() {
    if (!confirm('Delete this draft?')) return
    try { await api(`/drafts/${sel.id}`, { method: 'DELETE' }); setData((d) => d.filter((x) => x.id !== sel.id)) } catch (e) { alert(e.message) }
  }
  const mailto = sel ? `mailto:${encodeURIComponent(sel.to)}?subject=${encodeURIComponent(sel.subject)}&body=${encodeURIComponent(sel.body)}` : '#'

  return (
    <>
      <PageHead kicker="Follow-ups · saved here, never sent by the app" title="Drafts" />
      <ErrorBox error={error} onRetry={reload} />

      {candidates.length > 0 && (
        <section className="mb-10">
          <h2 className="label mb-1 border-b border-rule pb-2">Sessions without a follow-up yet</h2>
          <ul className="divide-y divide-rule">
            {candidates.map((r) => (
              <li key={r.id} className="py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span>
                    <Link to={recPath(r.id)} className="text-[15px] hover:underline hover:decoration-rule hover:underline-offset-4">{r.title}</Link>
                    <span className="ml-2 font-mono text-[11.5px] text-muted">{fmtWhen(r.recorded_at)}</span>
                  </span>
                </div>
                <ProposeButton className="mt-2" endpoint={`${recPath(r.id)}/followup-email`} onDone={() => reload()}>Draft follow-up</ProposeButton>
              </li>
            ))}
          </ul>
        </section>
      )}

      {loading && !data ? <Skeleton /> : !data?.length ? (
        <Empty title="No drafts yet.">Draft a follow-up above, from an action item, or ask the assistant: “Draft a follow-up email to Ravi about the purchase order”.</Empty>
      ) : (
        <div className="grid gap-8 md:grid-cols-[260px_minmax(0,1fr)]">
          <ul className="divide-y divide-rule border-y border-rule">
            {data.map((d) => (
              <li key={d.id}>
                <button onClick={() => setSelId(d.id)}
                  className={`block w-full border-l-2 py-3 pl-3 pr-2 text-left transition ${d.id === selId ? 'border-signal bg-surface' : 'border-transparent hover:bg-surface/60'}`}>
                  <span className="block truncate text-[14.5px] font-medium">{d.subject}</span>
                  <span className="block truncate text-[12.5px] text-muted">{d.to || 'no recipient yet'}</span>
                </button>
              </li>
            ))}
          </ul>
          {sel && (
            <article className="fade-in min-w-0" key={sel.id}>
              <p className="mb-5 inline-block border border-rule px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.1em] text-muted">Draft — never sent by Fieldnotes</p>
              {edit ? (
                <div className="grid gap-3">
                  <input className={inputCls} value={edit.to} onChange={(e) => setEdit({ ...edit, to: e.target.value })} placeholder="To" />
                  <input className={inputCls} value={edit.subject} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} placeholder="Subject" />
                  <textarea rows={12} className={`${inputCls} leading-relaxed`} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} />
                  <div className="flex gap-2"><Button variant="ink" onClick={save}>Save changes</Button><Button onClick={() => setEdit(null)}>Cancel</Button></div>
                </div>
              ) : (
                <>
                  <dl className="mb-6 grid grid-cols-[70px_minmax(0,1fr)] gap-y-1.5 border-b border-rule pb-4 text-[14px]">
                    <dt className="label pt-0.5">To</dt><dd>{sel.to || <span className="text-muted">—</span>}</dd>
                    <dt className="label pt-0.5">Subject</dt><dd className="font-medium">{sel.subject}</dd>
                    <dt className="label pt-0.5">Saved</dt><dd className="font-mono text-[12.5px] text-muted">{fmtLocal(sel.created_at)}</dd>
                  </dl>
                  <div className="whitespace-pre-wrap font-serif text-[18px] leading-relaxed">{sel.body}</div>
                  <div className="mt-8 flex flex-wrap items-center gap-2">
                    <Button onClick={() => setEdit({ to: sel.to, subject: sel.subject, body: sel.body })}>Edit</Button>
                    <Button variant="ink" onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>
                    <a href={mailto} className="inline-flex h-9 items-center rounded-md border border-rule px-3.5 text-[13px] font-medium hover:border-ink"
                      title="Opens your own email app with this draft filled in. You review and press send there.">Open in email app</a>
                    <Button onClick={remove}>Delete</Button>
                    {sel.source_recording_id && <Link to={recPath(sel.source_recording_id)} className="ml-2 text-[13px] text-muted hover:text-ink">From recording →</Link>}
                  </div>
                </>
              )}
            </article>
          )}
        </div>
      )}
    </>
  )
}
