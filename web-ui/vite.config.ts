/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      'plotly.js/dist/plotly': 'plotly.js-basic-dist-min',
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-pdf': ['react-pdf', 'pdfjs-dist'],
          'vendor-sigma': ['sigma', '@react-sigma/core', 'graphology'],
          'vendor-plotly': ['plotly.js-basic-dist-min', 'react-plotly.js'],
          'vendor-markdown': ['react-markdown', 'remark-gfm'],
          'vendor-dnd': ['@dnd-kit/core', '@dnd-kit/sortable', '@dnd-kit/utilities'],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    // Vitest's 5s default is sized for unit tests. Several suites here render
    // a whole page and drive it through search → enrichment → poster, which
    // costs seconds per test and blew the default intermittently — the same
    // file failed 1 to 10 tests run to run with no code change, always as
    // "Test timed out", never as a wrong assertion.
    //
    // This buys headroom, not speed: the suites are still slow, and a real
    // hang still fails, just later.
    testTimeout: 20_000,
  },
})
