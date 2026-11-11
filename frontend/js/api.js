// Fetch wrappers. Every error becomes an Error with a readable message.
async function handle(r) {
  let body = null;
  try { body = await r.json(); } catch (_) { body = null; }
  if (!r.ok) {
    const msg = body && body.error ? body.error.message : (body && body.detail ? JSON.stringify(body.detail) : `HTTP ${r.status}`);
    const e = new Error(msg); e.status = r.status; e.body = body; throw e;
  }
  return body;
}
export const api = {
  get: (url) => fetch(url, { headers: { Accept: 'application/json' } }).then(handle),
  post: (url, data) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(handle),
  patch: (url, data) => fetch(url, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(handle),
  upload: (url, formData) => fetch(url, { method: 'POST', body: formData }).then(handle),
};
