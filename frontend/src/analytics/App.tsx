// Aplicación de analítica (/analytics): cuadros de mando de negocio y valor de la IA.
import { lazy } from 'react'
import { Route, Routes } from 'react-router'
import AccessGate, { NotFound } from '../components/AccessGate'
import Shell, { type NavItem } from '../components/Shell'

const Dashboard = lazy(() => import('./Dashboard'))
const AIValue = lazy(() => import('./AIValue'))
const Account = lazy(() => import('../pages/Account'))
const Health = lazy(() => import('../pages/Health'))

const NAV: NavItem[] = [
  { to: '/', label: 'Cuadro de mando', icon: '▦', module: 'dashboards' },
  { to: '/ai', label: 'Valor de la IA', icon: '✦', module: 'dashboards' },
]

export default function App() {
  return (
    <AccessGate>
      <Routes>
        <Route element={<Shell nav={NAV} />}>
          <Route index element={<Dashboard />} />
          <Route path="ai" element={<AIValue />} />
          <Route path="account" element={<Account />} />
          <Route path="status" element={<Health />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AccessGate>
  )
}
