import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Tres aplicaciones en un solo build (fase 6b): cada HTML es una entrada con su
// propio código; lo común (sesión, cliente de API, componentes) se comparte en trozos.
// En desarrollo (npm run dev) las llamadas a /api van al backend a través de Nginx.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        operations: 'index.html',
        analytics: 'analytics/index.html',
        admin: 'admin/index.html',
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
})
