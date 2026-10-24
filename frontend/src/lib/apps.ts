// Las aplicaciones del frontal. Comparten código y sesión, pero cada una es un
// build aparte con su propia ruta y su propia cabecera X-App-Code (ADR-014, fase 6b).
export type AppCode = 'operations' | 'analytics' | 'admin'

export type AppInfo = { code: AppCode; name: string; path: string; tagline: string }

export const APPS: Record<AppCode, AppInfo> = {
  operations: {
    code: 'operations',
    name: 'Operaciones',
    path: '/',
    tagline: 'Oportunidades, documentos y propuestas con IA.',
  },
  analytics: {
    code: 'analytics',
    name: 'Analítica',
    path: '/analytics/',
    tagline: 'Embudo, cartera y valor de la IA para el negocio.',
  },
  admin: {
    code: 'admin',
    name: 'Administración',
    path: '/admin/',
    tagline: 'Usuarios, roles, modelos de IA, prompts y auditoría.',
  },
}

/** Aplicaciones del usuario que tienen frontal (la de seguridad aún no). */
export function userApps(codes: string[]): AppInfo[] {
  return (Object.keys(APPS) as AppCode[]).filter((c) => codes.includes(c)).map((c) => APPS[c])
}
