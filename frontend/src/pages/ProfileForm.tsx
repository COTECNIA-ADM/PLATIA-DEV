// Alta y edición de un perfil de talento: datos, competencias y experiencias.
import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import { FAMILIES, SENIORITY } from '../lib/format'
import type { Profile } from '../lib/types'
import { Field, Modal, errorMessage } from '../components/ui'

type SkillRow = { name: string; level: string; years: string }
type ExperienceRow = {
  company: string
  role: string
  start_date: string
  end_date: string
  description: string
  technologies: string
}

const emptySkill: SkillRow = { name: '', level: '', years: '' }
const emptyExperience: ExperienceRow = { company: '', role: '', start_date: '', end_date: '', description: '', technologies: '' }
const numOrNull = (v: string) => (v.trim() === '' ? null : Number(v))
const textOrNull = (v: string) => v.trim() || null

export default function ProfileForm({
  profile,
  onClose,
  onSaved,
}: {
  profile?: Profile
  onClose: () => void
  onSaved: (p: Profile) => void
}) {
  const [form, setForm] = useState({
    full_name: profile?.full_name ?? '',
    email: profile?.email ?? '',
    headline: profile?.headline ?? '',
    family: profile?.family ?? '',
    seniority: profile?.seniority ?? '',
    years_experience: profile?.years_experience?.toString() ?? '',
    summary: profile?.summary ?? '',
    is_available: profile?.is_available ?? true,
  })
  const [skills, setSkills] = useState<SkillRow[]>(
    profile?.skills.map((s) => ({ name: s.name, level: s.level?.toString() ?? '', years: s.years?.toString() ?? '' })) ?? [],
  )
  const [experiences, setExperiences] = useState<ExperienceRow[]>(
    profile?.experiences.map((e) => ({
      company: e.company,
      role: e.role ?? '',
      start_date: e.start_date?.slice(0, 10) ?? '',
      end_date: e.end_date?.slice(0, 10) ?? '',
      description: e.description ?? '',
      technologies: e.technologies.join(', '),
    })) ?? [],
  )
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })

  const save = useMutation({
    mutationFn: () => {
      const body = {
        full_name: form.full_name.trim(),
        email: textOrNull(form.email),
        headline: textOrNull(form.headline),
        family: form.family || null,
        seniority: form.seniority || null,
        years_experience: numOrNull(form.years_experience),
        summary: textOrNull(form.summary),
        is_available: form.is_available,
        skills: skills
          .filter((s) => s.name.trim())
          .map((s) => ({ name: s.name.trim(), level: numOrNull(s.level), years: numOrNull(s.years) })),
        experiences: experiences
          .filter((x) => x.company.trim())
          .map((x) => ({
            company: x.company.trim(),
            role: textOrNull(x.role),
            start_date: x.start_date || null,
            end_date: x.end_date || null,
            description: textOrNull(x.description),
            technologies: x.technologies
              .split(',')
              .map((t) => t.trim())
              .filter(Boolean),
          })),
      }
      return profile
        ? api<Profile>(`/api/talent/profiles/${profile.id}`, { method: 'PATCH', body: { ...body, version: profile.version } })
        : api<Profile>('/api/talent/profiles', { body })
    },
    onSuccess: onSaved,
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Modal title={profile ? `Editar ${profile.full_name}` : 'Nuevo perfil'} onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Nombre completo">
            <input value={form.full_name} onChange={set('full_name')} required maxLength={255} autoFocus />
          </Field>
          <Field label="Email">
            <input type="email" value={form.email} onChange={set('email')} maxLength={255} />
          </Field>
          <Field label="Titular" hint="Por ejemplo: Arquitecta cloud con 10 años en banca">
            <input value={form.headline} onChange={set('headline')} maxLength={255} />
          </Field>
          <Field label="Años de experiencia">
            <input type="number" min={0} max={60} value={form.years_experience} onChange={set('years_experience')} />
          </Field>
          <Field label="Familia">
            <select value={form.family} onChange={set('family')}>
              <option value="">—</option>
              {Object.entries(FAMILIES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Nivel">
            <select value={form.seniority} onChange={set('seniority')}>
              <option value="">—</option>
              {Object.entries(SENIORITY).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Resumen profesional">
          <textarea rows={3} value={form.summary} onChange={set('summary')} />
        </Field>
        <label className="check">
          <input
            type="checkbox"
            checked={form.is_available}
            onChange={(e) => setForm({ ...form, is_available: e.target.checked })}
          />{' '}
          Disponible para nuevos proyectos
        </label>

        <fieldset className="field">
          <legend className="field-label">Competencias</legend>
          <div className="stack">
            {skills.map((s, i) => (
              <div key={i} className="row-form">
                <input
                  className="grow"
                  placeholder="Competencia (p. ej. Kubernetes)"
                  aria-label="Competencia"
                  value={s.name}
                  maxLength={100}
                  onChange={(e) => setSkills(skills.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                />
                <select
                  aria-label="Nivel de la competencia"
                  value={s.level}
                  onChange={(e) => setSkills(skills.map((x, j) => (j === i ? { ...x, level: e.target.value } : x)))}
                >
                  <option value="">Nivel</option>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n} de 5
                    </option>
                  ))}
                </select>
                <input
                  type="number"
                  min={0}
                  max={60}
                  placeholder="Años"
                  aria-label="Años con la competencia"
                  className="input-short"
                  value={s.years}
                  onChange={(e) => setSkills(skills.map((x, j) => (j === i ? { ...x, years: e.target.value } : x)))}
                />
                <button type="button" className="btn-icon" aria-label="Quitar competencia" onClick={() => setSkills(skills.filter((_, j) => j !== i))}>
                  ×
                </button>
              </div>
            ))}
            <div>
              <button type="button" className="btn btn-small" onClick={() => setSkills([...skills, { ...emptySkill }])}>
                Añadir competencia
              </button>
            </div>
          </div>
        </fieldset>

        <fieldset className="field">
          <legend className="field-label">Experiencia</legend>
          <div className="stack">
            {experiences.map((x, i) => {
              const change = (key: keyof ExperienceRow) => (e: { target: { value: string } }) =>
                setExperiences(experiences.map((y, j) => (j === i ? { ...y, [key]: e.target.value } : y)))
              return (
                <section key={i} className="card card-flat stack">
                  <div className="grid-2">
                    <Field label="Empresa o cliente">
                      <input value={x.company} onChange={change('company')} maxLength={255} />
                    </Field>
                    <Field label="Puesto">
                      <input value={x.role} onChange={change('role')} maxLength={255} />
                    </Field>
                    <Field label="Desde">
                      <input type="date" value={x.start_date} onChange={change('start_date')} />
                    </Field>
                    <Field label="Hasta" hint="Vacío: actualidad">
                      <input type="date" value={x.end_date} onChange={change('end_date')} />
                    </Field>
                  </div>
                  <Field label="Qué hizo">
                    <textarea rows={2} value={x.description} onChange={change('description')} />
                  </Field>
                  <Field label="Tecnologías" hint="Separadas por comas">
                    <input value={x.technologies} onChange={change('technologies')} />
                  </Field>
                  <div>
                    <button type="button" className="btn btn-small btn-danger-ghost" onClick={() => setExperiences(experiences.filter((_, j) => j !== i))}>
                      Quitar experiencia
                    </button>
                  </div>
                </section>
              )
            })}
            <div>
              <button type="button" className="btn btn-small" onClick={() => setExperiences([...experiences, { ...emptyExperience }])}>
                Añadir experiencia
              </button>
            </div>
          </div>
        </fieldset>

        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Guardar
          </button>
        </div>
      </form>
    </Modal>
  )
}
