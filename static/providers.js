let providers = [], editing = null;
function providerState(p) {
  if (p.running) return `${p.phase} · ${p.processed} / ${p.total}`;
  if (p.error || p.last_error) return p.error || p.last_error;
  if (!p.configured) return 'Credentials needed';
  return `${p.inbox.toLocaleString()} emails in inbox · Last checked ${date(p.last_scan)}`;
}
function renderProviders() {
  render('providers', providers.map(p => [p.id,p.label,p.type,p.host,p.port,p.username,providerState(p),p.managed]), () => {
    $('provider-list').replaceChildren(...providers.map(p => {
      const row=node('div',undefined,'provider-row'), info=node('div'), actions=node('div',undefined,'row-actions');
      const where = p.type === 'bridge' ? 'Proton Mail Bridge' : `IMAP · ${p.host}:${p.port}`;
      info.append(node('strong',p.label),node('div',[where,p.username,p.managed ? 'Set by environment' : ''].filter(Boolean).join(' · '),'sender'),node('div',providerState(p),'metadata'));
      const edit=node('button','Edit','secondary');edit.type='button';edit.onclick=()=>openForm(p);actions.append(edit);
      if (!p.managed) { const del=node('button','Remove','secondary');del.type='button';del.onclick=()=>removeProvider(p);actions.append(del); }
      row.append(info,actions);return row;
    }));
    if (!providers.length) $('provider-list').append(node('div','No mail providers yet. Add one to start ranking your inbox.','empty'));
  });
}
async function loadStatus() {
  try {
    providers=(await api('/api/status')).providers;renderProviders();
    if (!providers.length && !loadStatus.loaded) openForm(null);
    loadStatus.loaded=true;
  } catch(e) { showError(e.message); }
}
const fields = ['label','type','host','port','username','webmail','focus'];
function syncType() {
  const bridge=$('f-type').value === 'bridge';
  document.querySelectorAll('.imap-only').forEach(e => e.hidden=bridge);$('f-host').required=!bridge;
  $('form-hint').textContent=(bridge ? 'Use the IMAP username and password shown in Proton Mail Bridge.' : 'Enable IMAP access in your mail settings and use an app-specific password where available. Port 993 uses implicit TLS.')
    +(editing && providers.find(p => p.id === editing)?.locked.length ? ' Greyed-out fields are set by environment variables.' : '');
}
function openForm(p) {
  editing=p ? p.id : '';$('provider-form').hidden=false;$('form-result').textContent='';$('form-result').classList.remove('error-text');
  $('form-title').textContent=p ? `Edit ${p.label}` : 'Add a provider';
  fields.forEach(f => { $('f-'+f).value=p ? p[f] : {type:'imap',port:993}[f] ?? ''; $('f-'+f).disabled=!!p?.locked.includes(f); });
  const fixed=p && ['file','env'].includes(p.password_source);
  $('f-password').value='';$('f-password').disabled=fixed;
  $('f-password').placeholder={file:'Set by secrets file',env:'Set by environment',saved:'Saved · leave blank to keep'}[p?.password_source] || '';
  syncType();$('provider-form').scrollIntoView({behavior:'smooth',block:'nearest'});$('f-label').focus();
}
function closeForm() { editing=null;$('provider-form').hidden=true;$('f-password').value=''; }
function formBody() { const body=Object.fromEntries(fields.map(f => [f,$('f-'+f).value.trim()]));body.port=Number(body.port) || 993;body.password=$('f-password').value;return body; }
function formResult(text, error) { $('form-result').textContent=text;$('form-result').classList.toggle('error-text',!!error); }
$('provider-form').onsubmit=async e => {
  e.preventDefault();const submit=e.target.querySelector('button[type=submit]');submit.disabled=true;
  try {
    await api(editing ? '/api/providers/'+encodeURIComponent(editing) : '/api/providers',{method:editing ? 'PUT' : 'POST',body:JSON.stringify(formBody())});
    closeForm();rendered.providers=null;await loadStatus();
  } catch(err) { formResult(err.message,true); } finally { submit.disabled=false; }
};
$('test-provider').onclick=async () => {
  $('test-provider').disabled=true;formResult('Testing connection…');
  try { const d=await api('/api/providers/test',{method:'POST',body:JSON.stringify({...formBody(),id:editing || ''})});formResult(`Connected · ${d.inbox.toLocaleString()} emails in inbox`); }
  catch(err) { formResult(err.message,true); } finally { $('test-provider').disabled=false; }
};
async function removeProvider(p) {
  if (!confirm(`Remove ${p.label}? Its cached emails and scores will be deleted. Your mailbox is not changed.`)) return;
  try { await api('/api/providers/'+encodeURIComponent(p.id),{method:'DELETE'});if(editing === p.id) closeForm();await loadStatus(); } catch(e) { formResult(e.message,true); }
}
$('f-type').onchange=syncType;$('cancel-provider').onclick=closeForm;$('add-provider').onclick=()=>openForm(null);
loadStatus();setInterval(loadStatus,5000);
