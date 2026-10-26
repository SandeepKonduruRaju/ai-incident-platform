/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Dev server: /api is proxied to incident-service, so the browser only ever talks to one origin (no CORS needed).
// API_URL overrides the target, e.g. http://localhost:8081 when compose publishes incident-service elsewhere.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: process.env.API_URL ?? 'http://localhost:8080', changeOrigin: false },
    },
  },
  build: {
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
});
