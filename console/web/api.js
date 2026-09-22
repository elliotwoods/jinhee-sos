// The bridge to Python: pywebview's js_api in the native window, or the loopback HTTP fallback.
const params = new URLSearchParams(location.search);
const TOKEN = params.get('token');

function native() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

export async function ready() {
  if (native()) return;
  if (TOKEN) return;               // browser fallback: nothing to wait for
  await new Promise((resolve) => {
    if (native()) return resolve();
    const done = () => resolve();
    window.addEventListener('pywebviewready', done, { once: true });
    setTimeout(() => { if (native()) resolve(); }, 3000);
    setTimeout(resolve, 8000);
  });
}

async function invoke(method, args) {
  const api = native();
  if (api) return api[method](...args);
  const response = await fetch(`/api/${method}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` },
    body: JSON.stringify({ args }),
  });
  return response.json();
}

export const api = {
  ping: () => invoke('ping', []),
  pull: (since, sinceSeq) => invoke('pull', [since, sinceSeq]),
  call: (name, args) => invoke('call', [name, args || {}]),
  confirm: (name, args) => invoke('confirm', [name, args || {}]),
  getCopy: () => invoke('get_copy', []),
  getLines: (device, sinceSeq, limit) => invoke('get_lines', [device, sinceSeq || 0, limit || 500]),
  shutdown: () => invoke('shutdown', []),
  mode: () => (native() ? 'native' : 'browser'),
};

// Call a command; destructive commands are confirmed first (server-side token, fetched by a completed hold).
export async function run(name, args, { confirmed = false } = {}) {
  let payload = { ...(args || {}) };
  if (confirmed) {
    const c = await api.confirm(name, payload);
    if (!c || !c.token) throw new Error((c && c.error) || 'Could not confirm the action');
    payload = { ...payload, token: c.token };
  }
  const result = await api.call(name, payload);
  if (!result || result.ok === false) throw new Error((result && result.error) || 'The backend refused');
  return result.result;
}
