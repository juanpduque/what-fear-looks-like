// Flat ESLint config (ESLint 9+). Lints the authored ES modules in src/ only;
// vendored Three.js and generated data/ are left alone.
//   npm run lint        # check
//   npm run lint:fix    # autofix
import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'data/**',
      'assets/**',
      'js/**',
      'i18n/**',
      'demos/poster-decompose/three.module.js',
      'demos/poster-decompose/GLTFLoader.js',
      'demos/poster-decompose/BufferGeometryUtils.js',
      'demos/poster-decompose/demo.js',
    ],
  },
  js.configs.recommended,
  {
    // Authored browser modules.
    files: ['src/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        d3: 'readonly', // loaded via <script> in index.html
        openPoster: 'writable', // window global wired by the lookup module
      },
    },
    rules: {
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      'no-console': 'off',
    },
  },
  {
    // Build config runs in Node (CJS-style __dirname is injected by Vite).
    files: ['vite.config.js', 'eslint.config.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.node,
      },
    },
  },
];
