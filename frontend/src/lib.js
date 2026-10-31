import { useCallback, useEffect, useRef, useState } from 'react'

// Built app is served by the backend itself (same origin). `npm run dev` talks to :8000.
export const API = (import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/$/, '')

export async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.headers || {}) } }
  if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== 'string') {
    init.body = JSON.stringify(opts.body)
    init.headers['Content-Type'] = 'application/json'
  }
  let res
  try {
    res = await fetch(API + path, init)
  } catch {
    throw new Error(`Can't reach the server at ${API}. Is the backend running?`)
  }
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const msg = data && (data.error || data.detail)
    throw new Error(typeof msg === 'string' ? msg : msg ? JSON.stringify(msg) : `Request failed (${res.status})`)
  }
  return data
}

export const recPath = (id) => `/recordings/${encodeURIComponent(id)}`
export const audioUrl = (id) => `${API}${recPath(id)}/audio`

// ---- live updates: one shared EventSource (Server-Sent Events) for the whole app ------------------
const liveListeners = new Set()
let liveSource = null
function ensureLive() {
  if (liveSource || typeof EventSource === 'undefined') return
  liveSource = new EventSource(`${API}/events`)
  liveSource.onmessage = (e) => {
    let msg = null
    try { msg = JSON.parse(e.data) } catch { return }
    liveListeners.forEach((fn) => fn(msg))
  }
}
export function useLive(fn) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    ensureLive()
    const h = (m) => ref.current(m)
    liveListeners.add(h)
    return () => liveListeners.delete(h)
  }, [])
}

/** Fetch a path. Refreshes instantly on live server events (debounced), with slow polling as a fallback. */
export function useApi(path, { poll = 0, live = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const alive = useRef(true)
  const timer = useRef(null)
  const load = useCallback(async () => {
    if (!path) return
    try {
      const data = await api(path)
      if (alive.current) setState({ data, error: null, loading: false })
    } catch (e) {
      if (alive.current) setState((s) => ({ ...s, error: e.message, loading: false }))
    }
  }, [path])
  useEffect(() => {
    alive.current = true
    load()
    if (!poll) return () => { alive.current = false }
    const t = setInterval(load, poll)
    return () => { alive.current = false; clearInterval(t) }
  }, [load, poll])
  useLive(() => {
    if (!live) return
    clearTimeout(timer.current)
    timer.current = setTimeout(load, 250)
  })
  return { ...state, reload: load, setData: (fn) => setState((s) => ({ ...s, data: fn(s.data) })) }
}

export const SOURCE_LABEL = { device: 'Recorder', import: 'Imported', dashboard: 'Uploaded' }

// ---- formatting: times are shown in the recording's own offset (read straight from the ISO string)
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const pad = (n) => String(n).padStart(2, '0')

export function parts(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(iso || '')
  return m ? { y: +m[1], mo: +m[2], d: +m[3], h: m[4], mi: m[5] } : null
}
export const fmtDay = (iso) => { const p = parts(iso); return p ? `${p.d} ${MON[p.mo - 1]}` : '' }
export const fmtClock = (iso) => { const p = parts(iso); return p && p.h ? `${p.h}:${p.mi}` : '' }
export const fmtWhen = (iso) => [fmtDay(iso), fmtClock(iso)].filter(Boolean).join(' · ')
export function fmtLongDate(ymd, opts = { weekday: 'long', day: 'numeric', month: 'long' }) {
  const p = parts(ymd)
  if (!p) return ymd || ''
  return new Date(Date.UTC(p.y, p.mo - 1, p.d)).toLocaleDateString('en-GB', { ...opts, timeZone: 'UTC' })
}
export function mmss(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(s / 3600)
  return h ? `${h}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}` : `${pad(Math.floor(s / 60))}:${pad(s % 60)}`
}
export const fmtDuration = (ms) => (ms == null ? '—' : mmss(ms / 1000))

export function todayYmd() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
export function nowIsoWithOffset(d = new Date()) {
  const off = -d.getTimezoneOffset()
  const sign = off >= 0 ? '+' : '-'
  const a = Math.abs(off)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`
}
/** "2026-11-06T10:00:00+05:30" <-> value for <input type="datetime-local"> keeping the offset */
export const toLocalInput = (iso) => (iso || '').slice(0, 16)
export function fromLocalInput(v, originalIso) {
  const off = /([+-]\d{2}:\d{2}|Z)$/.exec(originalIso || '')?.[1] || nowIsoWithOffset().slice(-6)
  return v ? `${v}:00${off}` : ''
}

export function dueLabel(item) {
  if (item.due_date) return fmtDay(item.due_date)
  return item.due_text || 'No date'
}
export function isOverdue(item) {
  return item.status === 'open' && item.due_date && item.due_date < todayYmd()
}

// ---- theme: 'light' | 'dark' | 'auto' (follows the OS) ----------------------------------------
const THEME_KEY = 'fieldnotes-theme'
export function useTheme() {
  const [theme, setThemeState] = useState(() => {
    try { return localStorage.getItem(THEME_KEY) || 'auto' } catch { return 'auto' }
  })
  useEffect(() => {
    const el = document.documentElement
    if (theme === 'auto') delete el.dataset.theme
    else el.dataset.theme = theme
    try { localStorage.setItem(THEME_KEY, theme) } catch { /* private mode: theme still applies for this visit */ }
  }, [theme])
  return [theme, setThemeState]
}

// ---- waveform: decode the WAV in the browser and reduce it to N peak bars ------------------------
export function useWaveform(url, durationMs, bars = 180) {
  const [peaks, setPeaks] = useState(null)
  useEffect(() => {
    setPeaks(null)
    if (!url || (durationMs && durationMs > 25 * 60 * 1000)) return // skip very long files
    let cancelled = false
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return
    ;(async () => {
      try {
        const buf = await (await fetch(url)).arrayBuffer()
        const ctx = new Ctx()
        const audio = await ctx.decodeAudioData(buf)
        ctx.close?.()
        const data = audio.getChannelData(0)
        const step = Math.max(1, Math.floor(data.length / bars))
        const out = []
        for (let i = 0; i < bars; i++) {
          let max = 0
          for (let j = i * step, end = Math.min(data.length, j + step); j < end; j += 8) {
            const v = Math.abs(data[j])
            if (v > max) max = v
          }
          out.push(max)
        }
        const top = Math.max(...out, 0.0001)
        if (!cancelled) setPeaks(out.map((v) => Math.max(0.06, Math.sqrt(v / top))))
      } catch {
        if (!cancelled) setPeaks([])
      }
    })()
    return () => { cancelled = true }
  }, [url, durationMs, bars])
  return peaks
}

/** Server timestamps ("...Z") shown in the viewer's local time. */
export function fmtLocal(isoZ) {
  const d = new Date(isoZ)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
