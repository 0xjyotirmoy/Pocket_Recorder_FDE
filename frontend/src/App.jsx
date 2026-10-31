import { NavLink, Route, Routes } from 'react-router-dom'
import { useApi, useTheme } from './lib.js'
import { ThemeToggle } from './components.jsx'
import Today from './pages/Today.jsx'
import Recordings from './pages/Recordings.jsx'
import Recording from './pages/Recording.jsx'
import Search from './pages/Search.jsx'
import Ask from './pages/Ask.jsx'
import ActionItems from './pages/ActionItems.jsx'
import Calendar from './pages/Calendar.jsx'
import Drafts from './pages/Drafts.jsx'

const NAV = [
  ['/', 'Overview'],
  ['/recordings', 'Recordings'],
  ['/search', 'Search'],
  ['/ask', 'Ask'],
  ['/actions', 'Action items'],
  ['/calendar', 'Calendar'],
  ['/drafts', 'Drafts'],
]

function LiveStatus() {
  const { data, error } = useApi('/health', { poll: 5000 })
  if (error && !data) return <p className="font-mono text-[11px] text-signal">● Server offline</p>
  if (!data) return null
  const busy = data.queue_depth > 0
  return (
    <p className="font-mono text-[11px] text-muted tnum">
      <span className={`lamp !size-[7px] mr-1.5 align-middle ${busy ? 'live text-proc' : 'text-done'}`} />
      {busy ? `${data.queue_depth} processing` : 'Listening for uploads'}
    </p>
  )
}

export default function App() {
  const [theme, setTheme] = useTheme()
  return (
    <div className="mx-auto grid min-h-screen max-w-[1240px] grid-cols-1 lg:grid-cols-[200px_minmax(0,1fr)] lg:gap-14">
      <aside className="border-b border-rule px-4 pt-5 pb-3 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:px-0 lg:pt-10 lg:pl-6">
        <div className="mb-4 flex items-baseline justify-between lg:mb-10 lg:block">
          <NavLink to="/" className="block">
            <span className="font-serif text-[26px] italic leading-none">Fieldnotes</span>
            <span className="label mt-1.5 hidden lg:block">Meeting log</span>
          </NavLink>
          <div className="flex items-center gap-3 lg:hidden"><ThemeToggle theme={theme} setTheme={setTheme} compact /></div>
        </div>
        <nav className="-mx-1 flex gap-1 overflow-x-auto lg:mx-0 lg:block lg:space-y-0.5">
          {NAV.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `relative block shrink-0 whitespace-nowrap rounded px-2 py-1.5 text-[14px] transition lg:pl-4 ${
                  isActive
                    ? 'text-ink lg:before:absolute lg:before:left-0 lg:before:top-1/2 lg:before:h-4 lg:before:w-[2px] lg:before:-translate-y-1/2 lg:before:bg-signal max-lg:bg-wash'
                    : 'text-muted hover:text-ink'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-10 hidden space-y-5 lg:block">
          <LiveStatus />
          <ThemeToggle theme={theme} setTheme={setTheme} />
        </div>
      </aside>

      <main className="min-w-0 px-4 pt-8 pb-24 lg:max-w-[920px] lg:px-0 lg:pt-12 lg:pr-6">
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/recordings" element={<Recordings />} />
          <Route path="/recordings/:id" element={<Recording />} />
          <Route path="/search" element={<Search />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/actions" element={<ActionItems />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/drafts" element={<Drafts />} />
          <Route path="*" element={<p className="font-serif text-2xl">Page not found.</p>} />
        </Routes>
      </main>
    </div>
  )
}
