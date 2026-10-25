import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { FAMILIES, SENIORITY, fmtDate, label } from '../lib/format'
import type { Profile } from '../lib/types'
import { Badge, ErrorBox, Spinner, errorMessage, useToast } from '../components/ui'
import ProfileForm from './ProfileForm'

export default function ProfileDetail() {
  const id = Number(useParams().id)
  const { can } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const { data: p, error, isLoading, refetch } = useQuery({ queryKey: ['talent', id], queryFn: () => api<Profile>(`/api/talent/profiles/${id}`) })
  const remove = useMutation({
    mutationFn: () => api(`/api/talent/profiles/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('Perfil borrado.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['talent'] })
      navigate('/talent')
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!p) return null
  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/talent">Talento</Link> / {p.full_name}
      </nav>
      <header className="page-head">
        <div>
          <h1>{p.full_name}</h1>
          <div className="meta-row">
            {p.headline && <span>{p.headline}</span>}
            {p.family && <Badge>{label(FAMILIES, p.family)}</Badge>}
            {p.seniority && <Badge tone="accent">{label(SENIORITY, p.seniority)}</Badge>}
            {p.is_available ? <Badge tone="success">Disponible</Badge> : <Badge>Ocupado</Badge>}
          </div>
        </div>
        <div className="btn-row">
          {can('talent', 'delete') && (
            <button
              className="btn btn-danger-ghost"
              disabled={remove.isPending}
              onClick={() => window.confirm(`¿Borrar el perfil de ${p.full_name}?`) && remove.mutate()}
            >
              Borrar
            </button>
          )}
          {can('talent', 'write') && (
            <button className="btn btn-primary" onClick={() => setEditing(true)}>
              Editar
            </button>
          )}
        </div>
      </header>
      {editing && (
        <ProfileForm
          profile={p}
          onClose={() => setEditing(false)}
          onSaved={(saved) => {
            setEditing(false)
            queryClient.setQueryData(['talent', id], saved)
            void queryClient.invalidateQueries({ queryKey: ['talent', 'list'] })
            toast('Perfil guardado.', 'success')
          }}
        />
      )}
      <div className="detail-grid">
        <div className="stack">
          {p.summary && (
            <section className="card">
              <h2>Resumen</h2>
              <p className="pre-line">{p.summary}</p>
            </section>
          )}
          <section className="card">
            <h2>Experiencia</h2>
            {!p.experiences.length && <p className="muted">Sin experiencias registradas.</p>}
            <ol className="timeline">
              {p.experiences.map((e, i) => (
                <li key={i}>
                  <strong>{e.role ?? 'Puesto'}</strong> · {e.company}
                  {(e.start_date || e.end_date) && (
                    <div className="row-sub">
                      {e.start_date ? fmtDate(e.start_date) : '¿?'} – {e.end_date ? fmtDate(e.end_date) : 'actualidad'}
                    </div>
                  )}
                  {e.description && <p>{e.description}</p>}
                  {!!e.technologies.length && (
                    <div className="tags">
                      {e.technologies.map((t) => (
                        <Badge key={t}>{t}</Badge>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </section>
        </div>
        <aside className="stack">
          <section className="card">
            <h2>Competencias</h2>
            <ul className="skill-list">
              {p.skills.map((s) => (
                <li key={s.name}>
                  <span>{s.name}</span>
                  <span className="dots" title={s.level ? `Nivel ${s.level} de 5` : 'Sin nivel'}>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <span key={n} className={s.level && n <= s.level ? 'dot on' : 'dot'} />
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <section className="card">
            <dl className="facts">
              <dt>Experiencia</dt>
              <dd>{p.years_experience ? `${p.years_experience} años` : '—'}</dd>
              <dt>Actualizado</dt>
              <dd>{fmtDate(p.updated_at)}</dd>
            </dl>
          </section>
        </aside>
      </div>
    </div>
  )
}
