// sched-prod API: the incidents the status page and the board read. Contract: contract/api.md.

const json = (body, status = 200) => Response.json(body, { status });

async function feed(env) {
  const res = await fetch(env.FEED_URL);
  if (!res.ok) throw new Error(`feed answered ${res.status}`);
  const { incidents } = await res.json();
  return incidents;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname === '/incidents') {
      let incidents = await feed(env);
      const status = url.searchParams.get('status');
      if (status !== null) incidents = incidents.filter((i) => i.status === status);
      const since = url.searchParams.get('since');
      if (since !== null) {
        const t = Date.parse(since);
        // A bad time must not look like "nothing new" to a polling console.
        if (Number.isNaN(t)) return json({ error: 'since must be an ISO time' }, 400);
        incidents = incidents.filter((i) => Date.parse(i.openedAt) > t);
      }
      return json({ incidents });
    }
    const one = request.method === 'GET' && url.pathname.match(/^\/incidents\/([^/]+)$/);
    if (one) {
      let id;
      try { id = decodeURIComponent(one[1]); } catch { return json({ error: 'not found' }, 404); }
      const incident = (await feed(env)).find((i) => i.id === id);
      if (incident) return json({ incident });
    }
    return json({ error: 'not found' }, 404);
  },
};
