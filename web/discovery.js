/* Discovery owns its feed lifecycle; market observations remain explicit writes. */
(() => {
  let watch = [], search = ['BTCUSDT','ETHUSDT','SOLUSDT'], quotes = new Map(), busy = false, owner = null;
  const status = message => { $('#discovery-status').textContent = message; };
  function card(symbol, saved) {
    const q = quotes.get(symbol);
    const stale = q && Date.now() - Date.parse(q.as_of) > 90000;
    return `<div class="item discovery-card"><div class="eyebrow">BINANCE SPOT · ${e(symbol.endsWith('USDT')?'USDT':symbol)}</div><h3>${e(symbol)}</h3>${q ? `<strong class="discovery-price">${e(Number(q.price).toLocaleString(undefined,{maximumFractionDigits:8}))}</strong><p class="${q.change_percent < 0 ? 'price-down':'price-up'}">${q.change_percent > 0 ? '+':''}${e(q.change_percent)}% <span class="meta">/ 24h</span></p><div class="meta">24h range ${e(q.low)} – ${e(q.high)}<br>Volume ${e(q.volume)} base units<br>${stale?'Stale · ':''}As of ${e(date(q.as_of))}</div>` : '<p>Price unavailable</p>'}<div class="actions"><button type="button" data-watch="${e(symbol)}" data-saved="${saved}">${saved?'Remove':'☆ Watch'}</button><button type="button" class="secondary" data-research="${e(symbol)}">Capture idea</button></div></div>`;
  }
  function render() {
    $('#discovery-results').innerHTML = search.map(s=>card(s,watch.includes(s))).join('');
    $('#discovery-watchlist').innerHTML = watch.length ? watch.map(s=>card(s,true)).join('') : '<p class="empty">Search for a pair and select ☆ Watch to start your list.</p>';
  }
  async function load() {
    if (busy || !signedIn || activeTab !== 'discovery' || document.hidden) return;
    busy = true;
    $('#discovery-refresh').disabled = true;
    try {
      if(owner !== state.username) { quotes.clear(); watch=[]; owner=state.username; }
      watch = (await api('discovery/watchlist')).symbols;
      render();
      const symbols = [...new Set([...search,...watch])];
      status('Refreshing market prices…');
      // Keep each request within the server batch limit.
      for(let i=0;i<symbols.length;i+=20) {
        const data = await api('discovery/prices?'+new URLSearchParams({symbols:symbols.slice(i,i+20).join(',')}));
        if(!signedIn || owner!==state.username) return;
        data.quotes.forEach(q=>quotes.set(q.symbol,q));
      }
      render(); status('Binance spot · Updated '+new Date().toLocaleTimeString()+'. Auto-refresh runs only while Discovery is visible.');
    } catch(err) { render(); status(err.message+' Any retained prices show their original timestamp.'); }
    finally { busy=false; $('#discovery-refresh').disabled=false; }
  }
  $('#discovery-search').addEventListener('submit',event=>{event.preventDefault();search=[event.target.elements.symbol.value.trim().toUpperCase()];void load();});
  $('#discovery-refresh').addEventListener('click',()=>void load());
  $('[data-view="discovery"]').addEventListener('click',async event=>{
    const b=event.target.closest('button[data-watch],button[data-research]'); if(!b)return;
    if(b.dataset.research) {
      ['quote-form','snapshot-form','decision-form','alert-form'].forEach(id=>{$('#'+id).elements.symbol.value=b.dataset.research;});
      $('#quote-form').scrollIntoView({behavior:'smooth',block:'center'});
      $('#quote-form').elements.price.focus(); notice('Symbol selected. Enter your observed price and currency to preserve your evidence.'); return;
    }
    b.disabled=true;
    try {
      const symbol=b.dataset.watch;
      if(b.dataset.saved==='true') await api('discovery/watchlist/'+encodeURIComponent(symbol),null,{method:'DELETE'});
      else await api('discovery/watchlist',{symbol});
      watch=(await api('discovery/watchlist')).symbols;render();
    } catch(err) { notice(err.message,true); } finally { b.disabled=false; }
  });
  window.addEventListener('desk-tab',()=>void load());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void load();});
  setInterval(()=>{if($('#discovery-auto').checked)void load();else render();},30000);
})();
