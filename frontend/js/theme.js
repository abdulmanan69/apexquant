// Theme toggle persisted per browser; Settings can also store it server-side.
export function currentTheme() {
  try { return localStorage.getItem('apex-theme') || document.documentElement.dataset.theme || 'light'; } catch (_) { return 'light'; }
}
export function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('apex-theme', t); } catch (_) { /* private mode */ }
  document.dispatchEvent(new CustomEvent('themechange', { detail: t }));
}
export function initTheme() { setTheme(currentTheme()); }
