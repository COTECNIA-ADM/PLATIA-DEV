// Aplicación de automatizaciones (/automation): portal Low-Code con n8n como motor (ADR-020).
import { lazy } from 'react'
import { Route, Routes } from 'react-router'
import AccessGate, { NotFound } from '../components/AccessGate'
import Shell, { type NavItem } from '../components/Shell'

const Home = lazy(() => import('./Home'))
const Catalog = lazy(() => import('./Catalog'))
const Runs = lazy(() => import('./Runs'))
const RunDetail = lazy(() => import('./RunDetail'))
const Account = lazy(() => import('../pages/Account'))
const Health = lazy(() => import('../pages/Health'))

const NAV: NavItem[] = [
  { to: '/', label: 'Inicio', icon: '⌂', module: 'automations' },
  { to: '/catalog', label: 'Catálogo', icon: '▤', module: 'automations' },
  { to: '/runs', label: 'Ejecuciones', icon: '↻', module: 'automations' },
]

export default function App() {
  return (
    <AccessGate>
      <Routes>
        <Route element={<Shell nav={NAV} />}>
          <Route index element={<Home />} />
          <Route path="catalog" element={<Catalog />} />
          <Route path="runs" element={<Runs />} />
          <Route path="runs/:id" element={<RunDetail />} />
          <Route path="account" element={<Account />} />
          <Route path="status" element={<Health />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AccessGate>
  )
}
