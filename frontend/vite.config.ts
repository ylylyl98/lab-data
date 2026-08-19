import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/devices': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/experiments': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/artifacts': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
});
