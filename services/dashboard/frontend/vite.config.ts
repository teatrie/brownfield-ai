import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/** Vite configuration for the ledger dashboard SPA. */
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8484',
      '/ws': {
        target: 'ws://localhost:8484',
        ws: true,
      },
    },
  },
});
