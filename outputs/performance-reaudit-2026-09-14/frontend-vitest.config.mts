import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': '/tmp/nexus-performance-reaudit-2026-09-14/frontend/src' } },
  test: { environment: 'jsdom', globals: true, include: ['*.test.tsx'], maxWorkers: 1, fileParallelism: false },
});
