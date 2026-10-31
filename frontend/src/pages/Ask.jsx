import { useEffect, useRef, useState } from 'react'
import { ActionCard } from '../ActionCard.jsx'
import { Button, SourceChip } from '../components.jsx'
import { api, fmtLocal, useApi } from '../lib.js'

// The open conversation survives page switches; conversations themselves are stored on the server.
let CURRENT = { id: null, turns: [] }

const STARTERS = [
  'What did we promise the vendor?',
  "What's on my schedule next week?",
  'What are my open action items?',
  'Draft a follow-up email to the vendor',
  'Schedule the review call',
  'Summarise the last meeting',
]

function Answer({ m }) {
  if (m.error) return <p className="border-l-2 border-signal pl-4 text-[15px]">{m.error}</p>
  if (!m.grounded && !m.pending_action)
    return (
      <div className="border-l-2 border-abstain bg-wash/60 px-4 py-3">
        <p className="label mb-1">Not in recordings</p>
        <p className="text-[15.5px] text-muted">{m.answer}</p>
        {m.related?.length > 0 && (
          <div className="mt-3">
            <p className="mb-1.5 font-mono text-[11px] text-muted">Closest moments, in case they help:</p>
            <div className="flex flex-wrap gap-2">{m.related.map((s) => <SourceChip key={s.segment_id} s={s} />)}</div>
          </div>
        )}
      </div>
    )
  return (
    <div>
      <p className="font-serif text-[19px] leading-relaxed">{m.answer}</p>
      {m.sources?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="label self-center">Source</span>
          {m.sources.map((s) => <SourceChip key={s.segment_id} s={s} />)}
        </div>
      )}
      {m.pending_action && <ActionCard action={m.pending_action} />}
    </div>
  )
}

export default function Ask() {
  const [conv, setConvState] = useState(CURRENT)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)
  const { data: sessions, reload: reloadSessions } = useApi('/chat/sessions', { live: false })
  const setConv = (fn) => setConvState((c) => (CURRENT = typeof fn === 'function' ? fn(c) : fn))

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [conv.turns.length, busy])

  async function open(id) {
    try {
      const s = await api(`/chat/sessions/${id}`)
      setConv({ id: s.id, turns: s.turns })
    } catch (e) { alert(e.message) }
  }
  async function remove(id) {
    if (!confirm('Delete this conversation?')) return
    await api(`/chat/sessions/${id}`, { method: 'DELETE' })
    if (conv.id === id) setConv({ id: null, turns: [] })
    reloadSessions()
  }

  async function send(msg) {
    const q = (msg ?? text).trim()
    if (!q || busy) return
    setText('')
    setConv((c) => ({ ...c, turns: [...c.turns, { q }] }))
    setBusy(true)
    try {
      const r = await api('/chat', { method: 'POST', body: { message: q, session_id: conv.id } })
      setConv((c) => ({ id: r.session_id, turns: c.turns.map((m, i) => (i === c.turns.length - 1 ? { ...m, ...r } : m)) }))
      reloadSessions()
    } catch (e) {
      setConv((c) => ({ ...c, turns: c.turns.map((m, i) => (i === c.turns.length - 1 ? { ...m, error: e.message } : m)) }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-x-10 xl:grid-cols-[minmax(0,1fr)_220px]">
      <div className="flex min-h-[calc(100vh-9rem)] min-w-0 flex-col">
        <header className="mb-8 border-b border-rule pb-6">
          <p className="label mb-3">Assistant</p>
          <div className="flex items-end justify-between gap-4">
            <h1 className="font-serif text-[40px] leading-[1.05] sm:text-[48px]">Ask your recordings</h1>
            {conv.turns.length > 0 && <Button onClick={() => setConv({ id: null, turns: [] })}>New conversation</Button>}
          </div>
          <p className="mt-3 max-w-xl text-[14px] text-muted">
            Answers come only from what was said, with the recording and minute. Ask it to schedule something or draft an email and it prepares a card for you to confirm.
            English, हिन्दी or বাংলা.
          </p>
        </header>

        <div className="flex-1 space-y-9">
          {conv.turns.length === 0 && (
            <div className="grid gap-2 sm:grid-cols-2">
              {STARTERS.map((s) => (
                <button key={s} onClick={() => send(s)}
                  className="rounded-md border border-rule px-4 py-3 text-left text-[14px] text-muted transition hover:border-ink hover:text-ink">{s}</button>
              ))}
            </div>
          )}
          {conv.turns.map((m, i) => (
            <article key={i} className="fade-in">
              <p className="mb-3 text-[15px] font-medium"><span className="label mr-2">Q</span>{m.q}</p>
              {m.answer || m.error ? <Answer m={m} /> : <p className="font-mono text-[12px] text-muted"><span className="lamp live mr-2 !size-1.5 text-proc" />Searching the recordings…</p>}
            </article>
          ))}
          <div ref={endRef} />
        </div>

        <form onSubmit={(e) => { e.preventDefault(); send() }} className="sticky bottom-0 mt-10 -mx-4 border-t border-rule bg-paper/95 px-4 py-4 backdrop-blur lg:mx-0 lg:px-0">
          <div className="flex gap-2">
            <input value={text} onChange={(e) => setText(e.target.value)} disabled={busy}
              placeholder="Ask about a meeting, or: schedule the review call / draft a mail to Ravi"
              className="h-11 flex-1 rounded-md border border-rule bg-surface px-4 text-[15px] text-ink focus:border-ink focus:outline-none" />
            <Button type="submit" variant="ink" className="h-11 px-5" disabled={busy || !text.trim()}>Ask</Button>
          </div>
        </form>
      </div>

      <aside className="order-first mb-6 xl:order-none xl:mb-0 xl:pt-2">
        <h2 className="label mb-2 border-b border-rule pb-2">Conversations</h2>
        {sessions?.length ? (
          <ul className="max-h-48 space-y-0.5 overflow-y-auto xl:max-h-[70vh]">
            {sessions.map((s) => (
              <li key={s.id} className="group flex items-center gap-1">
                <button onClick={() => open(s.id)}
                  className={`min-w-0 flex-1 truncate rounded px-2 py-1.5 text-left text-[13px] ${conv.id === s.id ? 'bg-surface text-ink' : 'text-muted hover:text-ink'}`}>
                  {s.title}
                  <span className="block font-mono text-[10.5px] text-muted">{fmtLocal(s.updated_at)}</span>
                </button>
                <button onClick={() => remove(s.id)} aria-label="Delete conversation" className="px-1 text-muted opacity-0 hover:text-signal group-hover:opacity-100">×</button>
              </li>
            ))}
          </ul>
        ) : <p className="text-[12.5px] text-muted">Your conversations are saved here.</p>}
      </aside>
    </div>
  )
}
