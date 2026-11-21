#!/usr/bin/env node
// Checks a Markdown tracker against the triage rules: node check.mjs <issues dir>
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const dir = process.argv[2] ?? 'doc/issues';
const list = (v) => (v ? v.replace(/^\[|\]$/g, '').split(',').map((s) => s.trim()).filter(Boolean) : []);

const issues = readdirSync(dir).filter((f) => f.endsWith('.md')).map((file) => {
  const text = readFileSync(join(dir, file), 'utf8');
  const m = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) return { file, bad: 'no frontmatter' };
  const fm = Object.fromEntries(m[1].split('\n').map((l) => l.replace(/\s+#.*$/, '')).map((l) => {
    const i = l.indexOf(':');
    return [l.slice(0, i).trim(), l.slice(i + 1).trim()];
  }));
  return { file, fm, body: m[2] };
});

const errs = [];
const keys = new Set(issues.map((i) => i.fm?.key));
const seen = new Map();
for (const { file, fm, body, bad } of issues) {
  const e = (msg) => errs.push(`${file}: ${msg}`);
  if (bad) { e(bad); continue; }
  const labels = list(fm.labels);
  const marks = labels.filter((l) => l === 'agent-ready' || l === 'needs-human');
  // One request may feed several open issues (a split); otherwise it lives in one issue only.
  for (const s of list(fm.sources)) {
    const prev = seen.get(s);
    if (prev && (prev.status !== 'open' || fm.status !== 'open')) e(`${s} is also a source of ${prev.file}`);
    seen.set(s, { file, status: fm.status });
  }
  for (const k of [...list(fm['blocked-by']), ...(fm['duplicate-of'] ? [fm['duplicate-of']] : [])]) {
    if (!keys.has(k)) e(`refers to missing key ${k}`);
  }
  if (!labels.some((l) => l.startsWith('from:'))) e('no from: label');
  if (fm.status === 'open') {
    if (marks.length !== 1) e(`open issue needs exactly one mark, has ${marks.length}`);
    if (marks[0] === 'agent-ready') {
      for (const h of ['## Intent', '## Acceptance', '## Boundaries']) if (!body.includes(h)) e(`missing ${h}`);
      if (!/^- .*\bthen\b.*\bnot\b/m.test(body.split('## Acceptance')[1]?.split('## Boundaries')[0] ?? '')) e('no "must not happen" acceptance line');
      if (!/Allowed by AUT-1/.test(body)) e('no "Allowed by AUT-1" line');
    }
    if (marks[0] === 'needs-human') {
      for (const h of ['## Question', '## Options', '## Recommendation', '## Why']) if (!body.includes(h)) e(`missing ${h}`);
      if (!/^2\. /m.test(body)) e('fewer than two options');
    }
  } else if (fm.status === 'closed') {
    if (!['duplicate', 'obsolete', 'contradicts-spec', 'not-planned'].includes(fm.reason)) e(`bad reason ${fm.reason}`);
    if (fm.reason === 'duplicate' && !fm['duplicate-of']) e('duplicate without duplicate-of');
    if (marks.length) e('closed issue carries a mark');
    if (!/\b(AUT|DES|PRD|ADR)-\d+|\bSCHED-\d+|\bIN-\d+/.test(body)) e('closed issue cites nothing');
  } else if (fm.status !== 'done') e(`bad status ${fm.status}`);
}
// A request the collector filed is keyed by its id; it must be someone's source.
for (const { fm } of issues) {
  if (/^IN-\d+$/.test(fm?.key ?? '') && !seen.has(fm.key)) errs.push(`${fm.key} is in nobody's sources`);
}

console.log(errs.length ? errs.join('\n') : `ok · ${issues.length} issues`);
process.exit(errs.length ? 1 : 0);
