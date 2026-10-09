import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import { resolve } from 'node:path';
import { rmSync } from 'node:fs';

/** JS bundled by Vite — do not copy to dist. */
const DEMO_BUNDLE_JS = new Set([
  'demo.js',
  'GLTFLoader.js',
  'BufferGeometryUtils.js',
  'three.module.js',
]);

export default defineConfig({
  base: '/what-fear-looks-like/',
  plugins: [
    viteStaticCopy({
      targets: [
        { src: 'assets', dest: '.' },
        { src: 'data', dest: '.' },
        { src: 'saliency', dest: '.' },
        { src: 'saliency_alts', dest: '.' },
        { src: 'i18n/*.js', dest: 'i18n' },
        { src: 'js', dest: '.' },
        {
          src: 'demos/poster-decompose/**/*',
          dest: 'demos/poster-decompose',
          globOptions: {
            ignore: [
              '**/_shots/**',
              '**/_shots',
              '**/captures/**',
              '**/captures',
              ...[...DEMO_BUNDLE_JS].map((f) => `**/${f}`),
            ],
          },
        },
      ],
    }),
    {
      name: 'strip-dev-artifacts',
      closeBundle() {
        for (const dir of ['_shots', 'captures']) {
          try {
            rmSync(resolve(__dirname, 'dist/demos/poster-decompose', dir), {
              recursive: true,
              force: true,
            });
          } catch {
            /* ignore */
          }
        }
      },
    },
  ],
  build: {
    // Async chunks (Three.js) load only after dynamic import — no modulepreload polyfill
    modulePreload: false,
    rollupOptions: {
      input: {
        essay: resolve(__dirname, 'index.html'),
        demo: resolve(__dirname, 'demos/poster-decompose/index.html'),
      },
      output: {
        manualChunks(id) {
          if (id.includes('three.module.js')) {
            return 'three';
          }
        },
      },
    },
  },
  resolve: {
    alias: {
      three: resolve(__dirname, 'demos/poster-decompose/three.module.js'),
    },
  },
});
