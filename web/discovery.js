/* Discovery owns its feed lifecycle; market observations remain explicit writes. */
(() => {
  let watch = [], search = ['BTCUSDT','ETHUSDT','SOLUSDT'], quotes = new Map(), busy = false, owner = null, socket = null, streamKey = '', lastTick = 0;
  const status = message => { $('#discovery-status').textContent = message; };
  function selectPanel(key) {
    document.querySelectorAll('[data-discovery-panel]').forEach(p=>p.hidden=p.dataset.discoveryPanel!==key);
    document.querySelectorAll('[data-discovery-tab]').forEach(b=>{const active=b.dataset.discoveryTab===key;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
  }
  document.querySelectorAll('[data-discovery-tab]').forEach(b=>{
    b.addEventListener('click',()=>selectPanel(b.dataset.discoveryTab));
    b.addEventListener('keydown',event=>{
      const tabs=[...document.querySelectorAll('[data-discovery-tab]')];let i=tabs.indexOf(b);
      if(event.key==='ArrowRight')i=(i+1)%tabs.length;else if(event.key==='ArrowLeft')i=(i+tabs.length-1)%tabs.length;else if(event.key==='Home')i=0;else if(event.key==='End')i=tabs.length-1;else return;
      event.preventDefault();tabs[i].click();tabs[i].focus();
    });
  });
  function stopStream() { if(socket){socket.onclose=null;socket.close();socket=null;} streamKey='';lastTick=0; }
  function connectStream() {
    if(!signedIn || activeTab!=='discovery' || document.hidden || !$('#discovery-auto').checked){stopStream();return;}
    const symbols=[...new Set([...search,...watch])].sort();const key=symbols.join(',');
    if(streamKey===key && socket && socket.readyState<2)return;
    stopStream();streamKey=key;
    socket=new WebSocket('wss://data-stream.binance.vision/stream?streams='+symbols.map(s=>s.toLowerCase()+'@miniTicker').join('/'));
    const current=socket;
    socket.onmessage=event=>{
      if(socket!==current || !signedIn)return;
      try {
        const q=JSON.parse(event.data).data;
        if(!symbols.includes(q.s) || q.e!=='24hrMiniTicker')return;
        const price=Number(q.c),open=Number(q.o),asOf=Number(q.E);
        if(![price,open,asOf,Number(q.h),Number(q.l),Number(q.v)].every(Number.isFinite)||price<=0||open<=0)return;
        quotes.set(q.s,{symbol:q.s,price,change_percent:Math.round((price/open-1)*10000)/100,high:Number(q.h),low:Number(q.l),volume:Number(q.v),as_of:new Date(asOf).toISOString()});
        lastTick=Date.now();render();status('● Live · Binance spot · '+new Date(asOf).toLocaleTimeString());
      } catch(_) { /* Ignore malformed events; keep timestamped evidence. */ }
    };
    socket.onerror=()=>{if(socket===current && !lastTick)status('Stream unavailable. Retrying prices every 5 seconds.');};
    socket.onclose=()=>{if(socket===current){socket=null;streamKey='';status('Stream disconnected. Reconnecting; prices keep their timestamps.');}};
  }
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
      try { watch = (await api('discovery/watchlist')).symbols; } catch(err) { notice('Watchlist: '+err.message,true); }
      connectStream();
      render();
      const symbols = [...new Set([...search,...watch])];
      status('Refreshing market prices…');
      // Keep each request within the server batch limit.
      for(let i=0;i<symbols.length;i+=20) {
        const data = await api('discovery/prices?'+new URLSearchParams({symbols:symbols.slice(i,i+20).join(',')}));
        if(!signedIn || owner!==state.username) return;
        data.quotes.forEach(q=>quotes.set(q.symbol,q));
      }
      render(); if(Date.now()-lastTick>10000) status('Latest prices · Binance spot · '+new Date().toLocaleTimeString()+' · Connecting live feed…');
    } catch(err) { render(); if(Date.now()-lastTick>10000) status(err.message+' Connecting live stream; retained prices keep their timestamps.'); }
    finally { busy=false; $('#discovery-refresh').disabled=false; }
  }
  $('#discovery-search').addEventListener('submit',event=>{event.preventDefault();const raw=event.target.elements.symbol.value.trim().toUpperCase(); const aliases={BITCOIN:'BTCUSDT',BTC:'BTCUSDT',ETHEREUM:'ETHUSDT',ETH:'ETHUSDT',SOLANA:'SOLUSDT',SOL:'SOLUSDT'}; search=[aliases[raw]||raw];void load();});
  $('#discovery-refresh').addEventListener('click',()=>void load());
  $('[data-view="discovery"]').addEventListener('click',async event=>{
    const b=event.target.closest('button[data-watch],button[data-research]'); if(!b)return;
    if(b.dataset.research) {
      ['quote-form','snapshot-form','decision-form','alert-form'].forEach(id=>{$('#'+id).elements.symbol.value=b.dataset.research;});
      selectPanel('capture');
      $('#quote-form').scrollIntoView({behavior:'smooth',block:'center'});
      $('#quote-form').elements.price.focus(); notice('Symbol selected. Enter your observed price and currency to preserve your evidence.'); return;
    }
    b.disabled=true;
    try {
      const symbol=b.dataset.watch;
      if(b.dataset.saved==='true') await api('discovery/watchlist/'+encodeURIComponent(symbol),null,{method:'DELETE'});
      else await api('discovery/watchlist',{symbol});
      watch=(await api('discovery/watchlist')).symbols;render();connectStream();
    } catch(err) { notice(err.message,true); } finally { b.disabled=false; }
  });
  window.addEventListener('desk-tab',()=>{connectStream();void load();});
  document.addEventListener('visibilitychange',()=>{connectStream();if(!document.hidden)void load();});
  $('#discovery-auto').addEventListener('change',()=>{connectStream();status($('#discovery-auto').checked?'Connecting live feed…':'Paused · prices show their last update time.');});
  setInterval(()=>{connectStream();if($('#discovery-auto').checked && Date.now()-lastTick>10000)void load();render();},5000);
})();
