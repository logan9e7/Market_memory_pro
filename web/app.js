/* Same-origin cookies keep session credentials out of application JavaScript. */
const $ = (s) => document.querySelector(s);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escapeHTML;
const date = value => value ? new Date(value).toLocaleString() : '—';
const money = (value, currency) => `${currency || ''} ${Number(value).toLocaleString(undefined, {maximumFractionDigits:8})}`;
let signedIn = false;
let visitOpen = false;
let activeTab = 'capture';
let state = {};

function notice(message, error = false) { $('#notice').textContent = message; $('#notice').className = error ? 'error' : ''; }
async function api(path, body, options = {}) {
  const response = await fetch(`/api/${path}`, {method:body ? 'POST':'GET', headers:{'Content-Type':'application/json'}, credentials:'same-origin', ...(body ? {body:JSON.stringify(body)} : {}), ...options});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !['login','register'].includes(path)) showAuth();
    throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the form values and try again.');
  }
  return result;
}
function showAuth() { signedIn = false; visitOpen = false; $('#auth').hidden = false; $('#workspace').hidden = true; $('#identity').replaceChildren(); }
function fields(form) { return Object.fromEntries(new FormData(form)); }
function numeric(data, keys) { keys.forEach(k => data[k] = Number(data[k])); return data; }
async function submit(form, work) {
  const buttons = form.querySelectorAll('button'); buttons.forEach(b => b.disabled = true);
  try { await work(); } catch (err) { notice(err.message, true); }
  finally { buttons.forEach(b => b.disabled = false); }
}
function list(selector, rows, render, empty) { $(selector).innerHTML = rows.length ? rows.map(render).join('') : `<div class="empty">${e(empty)}</div>`; }
function setTab(tab) { activeTab = tab; document.querySelectorAll('[data-view]').forEach(v => v.hidden = v.dataset.view !== tab); document.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('selected', b.dataset.tab === tab)); }
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => setTab(button.dataset.tab)));

async function refresh() {
  state = await api('state'); signedIn = true; $('#auth').hidden = true; $('#workspace').hidden = false;
  $('#identity').innerHTML = `<span>${e(state.username)}</span><button class="secondary" id="signout">Sign out</button>`;
  $('#signout').addEventListener('click', async () => { try { await captureVisit('close'); await api('logout', {}); showAuth(); notice('Signed out.'); } catch (err) { notice(err.message, true); } });
  const pending = state.opportunities.filter(o => o.status === 'pending');
  $('#pending-count').textContent = pending.length ? `(${pending.length})` : '';
  $('#metrics').innerHTML = [[state.decisions.length,'Recent decisions'],[state.strategies.filter(s=>s.eligible).length,'Strategies above 70%'],[pending.length,'Awaiting your approval'],[state.snapshots.length,'Recent captured moments']].map(([value,label]) => `<div class="metric"><strong>${value}</strong><small>${label}</small></div>`).join('');
  list('#quotes', state.quotes, q => `<div class="item"><strong>${e(q.symbol)}</strong> · ${e(money(q.price,q.currency))}<div class="meta">User-recorded · ${e(date(q.recorded_at))}</div></div>`, 'Your first recorded price starts the memory.');
  list('#alerts', state.alerts, a => `<div class="item"><strong>${e(a.symbol)}</strong> ${e(a.condition)} ${e(money(a.target,a.currency))} <span class="badge ${a.active?'pending':''}">${a.active?'Watching recorded prices':'Triggered'}</span>${a.triggered_at?`<div class="meta">${e(date(a.triggered_at))}</div>`:''}</div>`, 'No levels saved yet.');
  $('#visits').textContent = state.visits[0] ? `Last visit event: ${state.visits[0].kind} · ${date(state.visits[0].recorded_at)}` : 'Visits capture automatically after sign-in.';
  list('#snapshots', state.snapshots, s => `<div class="item"><strong>${e(s.symbol)}</strong> · ${e(money(s.price,s.currency))} <span class="badge">${e(s.kind)}</span><p>${e(s.note)}</p><div class="meta">Captured ${e(date(s.recorded_at))}<br>Price recorded ${e(date(s.quote_recorded_at))}</div></div>`, 'Capture a manual snapshot or return after recording a price.');
  list('#decisions', state.decisions, d => `<div class="item"><strong>${e(d.symbol)} · ${e(d.setup)}</strong> <span class="badge ${d.outcome === 'loss'?'loss':d.outcome?'':'pending'}">${e(d.outcome || 'Needs review')}</span><p>${e(d.note)}</p><div class="meta">${e(d.side)} · ${e(money(d.price,d.currency))} · ${e(date(d.recorded_at))}</div>${d.outcome?`<p>Lesson: ${e(d.lesson)}</p>`:`<form class="review-form" data-decision="${d.id}"><label>What happened?<select name="outcome"><option value="win">Win</option><option value="loss">Loss</option></select></label><label>Lesson<textarea name="lesson" required maxlength="5000"></textarea></label><button>Complete review</button></form>`}</div>`, 'Record your first decision in Capture.');
  document.querySelectorAll('[data-decision]').forEach(form => form.addEventListener('submit', event => { event.preventDefault(); submit(form, async () => { await api(`decisions/${form.dataset.decision}/review`,fields(form)); await refresh(); notice('Outcome recorded. Strategy evidence updated.'); }); }));
  list('#strategies', state.strategies, s => `<article class="panel"><div class="eyebrow">${e(s.symbol)} · ${e(s.currency)}</div><h2>${e(s.setup)}</h2><div class="rate">${s.win_rate === null?'—':s.win_rate+'%'}</div><span class="badge ${s.eligible?'':'pending'}">${s.eligible?'Qualified by historical evidence':s.completed<10?'Building evidence':'Below 70% threshold'}</span><p>${s.wins} wins / ${s.completed} completed reviews · ${s.total-s.completed} pending</p><div class="meta">Propose ${e(s.side)} when price is ${e(s.condition)} ${e(money(s.trigger_price,s.currency))}.<br>Extracted from matching structured decision records.</div></article>`, 'Your journal builds these patterns. Use the same setup and rule for comparable decisions.');
  list('#opportunities', state.opportunities, o => {
    const quote=state.quotes.find(q=>q.symbol===o.symbol&&q.currency===o.currency);
    return `<article class="panel ${o.status==='pending'?'opportunity':''}"><div class="eyebrow">${e(o.symbol)} · ${e(o.side.toUpperCase())} PROPOSAL</div><h2>${e(o.setup)}</h2><span class="badge ${o.status==='pending'?'pending':''}">${e(o.status)}</span><p>Matched ${e(o.condition)} ${e(money(o.trigger_price,o.currency))}<br>Detected at ${e(money(o.price,o.currency))} · ${e(date(o.recorded_at))}</p><div class="meta">${o.wins}/${o.completed} reviewed wins at detection. Latest price and eligibility are rechecked on approval.</div>${o.status==='pending'?`<p>Approval reference: ${quote?e(money(quote.price,quote.currency)):'Unavailable'}<br><span class="meta">${quote?e(date(quote.recorded_at)):''}</span></p><form data-opportunity="${o.id}" data-quote="${quote?.id||0}"><label>Paper quantity<input name="quantity" type="number" step="any" min="0.00000001" max="1000000" value="1" required></label><div class="actions"><button name="action" value="approve">Approve paper execution</button><button name="action" value="reject" class="secondary">Reject</button></div></form>`:''}</article>`;
  }, 'No matching opportunities yet. Qualified strategies create proposals when you record a matching price.');
  document.querySelectorAll('[data-opportunity]').forEach(form => form.addEventListener('submit', event => { event.preventDefault(); const action=event.submitter.value; submit(form, async () => { await api(`opportunities/${form.dataset.opportunity}/approval`,{action,quantity:Number(form.elements.quantity.value),expected_quote_id:Number(form.dataset.quote)}); await refresh(); notice(action==='approve'?'Approved. One paper order recorded; no real trade was placed.':'Proposal rejected.'); }); }));
  list('#orders', state.paper_orders, o => `<div class="item"><strong>${e(o.side.toUpperCase())} ${e(o.symbol)}</strong> · quantity ${e(o.quantity)} · reference ${e(money(o.reference_price,o.currency))}<div class="meta">Explicit approval #${o.opportunity_id} · ${e(date(o.recorded_at))} · simulated record, no broker fill</div></div>`, 'Orders appear only after your explicit approval.');
  await refreshLab();
  await refreshQuantProviders();
  setTab(activeTab);
}

$('#auth-form').addEventListener('submit', event => { event.preventDefault(); const path = event.submitter.value; submit(event.target, async () => { await api(path,fields(event.target)); event.target.reset(); await refresh(); await captureVisit('open'); await refresh(); notice('Your notebook is ready.'); }); });
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
refresh().then(async()=>{await captureVisit('open'); await refresh();}).catch(err=>{showAuth(); if(!err.message.includes('Sign in')) notice(err.message,true);});

async function refreshLab() {
  const data = await api('lab');
  list('#lab-ideas', data.ideas, idea => {
    const notes=data.notes.filter(n=>n.idea_id===idea.id);
    return `<article class="panel"><div class="eyebrow">${e(idea.symbol)} · ${e(idea.timeframe)} · PRIVATE</div><h2>${e(idea.title)}</h2><p>${e(idea.hypothesis)}</p><div class="meta">${e(date(idea.created_at))}</div><div class="actions"><button class="secondary" data-evidence="${idea.id}">Find journal evidence</button></div><div id="lab-evidence-${idea.id}" class="stack"></div><div class="stack">${notes.map(n=>`<div class="item">${e(n.content)}<div class="meta">${e(date(n.created_at))}</div></div>`).join('')}</div><form data-lab-note="${idea.id}"><label>Brainstorm note<textarea name="content" required maxlength="5000" placeholder="What conditions would invalidate this idea?"></textarea></label><button>Save note</button></form></article>`;
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
  event.preventDefault();submit(event.target,async()=>{await api('lab',fields(event.target));event.target.reset();await refreshLab();notice('Private strategy draft saved.');});
});

function showQuant(selector, obj) { $(selector).innerHTML='<pre class="quant-output">'+e(JSON.stringify(obj,null,2))+'</pre>'; }
async function refreshQuantProviders() { try { const r=await api('markets/providers'); list('#provider-result',r.markets,m=>'<div class="item"><strong>'+e(m.market)+'</strong> · '+e(m.provider)+' <span class="badge '+(m.available?'':'pending')+'">'+(m.available?'Available':'Credentials required')+'</span></div>','No providers'); }catch(err){ $('#provider-result').textContent=err.message; } }
$('#quant-trades').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{const raw=fields(event.target).returns;const values=raw.split(',').map(x=>Number(x.trim())/100);if(!raw.trim()||values.some(x=>!Number.isFinite(x)))throw Error('Enter valid comma-separated returns.');showQuant('#trade-result',await api('quant/trades',{returns:values}));});});
$('#quant-option').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{const v=fields(event.target);['spot','strike','years','volatility','rate'].forEach(k=>v[k]=Number(v[k]));showQuant('#option-result',await api('quant/option',v));});});
$('#market-form').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{const v=fields(event.target);if(v.market!=='crypto'){showQuant('#market-result',{message:'This provider needs server-side credentials and a provider-specific instrument selector. Use the API directly once configured.',provider:v.market});return;}const params=new URLSearchParams({symbol:v.symbol.toUpperCase(),interval:v.interval,limit:v.limit});const result=await api('markets/crypto/candles?'+params);showQuant('#market-result',{provider:result.provider,symbol:result.symbol,bars:result.candles.length,first:result.candles[0],last:result.candles.at(-1)});});});
