import { resolve } from 'node:path';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { mdsvex } from 'mdsvex';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [
    sveltekit({
      extensions: ['.svelte', '.svx'],
      preprocess: [mdsvex({ extensions: ['.svx'], layout: { runbook: resolve('src/lib/layouts/runbook.svelte') } })],
      adapter: adapter({ pages: 'rendered', assets: 'rendered', strict: false }),
      alias: { '#lib': 'src/lib' },
      // One self-contained file per page: the repo holds the page as the desk sees it.
      inlineStyleThreshold: Infinity,
      prerender: {
        entries: ['/kb', '/kb/incidents/4471', '/kb/incidents/4471-causes', '/kb/triage/dedupe', '/kb/decisions/0001-dedupe-by-subject'],
      },
    }),
  ],
});
