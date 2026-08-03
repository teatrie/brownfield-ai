/// <reference types="vite/client" />

/**
 * Ambient Vite client types.
 *
 * Supplies the module declarations for Vite's asset imports — notably the
 * bare `import './styles/theme.css'` side-effect form used in main.tsx.
 * TypeScript 5.8 accepted those untyped; TypeScript 7 rejects them with
 * TS2882, so this reference is load-bearing rather than decorative.
 */
