/* Same-origin cookies keep session credentials out of application JavaScript. */
const $ = (s) => document.querySelector(s);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escapeHTML;
const date = value => value ? new Date(value).toLocaleString() : '—';
const money = (value, currency) => `${currency || ''} ${Number(value).toLocaleString(undefined, {maximumFractionDigits:8})}`;
let signedIn = false;
let visitOpen = false;
let activeTab = 'overview';
let state = {};
let noticeTimer = null;

function notice(message, error = false) { clearTimeout(noticeTimer); if(message && !error) noticeTimer=setTimeout(()=>{if($('#notice').textContent===message)$('#notice').textContent='';},6000); $('#notice').textContent = message; $('#notice').className = error ? 'error' : ''; const feedback = $('#auth-feedback'); if (feedback) feedback.textContent = $('#auth-dialog').open && error ? message : ''; }
async function api(path, body, options = {}) {
  const response = await fetch(`/api/${path}`, {method:body ? 'POST':'GET', headers:{'Content-Type':'application/json'}, credentials:'same-origin', ...(body ? {body:JSON.stringify(body)} : {}), ...options});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !['login','register'].includes(path)) showAuth();
    throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the form values and try again.');
  }
  return result;
}
function showAuth() { signedIn = false; visitOpen = false; document.body.classList.remove('is-signed-in'); $('#auth').hidden = false; $('#workspace').hidden = true; $('#identity').replaceChildren(); if ($('#auth-dialog').open) $('#auth-dialog').close(); }
function fields(form) { return Object.fromEntries(new FormData(form)); }
function numeric(data, keys) { keys.forEach(k => data[k] = Number(data[k])); return data; }
async function submit(form, work) {
  const buttons = [...form.querySelectorAll('button')]; const disabled=buttons.map(b=>b.disabled); form.setAttribute('aria-busy','true'); buttons.forEach(b => b.disabled = true);
  try { await work(); } catch (err) { notice(err.message, true); }
  finally { buttons.forEach((b,i) => b.disabled = disabled[i]); form.removeAttribute('aria-busy'); }
}
function list(selector, rows, render, empty) {
  const actions={'#decisions':['discovery','Start in Discovery'],'#snapshots':['discovery','Capture an observation'],'#strategies':['discovery','Record a decision'],'#opportunities':['strategies','View strategy evidence'],'#lab-ideas':['lab','Start a hypothesis']};
  const action=actions[selector];
  $(selector).innerHTML=rows.length?rows.map(render).join(''):`<div class="empty-state"><span aria-hidden="true">${selector==='#lab-ideas'?'✳':'◇'}</span><h3>${selector==='#opportunities'?'Nothing needs your approval.':selector==='#lab-ideas'?'Give an idea a place to grow.':'Your evidence starts here.'}</h3><p>${e(empty)}</p>${action?`<button type="button" class="secondary" data-workspace-open="${action[0]}">${action[1]}</button>`:''}</div>`;
}
function setTab(tab) { activeTab = tab; $('#workspace-mobile-more').value=['overview','discovery','memory'].includes(tab)?'':tab; window.dispatchEvent(new CustomEvent('desk-tab', {detail:tab})); document.querySelectorAll('[data-view]').forEach(v => v.hidden = v.dataset.view !== tab); document.querySelectorAll('[data-tab]').forEach(b => { const active = b.dataset.tab === tab; b.classList.toggle('selected', active); b.setAttribute('aria-current', active ? 'page' : 'false'); }); }
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => setTab(button.dataset.tab)));

$('#workspace-mobile-more').addEventListener('change',event=>{if(event.target.value)setTab(event.target.value);});

async function refresh() {
  state = await api('state'); signedIn = true; $('#auth').hidden = true; $('#workspace').hidden = false; document.body.classList.add('is-signed-in'); if ($('#auth-dialog').open) $('#auth-dialog').close();
  $('#identity').innerHTML = `<span>${e(state.username)}</span><button class="secondary" id="signout">Sign out</button>`;
  $('#signout').addEventListener('click', async () => { try { await captureVisit('close'); await api('logout', {}); showAuth(); notice('Signed out.'); } catch (err) { notice(err.message, true); } });
  const pending = state.opportunities.filter(o => o.status === 'pending');
  $('#pending-count').textContent = pending.length ? `(${pending.length})` : '';
  $('#metrics').innerHTML = [[state.decisions.length,'Decisions logged'],[state.snapshots.length,'Snapshots kept'],[state.strategies.length,'Strategies tracked'],[pending.length,'Approvals waiting']].map(([value,label]) => `<div class="metric"><strong>${value}</strong><small>${label}</small></div>`).join('');
  renderRecentActivity();
  list('#quotes', state.quotes, q => `<div class="item"><strong>${e(q.symbol)}</strong> · ${e(money(q.price,q.currency))}<div class="meta">User-recorded · ${e(date(q.recorded_at))}</div></div>`, 'Your first recorded price starts the memory.');
  list('#alerts', state.alerts, a => `<div class="item"><strong>${e(a.symbol)}</strong> ${e(a.condition)} ${e(money(a.target,a.currency))} <span class="badge ${a.active?'pending':''}">${a.active?'Watching recorded prices':'Triggered'}</span>${a.triggered_at?`<div class="meta">${e(date(a.triggered_at))}</div>`:''}</div>`, 'No levels saved yet.');
  $('#visits').textContent = state.visits[0] ? `Last visit event: ${state.visits[0].kind} · ${date(state.visits[0].recorded_at)}` : 'Visits capture automatically after sign-in.';
  list('#snapshots', state.snapshots, s => `<article class="capture-entry" data-capture-kind="${e(s.kind)}" data-record-search="${e((s.symbol+' '+s.note).toLowerCase())}"><div class="entry-heading"><strong>${e(s.symbol)}</strong><span class="badge">${e(s.kind==='manual'?'Capture':s.kind+' visit')}</span></div><div class="capture-price">${e(money(s.price,s.currency))}</div><details class="entry-note"><summary>${e(s.note.slice(0,160))}${s.note.length>160?'…':''}</summary><p>${e(s.note)}</p></details><details class="entry-details"><summary>Capture details</summary><div class="meta">Captured ${e(date(s.recorded_at))}<br>Price recorded ${e(date(s.quote_recorded_at))}</div></details></article>`, 'Capture a manual snapshot or return after recording a price.');
  list('#decisions', state.decisions, d => `<article class="journal-entry" data-review-status="${d.outcome?'reviewed':'pending'}" data-record-search="${e((d.symbol+' '+d.setup+' '+d.note).toLowerCase())}"><div class="entry-heading"><div><span class="eyebrow">${e(d.symbol)} · ${e(d.side)}</span><h3>${e(d.setup)}</h3></div><span class="badge ${d.outcome==='loss'?'loss':d.outcome?'':'pending'}">${e(d.outcome||'Needs review')}</span></div><details class="entry-note"><summary>${e(d.note.slice(0,140))}${d.note.length>140?'…':''}</summary><p>${e(d.note)}</p></details><div class="entry-meta"><span>${e(money(d.price,d.currency))}</span><time>${e(date(d.recorded_at))}</time></div>${d.outcome?`<details class="entry-details"><summary>View lesson</summary><p>${e(d.lesson)}</p></details>`:`<details class="entry-details review-details"><summary>Review outcome <span aria-hidden="true">↗</span></summary><form class="review-form" data-decision="${d.id}"><label>What happened?<select name="outcome"><option value="win">Win</option><option value="loss">Loss</option></select></label><label>Lesson<textarea name="lesson" required maxlength="5000" placeholder="What will you carry into the next decision?"></textarea></label><button>Complete review</button></form></details>`}</article>`, 'Record your first decision in Discovery.');
  document.querySelectorAll('[data-decision]').forEach(form => form.addEventListener('submit', event => { event.preventDefault(); submit(form, async () => { await api(`decisions/${form.dataset.decision}/review`,fields(form)); await refresh(); notice('Outcome recorded. Strategy evidence updated.'); }); }));
  list('#strategies', state.strategies, s => `<article class="panel strategy-card" data-evidence-status="${s.eligible?'eligible':'building'}" data-record-search="${e((s.symbol+' '+s.setup).toLowerCase())}"><div class="eyebrow">${e(s.symbol)} · ${e(s.currency)}</div><h2>${e(s.setup)}</h2><div class="rate">${s.win_rate === null?'—':s.win_rate+'%'}</div><span class="badge ${s.eligible?'':'pending'}">${s.eligible?'Qualified by historical evidence':s.completed<10?'Building evidence':'Below 70% threshold'}</span><p>${s.wins} wins / ${s.completed} completed reviews · ${s.total-s.completed} pending</p><div class="meta">Propose ${e(s.side)} when price is ${e(s.condition)} ${e(money(s.trigger_price,s.currency))}.<br>Extracted from matching structured decision records.</div></article>`, 'Your journal builds these patterns. Use the same setup and rule for comparable decisions.');
  list('#opportunities', state.opportunities.filter(o=>o.status==='pending'), o => {
    const quote=state.quotes.find(q=>q.symbol===o.symbol&&q.currency===o.currency);
    return `<article class="panel ${o.status==='pending'?'opportunity':''}"><div class="eyebrow">${e(o.symbol)} · ${e(o.side.toUpperCase())} PROPOSAL</div><h2>${e(o.setup)}</h2><span class="badge ${o.status==='pending'?'pending':''}">${e(o.status)}</span><p>Matched ${e(o.condition)} ${e(money(o.trigger_price,o.currency))}<br>Detected at ${e(money(o.price,o.currency))} · ${e(date(o.recorded_at))}</p><div class="meta">${o.wins}/${o.completed} reviewed wins at detection. Latest price and eligibility are rechecked on approval.</div>${o.status==='pending'?`<p>Approval reference: ${quote?e(money(quote.price,quote.currency)):'Unavailable'}<br><span class="meta">${quote?e(date(quote.recorded_at)):''}</span></p><form data-opportunity="${o.id}" data-quote="${quote?.id||0}"><label>Paper quantity<input name="quantity" type="number" step="any" min="0.00000001" max="1000000" value="1" required></label><div class="actions"><button name="action" value="approve">Approve paper execution</button><button name="action" value="reject" class="secondary">Reject</button></div></form>`:''}</article>`;
  }, 'No matching opportunities yet. Qualified strategies create proposals when you record a matching price.');
  document.querySelectorAll('[data-opportunity]').forEach(form => form.addEventListener('submit', event => { event.preventDefault(); const action=event.submitter.value; submit(form, async () => { await api(`opportunities/${form.dataset.opportunity}/approval`,{action,quantity:Number(form.elements.quantity.value),expected_quote_id:Number(form.dataset.quote)}); await refresh(); notice(action==='approve'?'Approved. One paper order recorded; no real trade was placed.':'Proposal rejected.'); }); }));
  list('#orders', state.paper_orders, o => `<div class="item"><strong>${e(o.side.toUpperCase())} ${e(o.symbol)}</strong> · quantity ${e(o.quantity)} · reference ${e(money(o.reference_price,o.currency))}<div class="meta">Explicit approval #${o.opportunity_id} · ${e(date(o.recorded_at))} · simulated record, no broker fill</div></div>`, 'Orders appear only after your explicit approval.');
  list('#closed-opportunities',state.opportunities.filter(o=>o.status!=='pending'),o=>`<div class="history-row"><div><strong>${e(o.symbol)} · ${e(o.setup)}</strong><small>${e(date(o.recorded_at))}</small></div><span class="badge">${e(o.status)}</span></div>`,'No completed proposals yet.');
  await refreshLab();
  await refreshQuantProviders();
  setTab(activeTab);
  window.dispatchEvent(new CustomEvent('workspace-data'));
}

$('#auth-form').addEventListener('submit', event => {
  event.preventDefault();
  const path = event.submitter?.value;
  if (!['login','register'].includes(path)) return;
  submit(event.target, async () => {
    const payload = fields(event.target);
    if (path === 'register' && !payload.email) throw Error('Enter your email address to create an account.');
    const result = await api(path,payload);
    if (path === 'register' && result.verification_required) {
      event.target.reset();
      notice('Verification email sent. Check your inbox and spam folder.');
      $('#auth-feedback').textContent = 'Check your inbox and open the verification link. Then sign in.';
      return;
    }
    event.target.reset();
    await refresh();
    await captureVisit('open');
    await refresh();
    notice('Your notebook is ready.');
  });
});
$('#resend-verification-form').addEventListener('submit', event => {
  event.preventDefault();
  submit(event.target, async () => {
    await api('auth/resend-verification', fields(event.target));
    notice('If verification is pending, check your inbox for a new link.');
  });
});
async function verifyEmailFromLink() {
  const match = window.location.hash.match(/^#verify-email=([A-Za-z0-9_-]{32,128})$/);
  if (!match) return;
  // Remove secret token from the address bar/history before network calls.
  history.replaceState(null, '', window.location.pathname + window.location.search);
  try {
    const result = await api('auth/verify-email', {token: match[1]});
    openAuthDialog();
    notice(result.message);
    $('#auth-feedback').textContent = result.message;
  } catch (error) {
    openAuthDialog();
    notice(error.message, true);
    $('#auth-feedback').textContent = error.message;
  }
}
const bindings = [['quote-form','quotes',['price'],'Price recorded. Alerts and eligible strategies checked.'],['snapshot-form','snapshots',[],'Snapshot preserved.'],['decision-form','decisions',['price','trigger_price'],'Decision saved. Review it when the outcome is known.'],['alert-form','alerts',['target'],'Alert saved.']];
bindings.forEach(([id,path,keys,message]) => { const form=$('#'+id); let requestId=null; form.addEventListener('submit', event => { event.preventDefault(); submit(form, async () => { const data=numeric(fields(form),keys); if(path==='decisions') { requestId ||= crypto.randomUUID(); data.request_id=requestId; } await api(path,data); requestId=null; form.reset(); await refresh(); notice(message); }); }); form.addEventListener('input',()=>{requestId=null;}); });

async function captureVisit(kind) {
  if (!signedIn || (kind==='open' && visitOpen) || (kind==='close' && !visitOpen)) return;
  // Closing is sent with keepalive; reopening creates a new capture episode.
  visitOpen = kind==='open';
  try { await api('visits',{kind,event_id:crypto.randomUUID()},{keepalive:kind==='close'}); }
  catch (err) { if(kind==='open') visitOpen=false; }
}
document.addEventListener('visibilitychange', () => { if(document.visibilityState==='hidden') void captureVisit('close'); else if(signedIn) void captureVisit('open').then(refresh).catch(err=>notice(err.message,true)); });
window.addEventListener('pagehide',()=>{void captureVisit('close');});
refresh().then(async()=>{await captureVisit('open'); await refresh();}).catch(err=>{showAuth(); if(!err.message.includes('Sign in')) notice(err.message,true);}).finally(()=>{void verifyEmailFromLink();});

async function refreshLab() {
  const data = await api('lab');
  list('#lab-ideas', data.ideas, idea => {
    const notes=data.notes.filter(n=>n.idea_id===idea.id);
    return `<article class="panel"><div class="eyebrow">${e(idea.symbol)} · ${e(idea.timeframe)} · PRIVATE</div><h2>${e(idea.title)}</h2><details class="entry-note"><summary>${e(idea.hypothesis.slice(0,160))}${idea.hypothesis.length>160?'…':''}</summary><p>${e(idea.hypothesis)}</p></details><div class="meta">${e(date(idea.created_at))}</div><div class="actions"><button class="secondary" data-evidence="${idea.id}">Find journal evidence</button></div><div id="lab-evidence-${idea.id}" class="stack"></div><div class="stack">${notes.map(n=>`<div class="item">${e(n.content)}<div class="meta">${e(date(n.created_at))}</div></div>`).join('')}</div><details class="entry-details"><summary>Add a research note</summary><form data-lab-note="${idea.id}"><label>Brainstorm note<textarea name="content" required maxlength="5000" placeholder="What conditions would invalidate this idea?"></textarea></label><button>Save note</button></form></details></article>`;
  }, 'No drafts yet. Start with one hypothesis.');
  document.querySelectorAll('[data-lab-note]').forEach(form=>form.addEventListener('submit',event=>{
    event.preventDefault();submit(form,async()=>{await api('lab/'+form.dataset.labNote+'/notes',fields(form));await refreshLab();notice('Research note saved.');});
  }));
  document.querySelectorAll('[data-evidence]').forEach(button=>button.addEventListener('click',async()=>{
    try { const result=await api('lab/'+button.dataset.evidence+'/evidence');
      list('#lab-evidence-'+button.dataset.evidence,result.evidence,d=>`<div class="item"><strong>${e(d.setup)}</strong><p>${e(d.note)}</p><div class="meta">Outcome: ${e(d.outcome||'pending')} · Journal #${d.id}</div></div>`,'No same-symbol journal records yet.');
      notice('Retrieved journal evidence. This is not a backtest or predictive score.');
    }catch(err){notice(err.message,true);}
  }));
}
$('#lab-form').addEventListener('submit',event=>{
  event.preventDefault();submit(event.target,async()=>{await api('lab',fields(event.target));event.target.reset();await refreshLab();window.dispatchEvent(new CustomEvent('workspace-switch',{detail:{group:'lab',pane:'drafts'}}));notice('Private strategy draft saved.');});
});

function showQuant(selector, obj) {
  const labels={count:'Reviewed sample',wins:'Winning trades',win_rate:'Observed win rate',mean_return:'Mean net return',sample_std:'Sample volatility',profit_factor:'Profit factor',compounded_return:'Compounded return',max_drawdown:'Maximum drawdown',theoretical_price:'Theoretical price',delta:'Delta',gamma:'Gamma',vega_per_1_vol_unit:'Vega · per 1.0 vol',bars:'Bars returned'};
  const percents=new Set(['win_rate','mean_return','sample_std','compounded_return','max_drawdown']);
  const metrics=Object.entries(labels).filter(([key])=>Object.hasOwn(obj,key)).map(([key,label])=>{const value=obj[key];return `<div class="result-metric"><small>${label}</small><strong>${value==null?'—':e((percents.has(key)?100*value:value).toLocaleString(undefined,{maximumFractionDigits:4}))+(percents.has(key)&&value!=null?'%':'')}</strong></div>`;}).join('');
  const interval=obj.win_rate_wilson_95;
  $(selector).innerHTML=(obj.message?'<div class="context-note"><p>'+e(obj.message)+'</p></div>':'')+'<div class="result-grid">'+metrics+'</div>'+(interval?'<p class="meta">95% interval for the sample win rate: '+e((100*interval.lower).toFixed(1))+'% – '+e((100*interval.upper).toFixed(1))+'%.</p>':'')+(obj.model?'<p class="meta">'+e(obj.model)+'</p>':'')+(obj.caveat?'<p class="calculation-note">'+e(obj.caveat)+'</p>':'')+'<details class="context-details"><summary>Calculation details</summary><pre class="quant-output">'+e(JSON.stringify(obj,null,2))+'</pre></details>';
}
async function refreshQuantProviders() { try { const r=await api('markets/providers'); list('#provider-result',r.markets,m=>'<div class="item"><strong>'+e(m.market)+'</strong> · '+e(m.provider)+' <span class="badge '+(m.available?'':'pending')+'">'+(m.available?'Available':'Credentials required')+'</span></div>','No providers'); }catch(err){ $('#provider-result').textContent=err.message; } }
$('#quant-trades').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{const raw=fields(event.target).returns;const values=raw.split(',').map(x=>Number(x.trim())/100);if(!raw.trim()||values.some(x=>!Number.isFinite(x)))throw Error('Enter valid comma-separated returns.');showQuant('#trade-result',await api('quant/trades',{returns:values}));});});
$('#quant-option').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{const v=fields(event.target);['spot','strike','years','volatility','rate'].forEach(k=>v[k]=Number(v[k]));showQuant('#option-result',await api('quant/option',v));});});
$('#market-form').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{const v=fields(event.target);if(v.market!=='crypto'){showQuant('#market-result',{message:'This provider needs server-side credentials and a provider-specific instrument selector. Open Discovery to search stocks and derivative contracts after connecting the provider.',provider:v.market});return;}const params=new URLSearchParams({symbol:v.symbol.toUpperCase(),interval:v.interval,limit:v.limit});const result=await api('markets/crypto/candles?'+params);showQuant('#market-result',{provider:result.provider,symbol:result.symbol,bars:result.candles.length,first:result.candles[0],last:result.candles.at(-1)});});});

$('#password-form').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{if(!confirm('Changing your password signs out every device. Continue?'))return;await api('auth/change-password',fields(event.target));event.target.reset();showAuth();notice('Password updated. Sign in with your new password.');});});
$('#logout-all').addEventListener('click',async()=>{if(!confirm('Revoke every active session?'))return;try{await api('auth/logout-all',{});showAuth();notice('All sessions revoked.');}catch(err){notice(err.message,true);}});

function renderIntelligence(report) {
  const analysis=report.analysis||{};
  const groups=[['The evidence','level_1_evidence'],['Quantitative findings','level_2_quantitative'],['Behavior observations','level_3_behavior'],['Hypotheses to test','level_4_hypotheses'],['Questions for the next entry','level_5_adaptation']];
  $('#intelligence-result').innerHTML='<div class="section-divider"><h2>Your evidence review</h2><span class="badge">Research hypotheses</span></div>'+groups.map(([title,key],i)=>{const items=analysis[key]||[];return `<details class="insight-section" ${i===0?'open':''}><summary><span>${title}</span><small>${items.length} observations</small></summary>${items.length?items.map(item=>`<article class="insight-item"><h3>${e(item.parameter||item.statement)}</h3><p>${e(item.observation||item.test_next||'')}</p>${item.alternative_explanation?`<p class="meta">Alternative explanation: ${e(item.alternative_explanation)}</p>`:''}${item.evidence_ids?.length?`<small class="evidence-refs">Evidence: ${e(item.evidence_ids.join(', '))}</small>`:''}</article>`).join(''):'<p class="meta">Not enough evidence in your entries yet.</p>'}</details>`;}).join('')+'<div class="calculation-note">'+(analysis.limitations||[]).map(e).join('<br>')+'</div>';
}
$('#analyze-memory').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  $('#intelligence-result').textContent = 'Analyzing recent evidence…';
  try {
    const report = await api('intelligence/analyze', {});
    renderIntelligence(report);
    const evolution = await api('intelligence/evolution');
    if (evolution.status === 'compared') {
      const summary = document.createElement('p');
      summary.className = 'muted';
      summary.textContent = 'Since the previous report: '+evolution.added.length+
        ' new parameters, '+evolution.revisited.length+' changed descriptions, '+
        evolution.missing.length+' not repeated. Changes require evidence review.';
      $('#intelligence-result').prepend(summary);
    }
    notice('Analysis saved to your private history.');
  } catch (err) {
    $('#intelligence-result').textContent = err.message;
    notice(err.message, true);
  } finally { button.disabled = false; }
});


/* Research Desk: intentional navigation and evidence-only overview. */
function renderRecentActivity() {
  const records = [
    ...(state.decisions || []).map(d => ({kind:'DECISION',title:d.symbol + ' · ' + d.setup,detail:d.outcome ? 'Reviewed: ' + d.outcome : 'Awaiting outcome review',at:d.recorded_at})),
    ...(state.snapshots || []).map(s => ({kind:'SNAPSHOT',title:s.symbol + ' · ' + s.kind,detail:s.note || 'Recorded market observation',at:s.recorded_at}))
  ].sort((a,b) => (Date.parse(b.at || '') || 0) - (Date.parse(a.at || '') || 0)).slice(0,4);
  $('#recent-activity').innerHTML = records.length
    ? records.map(r => '<div class="activity-row"><div><div class="eyebrow">' + e(r.kind) + '</div><strong>' + e(r.title) + '</strong><br><span>' + e(r.detail) + '</span></div><time>' + e(date(r.at)) + '</time></div>').join('')
    : '<div class="recent-empty"><h3>Your first entry starts the story.</h3><p>No market records yet. Capture an observation to build your timeline.</p></div>';
}
function openAuthDialog() {
  window.dispatchEvent(new CustomEvent('auth-open'));
  const dialog = $('#auth-dialog');
  if (!dialog.open) dialog.showModal();
  const username = dialog.querySelector('input[name="username"]');
  if (username) username.focus();
}
$('#open-auth').addEventListener('click', openAuthDialog);
$('#open-auth-top').addEventListener('click', openAuthDialog);
$('#close-auth').addEventListener('click', () => $('#auth-dialog').close());
document.querySelectorAll('[data-goto]').forEach(button => button.addEventListener('click', () => { setTab(button.dataset.goto); if(button.dataset.goto==='lab')window.dispatchEvent(new CustomEvent('workspace-switch',{detail:{group:'lab',pane:'new'}})); if(button.dataset.goto==='memory')window.dispatchEvent(new CustomEvent('workspace-switch',{detail:{group:'memory',pane:'decisions'}})); window.scrollTo({top:0,behavior:'smooth'}); }));
