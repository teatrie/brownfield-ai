import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

/**
 * Vitest configuration for the ledger dashboard frontend.
 *
 * Extends the existing Vite config with test-specific settings:
 * jsdom environment, global test APIs, and jest-dom matchers.
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test-setup.ts'],
    },
  }),
);
