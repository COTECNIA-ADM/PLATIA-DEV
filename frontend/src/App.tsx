import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router'
import Layout from './components/Layout'
import { Empty, Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import Login from './pages/Login'

// Cada pantalla se carga cuando se abre: el primer arranque descarga menos código
const Home = lazy(() => import('./pages/Home'))
const Opportunities = lazy(() => import('./pages/Opportunities'))
const OpportunityDetail = lazy(() => import('./pages/OpportunityDetail'))
const Documents = lazy(() => import('./pages/Documents'))
const DocumentDetail = lazy(() => import('./pages/DocumentDetail'))
const Proposals = lazy(() => import('./pages/Proposals'))
const ProposalDetail = lazy(() => import('./pages/ProposalDetail'))
const Copilot = lazy(() => import('./pages/Copilot'))
const Clients = lazy(() => import('./pages/Clients'))
const ClientDetail = lazy(() => import('./pages/ClientDetail'))
const Talent = lazy(() => import('./pages/Talent'))
const ProfileDetail = lazy(() => import('./pages/ProfileDetail'))
const Notifications = lazy(() => import('./pages/Notifications'))
const Search = lazy(() => import('./pages/Search'))
const Account = lazy(() => import('./pages/Account'))
const Health = lazy(() => import('./pages/Health'))

function NotFound() {
  return <Empty title="Esta página no existe">Vuelve al inicio desde el menú.</Empty>
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Spinner label="Recuperando la sesión…" />
  if (!user) {
    return (
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="status" element={<div className="content"><Health /></div>} />
          <Route path="*" element={<Login />} />
        </Routes>
      </Suspense>
    )
  }
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="opportunities" element={<Opportunities />} />
          <Route path="opportunities/:id" element={<OpportunityDetail />} />
          <Route path="documents" element={<Documents />} />
          <Route path="documents/:id" element={<DocumentDetail />} />
          <Route path="proposals" element={<Proposals />} />
          <Route path="proposals/:id" element={<ProposalDetail />} />
          <Route path="copilot" element={<Copilot />} />
          <Route path="copilot/:id" element={<Copilot />} />
          <Route path="clients" element={<Clients />} />
          <Route path="clients/:id" element={<ClientDetail />} />
          <Route path="talent" element={<Talent />} />
          <Route path="talent/:id" element={<ProfileDetail />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="search" element={<Search />} />
          <Route path="account" element={<Account />} />
          <Route path="status" element={<Health />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
