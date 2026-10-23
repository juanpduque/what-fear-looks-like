import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import { resolve } from 'node:path';
import { readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';

const PAGES_ORIGIN = 'https://juanpduque.github.io/what-fear-looks-like';

/** GitHub Pages keeps the repo path. Netlify publishes at the domain root. */
function siteBase() {
  const fromEnv = process.env.VITE_BASE;
  if (fromEnv) return fromEnv.endsWith('/') ? fromEnv : `${fromEnv}/`;
  if (process.env.NETLIFY) return '/';
  return '/what-fear-looks-like/';
}

function deployOrigin() {
  const raw = process.env.VITE_SITE_ORIGIN || (process.env.NETLIFY ? process.env.URL : '') || '';
  return raw.replace(/\/$/, '');
}

/** Autopsy blobs live in Supabase once the build has a project URL. */
const AUTOPSY_BLOBS = [
  'lookup.js',
  'pose.js',
  'creature_boxes.js',
  'weapon_boxes.js',
  'saliency.json',
  'title_ink.json',
  'omdb.json',
  'medium_cl.json',
  'key_art.json',
  'poster_alts.json',
  'poster_alts_rek.json',
  'poster_alts_pose.json',
  'poster_alts_sal.json',
  'poster_alts_comp.json',
  'poster_alts_faces.json',
  'poster_alts_owl.json',
  'poster_alts_text.json',
  'poster_alts_clip.json',
];

function rewriteOrigins(dir, origin) {
  for (const name of readdirSync(dir)) {
    const path = resolve(dir, name);
    if (statSync(path).isDirectory()) {
      rewriteOrigins(path, origin);
      continue;
    }
    if (!name.endsWith('.html')) continue;
    const text = readFileSync(path, 'utf8');
    if (!text.includes(PAGES_ORIGIN)) continue;
    writeFileSync(path, text.replaceAll(PAGES_ORIGIN, origin));
  }
}

/** JS bundled by Vite — do not copy to dist. */
const DEMO_BUNDLE_JS = new Set([
  'demo.js',
  'GLTFLoader.js',
  'BufferGeometryUtils.js',
  'three.module.js',
]);

export default defineConfig({
  base: siteBase(),
  plugins: [
    viteStaticCopy({
      targets: [
        { src: 'assets', dest: '.' },
        // Spanish share URL: static tags for link previews, then a redirect.
        { src: 'es', dest: '.' },
        { src: 'data', dest: '.' },
        { src: 'studios/i18n.json', dest: 'studios' },
        { src: 'saliency', dest: '.' },
        { src: 'saliency_alts', dest: '.' },
        { src: 'saliency_world', dest: '.' },
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
        if (process.env.VITE_SUPABASE_URL) {
          for (const file of AUTOPSY_BLOBS) {
            rmSync(resolve(__dirname, 'dist/data', file), { force: true });
          }
        }
        const origin = deployOrigin();
        if (origin && origin !== PAGES_ORIGIN) {
          rewriteOrigins(resolve(__dirname, 'dist'), origin);
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
        studios: resolve(__dirname, 'studios/index.html'),
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
