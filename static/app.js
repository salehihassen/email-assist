let topMode = true, page = 1, searchTimer, total = 0, providers = [], selected = localStorage.getItem('provider') || '';
const detailId = location.pathname.startsWith('/email/') ? location.pathname.split('/')[2] : null;
function score(value) { const e = node('div', value ?? '—', 'score'+(value >= 85 ? ' urgent' : '')); e.append(node('small',value == null ? 'PENDING' : '/ 100')); return e; }
const label = id => providers.find(p => p.id === id)?.label || id;
const latest = values => values.filter(Boolean).sort().at(-1);
async function loadEmails() {
  const current = selected;
  try {
    const d = await api(`/api/emails?provider=${encodeURIComponent(current)}&top=${topMode}&page=${page}&q=${encodeURIComponent($('search').value)}`);
    if (current !== selected) return;
    total = d.total; $('emails').replaceChildren();
    d.emails.forEach((item,i) => {
      const card=node('article',undefined,'email'); card.append(node('div',String(topMode ? i+1 : (page-1)*50+i+1).padStart(2,'0'),'rank'),score(item.score));
      const main=node('div');const link=node('a',item.subject || '(No subject)');link.href='/email/'+item.id;main.append(link,node('div',item.sender,'sender'));
      if(item.reason) main.append(node('p',item.reason));
      if(item.suggested_action && topMode) main.append(node('p', 'Next: '+item.suggested_action));
      const source = !current && providers.length > 1 ? label(item.provider)+' · ' : '';
      main.append(node('div',`${source}${date(item.sent_at)} · ${item.analyze_date ? 'Analyzed '+date(item.analyze_date) : 'Awaiting analysis'}`,'metadata'));
      card.append(main,node('span','↗','arrow'));$('emails').append(card);
    });
    if(!d.emails.length && !providers.length) { const empty=node('div','No mail providers yet. ','empty'),link=node('a','Add one to start ranking your inbox.');link.href='/providers';empty.append(link);$('emails').append(empty); }
    else if(!d.emails.length) $('emails').append(node('div',topMode ? 'No reply recommendations yet. Refresh to score emails.' : 'No matching emails.','empty'));
    $('pagination').hidden=topMode || total<=50;$('prev').disabled=page<=1;$('next').disabled=page*50>=total;$('page-label').textContent=`Page ${page} · ${total} emails`;
  } catch(e) { showError(e.message); }
}
function renderFilter() {
  render('filter', providers.map(p => [p.id,p.label,selected]), () => {
    $('filter').hidden = providers.length < 2;
    $('filter').replaceChildren(...[{id:'',label:'All inboxes'},...providers].map(p => {
      const b=node('button',p.label,'tab'+(p.id===selected ? ' active' : ''));b.type='button';b.onclick=()=>choose(p.id);return b;
    }));
  });
}
async function loadStatus() {
  try {
    const d=await api('/api/status');providers=d.providers;
    if (selected && !providers.some(p => p.id === selected)) { selected='';localStorage.setItem('provider',''); }
    const shown=selected ? providers.filter(p => p.id === selected) : providers, many=shown.length > 1, name=p => many ? p.label+': ' : '';
    $('inbox-count').textContent=shown.reduce((n,p) => n+p.inbox,0).toLocaleString();$('scored-count').textContent=shown.reduce((n,p) => n+p.scored,0).toLocaleString();
    const scan=latest(shown.map(p => p.last_scan));$('last-scan').textContent=scan ? new Date(scan).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}) : 'Not yet';
    $('model-label').textContent=d.model;$('refresh').textContent=many ? '↻ Refresh all inboxes' : '↻ Refresh inbox';$('refresh').disabled=shown.every(p => p.running || !p.configured);
    const running=shown.filter(p => p.running), failed=shown.filter(p => p.error || p.last_error), missing=shown.filter(p => !p.configured);
    $('status').classList.toggle('error',failed.length > 0);
    $('status').textContent=running.length ? running.map(p => `${name(p)}${p.phase} · ${p.processed} / ${p.total} · ${p.analyzed} scored · ${p.cached} cached`).join(' — ')
      : failed.length ? failed.map(p => name(p)+(p.error || p.last_error)).join(' — ')
      : !providers.length ? 'Add a mail provider under Providers to start.'
      : missing.length ? `Add credentials for ${missing.map(p => p.label).join(', ')} under Providers.`
      : `Ready · Daily check at 07:00 ${d.timezone} · Last completed: ${date(latest(shown.map(p => p.last_success)))}`;
    renderFilter();
    const busy=running.length > 0;
    if(!detailId && (busy || loadStatus.wasRunning || !loadStatus.loaded)) { await loadEmails();loadStatus.loaded=true; }
    loadStatus.wasRunning=busy;
  } catch(e) { showError(e.message); }
}
function choose(id) {
  selected=id;localStorage.setItem('provider',id);
  if (detailId) { location.assign('/'); return; }
  page=1;$('search').value='';$('emails').replaceChildren();loadStatus.loaded=false;loadStatus();
}
$('refresh').onclick=async()=>{try{await api('/api/refresh?provider='+encodeURIComponent(selected),{method:'POST'});await loadStatus();await loadEmails();}catch(e){showError(e.message);}};
function mode(top){topMode=top;page=1;$('top-tab').classList.toggle('active',top);$('all-tab').classList.toggle('active',!top);$('search-box').hidden=top;$('list-title').textContent=top ? 'Ten replies worth your time' : 'Every title, one place';$('list-caption').textContent=top ? 'AI suggestions to help you decide what to answer next.' : 'Your inbox, sorted by score. Reading here leaves your mail unchanged.';loadEmails();}
$('top-tab').onclick=()=>mode(true);$('all-tab').onclick=()=>mode(false);$('prev').onclick=()=>{page--;loadEmails();};$('next').onclick=()=>{page++;loadEmails();};$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;loadEmails();},250);};
async function loadDetail(){ $('list-view').hidden=true;$('detail').hidden=false;try{const d=await api('/api/email/'+encodeURIComponent(detailId));const p=providers.find(x => x.id === d.provider);$('detail-title').textContent=d.subject;$('detail-from').textContent=d.sender;$('detail-date').textContent=`${date(d.sent_at)} · ${label(d.provider)}`;$('detail-score').replaceWith(Object.assign(score(d.score),{id:'detail-score'}));$('detail-reason').textContent=d.reason || 'This email has not been scored yet.';$('detail-action').textContent=d.suggested_action || 'Refresh the inbox to analyze it.';$('detail-analysis').textContent=`Analyzed: ${date(d.analyze_date)} · ${d.model || 'Pending'}`;$('detail-body').textContent=d.body || '(No text preview available)';$('truncated').hidden=!d.truncated;$('webmail').hidden=!p?.webmail;if(p?.webmail){$('webmail').href=p.webmail;$('webmail').textContent=`Open ${p.label} webmail ↗`;}$('copy-subject').onclick=async()=>{try{await navigator.clipboard.writeText(d.subject);$('copy-subject').textContent='Subject copied';}catch(e){showError('Copy failed. Select and copy the title above.');}};}catch(e){showError(e.message);}}
$('today').textContent=new Date().toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'}).toUpperCase()+' · YOUR REPLY QUEUE';
async function init(){
  await loadStatus();
  if(detailId) await loadDetail();
  setInterval(loadStatus,5000);
}
init();
