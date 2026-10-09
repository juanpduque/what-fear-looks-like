import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import { resolve, sep } from 'node:path';
import { createReadStream, existsSync, rmSync } from 'node:fs';

const SALIENCY_MAPS = resolve(__dirname, '../pipeline/data/qa/saliency/maps');
const SALIENCY_ALT_MAPS = resolve(__dirname, '../pipeline/data/qa/saliency_alts/maps');

function saliencyFileFromUrl(url) {
  const path = decodeURIComponent(String(url || '').split('?')[0]);
  const alt = path.match(/\/saliency_alts\/([^/]+)\.png$/i);
  if (alt) {
    const name = alt[1].replace(/[^A-Za-z0-9._-]/g, '');
    if (!name) return null;
    return resolve(SALIENCY_ALT_MAPS, `${name}.png`);
  }
  const m = path.match(/\/saliency\/(\d+)\.png$/i);
  if (m) return resolve(SALIENCY_MAPS, `${m[1]}.png`);
  return null;
}

function serveSaliencyMaps(req, res, next) {
  const file = saliencyFileFromUrl(req.originalUrl || req.url);
  if (!file) return next();
  const root = file.includes(`${sep}saliency_alts${sep}`) ? SALIENCY_ALT_MAPS : SALIENCY_MAPS;
  if (!file.startsWith(root) || !existsSync(file)) {
    res.statusCode = 404;
    res.end();
    return;
  }
  res.setHeader('Content-Type', 'image/png');
  res.setHeader('Cache-Control', 'no-store');
  createReadStream(file).pipe(res);
}

/** JS bundled by Vite — do not copy to dist. */
const DEMO_BUNDLE_JS = new Set([
  'demo.js',
  'GLTFLoader.js',
  'BufferGeometryUtils.js',
  'three.module.js',
]);

export default defineConfig({
  base: '/what-fear-looks-like/',
  server: {
    fs: {
      allow: [resolve(__dirname, '..')],
    },
  },
  plugins: [
    {
      name: 'serve-saliency-maps',
      configureServer(server) {
        server.middlewares.use(serveSaliencyMaps);
      },
      configurePreviewServer(server) {
        server.middlewares.use(serveSaliencyMaps);
      },
    },
    viteStaticCopy({
      targets: [
        { src: 'assets', dest: '.' },
        { src: 'data', dest: '.' },
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
