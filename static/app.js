const $ = id => document.getElementById(id);
let topMode = true, page = 1, searchTimer, total = 0;
const detailId = location.pathname.startsWith('/email/') ? location.pathname.split('/')[2] : null;
async function api(path, options = {}) {
  const r = await fetch(path, { ...options, headers: {'Content-Type':'application/json','X-Email-Assist':'1',...(options.headers || {})} });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed. Please try again.'); }
  return r.json();
}
function date(value) { return value ? new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}) : 'Not yet'; }
function node(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if(cls) e.className = cls; return e; }
function score(value) { const e = node('div', value ?? '—', 'score'+(value >= 85 ? ' urgent' : '')); e.append(node('small',value == null ? 'PENDING' : '/ 100')); return e; }
async function loadEmails() {
  try {
    const d = await api(`/api/emails?top=${topMode}&page=${page}&q=${encodeURIComponent($('search').value)}`);
    total = d.total; $('emails').replaceChildren();
    d.emails.forEach((item,i) => {
      const card=node('article',undefined,'email'); card.append(node('div',String(topMode ? i+1 : (page-1)*50+i+1).padStart(2,'0'),'rank'),score(item.score));
      const main=node('div');const link=node('a',item.subject || '(No subject)');link.href='/email/'+item.id;main.append(link,node('div',item.sender,'sender'));
      if(item.reason) main.append(node('p',item.reason));
      if(item.suggested_action && topMode) main.append(node('p', 'Next: '+item.suggested_action));
      main.append(node('div',`${date(item.sent_at)} · ${item.analyze_date ? 'Analyzed '+date(item.analyze_date) : 'Awaiting analysis'}`,'metadata'));
      card.append(main,node('span','↗','arrow'));$('emails').append(card);
    });
    if(!d.emails.length) $('emails').append(node('div',topMode ? 'No reply recommendations yet. Connect your inbox or refresh to score emails.' : 'No matching emails.','empty'));
    $('pagination').hidden=topMode || total<=50;$('prev').disabled=page<=1;$('next').disabled=page*50>=total;$('page-label').textContent=`Page ${page} · ${total} emails`;
  } catch(e) { showError(e.message); }
}
function showError(text) { $('status').textContent=text;$('status').classList.add('error'); }
async function loadStatus() {
  try {
    const d=await api('/api/status');$('inbox-count').textContent=d.inbox.toLocaleString();$('scored-count').textContent=d.scored.toLocaleString();$('last-scan').textContent=d.last_scan ? new Date(d.last_scan).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}) : 'Not yet';
    $('setup').hidden=d.configured;$('model-label').textContent=d.model;$('refresh').disabled=d.running || !d.configured;
    $('status').classList.toggle('error',!!(d.error || d.last_error));
    $('status').textContent=d.running ? `${d.phase} · ${d.processed} / ${d.total} · ${d.analyzed} scored · ${d.cached} cached` : (d.error || d.last_error || (d.configured ? `Ready · Daily check at 07:00 ${d.timezone} · Last completed: ${date(d.last_success)}` : 'Add your Bridge IMAP password to start.'));
    if(!detailId && (d.running || loadStatus.wasRunning || !loadStatus.loaded)) { await loadEmails();loadStatus.loaded=true; }
    loadStatus.wasRunning=d.running;
  } catch(e) { showError(e.message); }
}
$('refresh').onclick=async()=>{try{await api('/api/refresh',{method:'POST'});await loadStatus();await loadEmails();}catch(e){showError(e.message);}};
$('setup-form').onsubmit=async e=>{e.preventDefault();const submit=e.target.querySelector('button');submit.disabled=true;$('setup-error').textContent='Checking credentials…';try{await api('/api/setup',{method:'POST',body:JSON.stringify({username:$('username').value,password:$('password').value})});$('password').value='';$('setup-error').textContent='';await loadStatus();}catch(err){$('setup-error').textContent=err.message;}finally{submit.disabled=false;}};
function mode(top){topMode=top;page=1;$('top-tab').classList.toggle('active',top);$('all-tab').classList.toggle('active',!top);$('search-box').hidden=top;$('list-title').textContent=top ? 'Ten replies worth your time' : 'Every title, one place';$('list-caption').textContent=top ? 'AI suggestions to help you decide what to answer next.' : 'Your inbox, sorted by score. Reading here leaves your mail unchanged.';loadEmails();}
$('top-tab').onclick=()=>mode(true);$('all-tab').onclick=()=>mode(false);$('prev').onclick=()=>{page--;loadEmails();};$('next').onclick=()=>{page++;loadEmails();};$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;loadEmails();},250);};
async function loadDetail(){ $('list-view').hidden=true;$('detail').hidden=false;try{const d=await api('/api/email/'+encodeURIComponent(detailId));$('detail-title').textContent=d.subject;$('detail-from').textContent=d.sender;$('detail-date').textContent=date(d.sent_at);$('detail-score').replaceWith(Object.assign(score(d.score),{id:'detail-score'}));$('detail-reason').textContent=d.reason || 'This email has not been scored yet.';$('detail-action').textContent=d.suggested_action || 'Refresh the inbox to analyze it.';$('detail-analysis').textContent=`Analyzed: ${date(d.analyze_date)} · ${d.model || 'Pending'}`;$('detail-body').textContent=d.body || '(No text preview available)';$('truncated').hidden=!d.truncated;$('copy-subject').onclick=async()=>{try{await navigator.clipboard.writeText(d.subject);$('copy-subject').textContent='Subject copied';}catch(e){showError('Copy failed. Select and copy the title above.');}};}catch(e){showError(e.message);}}
$('today').textContent=new Date().toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'}).toUpperCase()+' · YOUR REPLY QUEUE';
loadStatus();if(detailId)loadDetail();setInterval(loadStatus,5000);
