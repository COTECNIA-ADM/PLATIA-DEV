// Aplicación de administración (/admin): usuarios y roles, IA, prompts, agentes,
// búsqueda, tareas y auditoría. Cada pantalla depende del permiso del rol en Admin.
import { lazy } from 'react'
import { Route, Routes } from 'react-router'
import AccessGate, { NotFound } from '../components/AccessGate'
import Shell, { type NavItem } from '../components/Shell'

const Overview = lazy(() => import('./Overview'))
const Users = lazy(() => import('./Users'))
const UserDetail = lazy(() => import('./UserDetail'))
const Roles = lazy(() => import('./Roles'))
const AIConfig = lazy(() => import('./AIConfig'))
const Prompts = lazy(() => import('./Prompts'))
const PromptDetail = lazy(() => import('./PromptDetail'))
const Agents = lazy(() => import('./Agents'))
const AgentDetail = lazy(() => import('./AgentDetail'))
const SearchAdmin = lazy(() => import('./SearchAdmin'))
const Tasks = lazy(() => import('./Tasks'))
const Audit = lazy(() => import('./Audit'))
const Account = lazy(() => import('../pages/Account'))
const Health = lazy(() => import('../pages/Health'))

const NAV: NavItem[] = [
  { to: '/', label: 'Resumen', icon: '⌂' },
  { to: '/users', label: 'Usuarios', icon: '☺', module: 'users' },
  { to: '/roles', label: 'Roles y permisos', icon: '◇', module: 'roles' },
  { to: '/ai', label: 'Modelos y costes', icon: '✦', module: 'llm_config' },
  { to: '/prompts', label: 'Prompts', icon: '✎', module: 'prompts' },
  { to: '/agents', label: 'Agentes', icon: '◎', module: 'agents' },
  { to: '/search', label: 'Búsqueda', icon: '⌕', module: 'search' },
  { to: '/tasks', label: 'Tareas', icon: '▤', module: 'tasks' },
  { to: '/audit', label: 'Auditoría', icon: '☰', module: 'audit' },
  { to: '/status', label: 'Estado', icon: '♥', module: 'health' },
]

export default function App() {
  return (
    <AccessGate>
      <Routes>
        <Route element={<Shell nav={NAV} />}>
          <Route index element={<Overview />} />
          <Route path="users" element={<Users />} />
          <Route path="users/:id" element={<UserDetail />} />
          <Route path="roles" element={<Roles />} />
          <Route path="ai" element={<AIConfig />} />
          <Route path="prompts" element={<Prompts />} />
          <Route path="prompts/:name" element={<PromptDetail />} />
          <Route path="agents" element={<Agents />} />
          <Route path="agents/:id" element={<AgentDetail />} />
          <Route path="search" element={<SearchAdmin />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="audit" element={<Audit />} />
          <Route path="account" element={<Account />} />
          <Route path="status" element={<Health />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AccessGate>
  )
}
