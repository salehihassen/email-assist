const $ = id => document.getElementById(id);
let rendered = {};
async function api(path, options = {}) {
  const r = await fetch(path, { ...options, headers: {'Content-Type':'application/json','X-Email-Assist':'1',...(options.headers || {})} });
  if (r.status === 401) {
    location.replace('/login?next=' + encodeURIComponent(location.pathname));
    throw new Error('Please sign in to continue.');
  }
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed. Please try again.'); }
  return r.json();
}
function date(value) { return value ? new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}) : 'Not yet'; }
function node(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if(cls) e.className = cls; return e; }
// Rebuild a list only when its content changes, so polling never swallows a click.
function render(key, data, build) { const sig = JSON.stringify(data); if (rendered[key] !== sig) { rendered[key] = sig; build(); } }
function showError(text) { $('status').hidden=false;$('status').textContent=text;$('status').classList.add('error'); }

$('logout').onclick = async () => {
  $('logout').disabled = true;
  try {
    await api('/api/logout', {method:'POST'});
    location.replace('/login');
  } catch (error) {
    showError(error.message);
    $('logout').disabled = false;
  }
};
// Recheck authentication if a browser restores a page from its back cache.
window.addEventListener('pageshow', event => { if (event.persisted) loadStatus(); });
