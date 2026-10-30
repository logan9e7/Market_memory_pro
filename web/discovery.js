/* Compact, market-aware discovery. Quotes never write journal evidence implicitly. */
(() => {
  let asset=null;
  let captureQuote=null,captureKey='',captureEpoch=0,captureBusy=false,captureTimer=null;
  let market='crypto',watch=[],owner=null,busy=false,version=0,socket=null,streamKey='',lastTick=0;
  const selected={crypto:['BTCUSDT','ETHUSDT','SOLUSDT'],india:[],us:['AAPL','MSFT','NVDA'],fo:[]};
  const quotes=new Map(),names=new Map();
  const labels={crypto:'Crypto spot',india:'Indian stocks',us:'US stocks',fo:'Indian F&O'};
  const status=m=>{const node=$('#discovery-status');node.textContent=m;node.closest('.feed-status').dataset.tone=/unavailable|need.*connection|expired|invalid|failed|no usable/i.test(m)?'warning':/^● Streaming/.test(m)?'live':/loading|refreshing|searching|connecting/i.test(m)?'loading':/paused/i.test(m)?'paused':'ready';};
  const id=(m,s)=>m==='crypto'?s:m.toUpperCase()+':'+s;
  const currentWatch=()=>watch.filter(s=>market==='crypto'?!s.includes(':'):s.startsWith(market.toUpperCase()+':')).map(s=>market==='crypto'?s:s.slice(s.indexOf(':')+1));
  function panel(key){$('.discovery-search-panel').hidden=!['markets','watchlist'].includes(key);$('#discovery-tool-select').value=['capture','journal','alerts'].includes(key)?key:'';document.querySelectorAll('[data-discovery-panel]').forEach(p=>p.hidden=p.dataset.discoveryPanel!==key);document.querySelectorAll('[data-discovery-tab]').forEach(b=>{const active=b.dataset.discoveryTab===key;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});}
  document.querySelectorAll('[data-discovery-tab]').forEach(b=>{
    b.addEventListener('click',()=>panel(b.dataset.discoveryTab));
    b.addEventListener('keydown',event=>{const tabs=[...document.querySelectorAll('[data-discovery-tab]')];let i=tabs.indexOf(b);if(event.key==='ArrowRight')i=(i+1)%tabs.length;else if(event.key==='ArrowLeft')i=(i+tabs.length-1)%tabs.length;else if(event.key==='Home')i=0;else if(event.key==='End')i=tabs.length-1;else return;event.preventDefault();tabs[i].click();tabs[i].focus();});
  });
  function stop(){if(socket){socket.onclose=null;socket.close();socket=null;}streamKey='';lastTick=0;}
  const visible=()=>signedIn && activeTab==='discovery' && !document.hidden;
  function stream(){
    if(!visible() || market!=='crypto' || !$('#discovery-auto').checked){stop();return;}
    const symbols=[...new Set([...selected.crypto,...currentWatch()])].sort(),key=symbols.join(',');
    if(!symbols.length || (streamKey===key && socket && socket.readyState<2))return;
    stop();streamKey=key;const ws=new WebSocket('wss://data-stream.binance.vision/stream?streams='+symbols.map(s=>s.toLowerCase()+'@miniTicker').join('/'));socket=ws;
    ws.onmessage=event=>{if(socket!==ws || !visible())return;try{const q=JSON.parse(event.data).data;if(q.e!=='24hrMiniTicker'||!symbols.includes(q.s))return;const price=Number(q.c),open=Number(q.o);if(![price,open,Number(q.E),Number(q.h),Number(q.l),Number(q.v)].every(Number.isFinite)||price<=0||open<=0)return;quotes.set(id('crypto',q.s),{symbol:q.s,price,change_percent:(price/open-1)*100,high:Number(q.h),low:Number(q.l),volume:Number(q.v),as_of:new Date(q.E).toISOString(),currency:currency(q.s),provider:'Binance spot',period:'24h'});lastTick=Date.now();render();status('● Streaming · Binance · '+new Date(q.E).toLocaleTimeString());if(captureKey===id('crypto',q.s)){captureQuote=quotes.get(captureKey);renderCapture();}}catch(_){} };
    ws.onclose=()=>{if(socket===ws){socket=null;streamKey='';}};
    // REST remains available if the user's network blocks exchange WebSockets.
    ws.onerror=()=>{};
  }
  function currency(s){return ['USDT','USDC','USD','EUR','BTC','ETH','BNB'].find(q=>s.endsWith(q))||'';}
  const fmt=v=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:8});
  function card(symbol){
    const key=id(market,symbol),q=quotes.get(key),saved=watch.includes(key),asof=q?.as_of,old=asof&&Date.now()-Date.parse(asof)>90000;
    const change=q?.change_percent,code=market==='crypto'?symbol.replace(/(USDT|USDC|USD|EUR)$/,''):q?.symbol||names.get(key)||symbol;
    const title=market==='crypto'?({BTC:'Bitcoin',ETH:'Ethereum',SOL:'Solana',RAY:'Raydium'}[code]||code):code;
    const provider=q?.provider||labels[market];
    const time=asof?new Date(asof).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
    return `<article class="asset-row${saved?' is-watched':''}" data-quote-state="${q?(old?'old':'available'):'pending'}"><button type="button" class="asset-open" data-open-asset="${e(symbol)}" aria-label="Open ${e(title)} actions"><span class="asset-monogram" aria-hidden="true">${e(code.slice(0,3))}</span><span class="asset-identity"><strong>${e(title)}</strong><small>${e(symbol)} <span class="asset-provider">· ${e(provider)}</span></small></span></button><button type="button" class="quote-open" data-open-asset="${e(symbol)}" aria-label="View ${e(title)} price and actions"><strong>${q?e(fmt(q.price)):'—'} <span>${e(q?.currency||'')}</span></strong><small>${q?e((q.timestamp_kind==='retrieved'?'Retrieved ':old?'Last quote ':'')+time):'Awaiting quote'}</small></button><div class="asset-change ${change==null?'':change<0?'price-down':'price-up'}">${change==null?'—':(change>0?'+':'')+e(Number(change).toFixed(2))+'%'}<small>${q?e(q.period||'session'):''}</small></div><button type="button" class="watch-control${saved?' saved':''}" data-watch="${e(symbol)}" data-saved="${saved}" aria-label="${saved?'Remove':'Add'} ${e(title)} ${saved?'from':'to'} watchlist" aria-pressed="${saved}">${saved?'★':'☆'}</button><button type="button" class="asset-more" data-open-asset="${e(symbol)}" aria-label="Capture or set alert for ${e(title)}">›</button></article>`;
  }
  function render(){
    const focused=document.activeElement,focusRoot=focused?.closest('#discovery-results,#discovery-watchlist')?.id;
    const focusSymbol=focused?.dataset.openAsset||focused?.dataset.watch,focusClass=focused?.className;
    if(asset && !asset.manual && $('#asset-dialog').open)renderAsset();
    $('#discovery-results').innerHTML=selected[market].length?selected[market].map(card).join(''):'<div class="discovery-empty"><span aria-hidden="true">⌕</span><h3>Start with an asset.</h3><p>Search a stock or choose an exact F&O contract.<br>Your next observation starts here.</p></div>';
    $('#discovery-watchlist').innerHTML=currentWatch().length?currentWatch().map(card).join(''):'<div class="discovery-empty"><span aria-hidden="true">☆</span><h3>A little focus goes a long way.</h3><p>Tap the star beside an asset to keep it here.<br>Your watchlist stays private.</p><button type="button" class="secondary" id="watchlist-explore">Explore assets</button></div>';
    $('#discovery-watch-count').textContent=currentWatch().length;
    if(focusRoot&&focusSymbol){const next=[...document.getElementById(focusRoot).querySelectorAll('button')].find(b=>(b.dataset.openAsset||b.dataset.watch)===focusSymbol&&b.className===focusClass);next?.focus({preventScroll:true});}
  }
  async function load(){
    if(busy || !visible())return;
    busy=true;$('#discovery-refresh').disabled=true;const epoch=version,m=market;
    try{
      if(owner!==state.username){stop();quotes.clear();watch=[];owner=state.username;}
      const w=await api('discovery/watchlist');if(epoch!==version||!visible())return;watch=w.symbols;
      stream();render();const symbols=[...new Set([...selected[m],...currentWatch()])];
      if(!symbols.length){status(m==='fo'?'Search an underlying, then choose the exact expiry, strike and contract.':'Search a stock to load its price.');return;}
      status('Loading '+labels[m].toLowerCase()+'…');let errors=[];let providers=new Set();
      for(let i=0;i<symbols.length;i+=20){const params=new URLSearchParams({symbols:symbols.slice(i,i+20).join(',')});if(m!=='crypto')params.set('market',m);const data=await api('discovery/'+(m==='crypto'?'prices?':'quotes?')+params);if(epoch!==version||!visible())return;data.quotes.forEach(q=>{const s=q.instrument_key||q.symbol;quotes.set(id(m,s),q);names.set(id(m,s),q.symbol);});errors.push(...(data.errors||[]));providers.add(data.provider);}
      render();if(Date.now()-lastTick>10000)status([...providers].join(' / ')+' · Latest available quotes · '+new Date().toLocaleTimeString()+(errors.length?' · '+errors.map(x=>x.symbol+': '+x.message).join('; '):''));
    }catch(err){if(epoch===version){render();if(Date.now()-lastTick>10000)status(err.message);}}
    finally{busy=false;$('#discovery-refresh').disabled=false;if(epoch!==version)void load();}
  }
  async function chooseMarket(){market=$('#discovery-market').value;version++;stop();$('#discovery-contract-controls').hidden=market!=='fo';$('#discovery-instruments').replaceChildren();$('#discovery-search').elements.symbol.value='';$('#discovery-search').elements.symbol.placeholder={crypto:'RAY, BTC, ETH or BTCUSDT',india:'RELIANCE, TCS, HDFC',us:'AAPL, MSFT, NVDA',fo:'NIFTY, BANKNIFTY, RELIANCE'}[market];render();status('Loading '+labels[market]+'…');void load();}
  $('#discovery-market').addEventListener('change',chooseMarket);
  $('#discovery-search').addEventListener('submit',event=>{event.preventDefault();submit(event.target,async()=>{
    panel('markets');const raw=event.target.elements.symbol.value.trim().toUpperCase(),epoch=version;
    if(market==='crypto'){const alias={BITCOIN:'BTC',ETHEREUM:'ETH',SOLANA:'SOL',RAYDIUM:'RAY'},s=alias[raw]||raw;selected.crypto=[s.length>3&&['USDT','USDC','USD','EUR','BTC','ETH','BNB'].some(q=>s.endsWith(q)&&s.length>q.length)?s:s+'USDT'];void load();return;}
    if(market==='us'){if(!/^[A-Z][A-Z.-]{0,11}$/.test(raw))throw Error('Enter a US stock ticker such as AAPL.');selected.us=[raw];void load();return;}
    const params=new URLSearchParams({q:raw,market,kind:$('#discovery-kind').value,expiry:$('#discovery-expiry').value});status('Searching exchange instruments…');
    try{const data=await api('discovery/search?'+params);if(epoch!==version)return;$('#discovery-instruments').innerHTML=data.instruments.length?data.instruments.map(r=>{names.set(id(market,r.instrument_key),r.symbol);return `<button type="button" class="secondary instrument-choice" data-instrument="${e(r.instrument_key)}"><strong>${e(r.symbol)}</strong><span>${e(r.exchange)} · ${e(r.kind)}${r.expiry?' · Expiry '+e(typeof r.expiry==='number'?new Date(r.expiry).toLocaleDateString():r.expiry):''}${r.strike?' · Strike '+e(r.strike):''} · Lot ${e(r.lot_size??'—')}</span></button>`;}).join(''):'<p>No matching instruments. Try a different underlying or expiry.</p>';status('Select an instrument to view its price.');}catch(err){status(err.message);}
  });});
  $('#discovery-instruments').addEventListener('click',event=>{const b=event.target.closest('[data-instrument]');if(!b)return;selected[market]=[b.dataset.instrument];$('#discovery-instruments').replaceChildren();void load();});
  $('#discovery-refresh').addEventListener('click',()=>void load());
  $('[data-view="discovery"]').addEventListener('click',async event=>{if(event.target.closest('#watchlist-explore')){panel('markets');$('#discovery-search').elements.symbol.focus();return;}const b=event.target.closest('[data-watch],[data-research],[data-open-asset]');if(!b)return;const symbol=b.dataset.watch||b.dataset.research||b.dataset.openAsset;
    if(b.dataset.openAsset){openAsset(symbol);return;}
    if(b.dataset.research){$('#capture-market').value=market;const q=quotes.get(id(market,symbol));['quote-form','snapshot-form','decision-form','alert-form'].forEach(key=>{const form=$('#'+key);form.elements.symbol.value=(q?.instrument_key||q?.symbol||names.get(id(market,symbol))||symbol).slice(0,32);if(form.elements.currency&&q?.currency){const option=[...form.elements.currency.options].find(o=>o.value===q.currency);if(option)form.elements.currency.value=q.currency;}});panel('capture');void loadCapture();$('#quote-form').elements.price.focus();notice('Asset selected. Confirm the observed price and currency before saving.');return;}
    b.disabled=true;try{if(b.dataset.saved==='true')await api('discovery/watchlist/'+encodeURIComponent(id(market,symbol)),null,{method:'DELETE'});else await api('discovery/watchlist',{symbol,market});watch=(await api('discovery/watchlist')).symbols;render();stream();}catch(err){notice(err.message,true);}finally{b.disabled=false;}
  });
  function renderAsset(){
    if(!asset||asset.manual)return;
    const key=id(asset.market,asset.symbol),q=quotes.get(key);
    $('#asset-title').textContent=q?.symbol||names.get(key)||asset.symbol;
    $('#asset-market').textContent=labels[asset.market];
    $('#asset-price').textContent=q?(q.currency+' '+fmt(q.price)):'Quote unavailable';
    const old=q?.as_of&&Date.now()-Date.parse(q.as_of)>90000;
    $('#asset-meta').textContent=q?(q.provider+' · '+(old?'Last available quote · ':'')+(q.timestamp_kind==='retrieved'?'Retrieved ':'As of ')+(q.as_of?date(q.as_of):'unknown time')):'A quote is needed for asset capture. Manual capture is available separately.';
    $('#asset-stats').hidden=false;$('#asset-stats').innerHTML=[['Range',fmt(q?.low)+' – '+fmt(q?.high)],['Volume',fmt(q?.volume)],['Change',q?.change_percent==null?'—':Number(q.change_percent).toFixed(2)+'%']].map(([label,value])=>'<div><small>'+e(label)+'</small><strong>'+e(value)+'</strong></div>').join('');$('#asset-capture').disabled=!q;
    $('#asset-watch').textContent=watch.includes(key)?'Remove from watchlist':'☆ Add to watchlist';
  }
  function openAsset(symbol){
    asset={market,symbol,manual:false};
    $('#asset-choices').hidden=false;$('#asset-capture-form').hidden=true;$('#asset-feedback').textContent='';renderAsset();$('#asset-dialog').showModal();
  }
  function prepareCapture(manual){
    const form=$('#asset-capture-form');form.reset();
    const q=manual?null:quotes.get(id(asset.market,asset.symbol));
    if(!manual&&!q)return;
    if(manual){$('#asset-stats').hidden=true;asset={manual:true,market,symbol:''};$('#asset-market').textContent='MANUAL CAPTURE';$('#asset-title').textContent='Keep a market moment';$('#asset-price').textContent='';$('#asset-meta').textContent='Enter your observed price and a note. No live feed is required.';}
    $('#asset-choices').hidden=true;form.hidden=false;
    form.elements.symbol.readOnly=!manual;form.elements.currency.disabled=!manual;form.elements.price.readOnly=!manual;
    form.elements.symbol.value=q?.instrument_key||q?.symbol||'';form.elements.currency.value=q?.currency||(market==='crypto'?'USDT':market==='us'?'USD':'INR');form.elements.price.value=q?.price||'';
    asset.quote=q?{...q}:null;
    $('#asset-capture-note').textContent=q?'The displayed price is fixed for this capture. Its provider and quote time will be saved with your note.':'Manual entries are saved as your own observations.';
    $('#asset-feedback').textContent='';
    if(!$('#asset-dialog').open)$('#asset-dialog').showModal();
    (manual?form.elements.symbol:form.elements.note).focus();
  }
  $('#asset-close').addEventListener('click',()=>$('#asset-dialog').close());
  $('#asset-capture-cancel').addEventListener('click',()=>$('#asset-dialog').close());
  $('#asset-dialog').addEventListener('close',()=>{asset=null;});
  $('#discovery-manual-capture').addEventListener('click',()=>prepareCapture(true));
  $('#asset-capture').addEventListener('click',()=>prepareCapture(false));
  $('#asset-alert').addEventListener('click',()=>{
    if(!asset)return;const q=quotes.get(id(asset.market,asset.symbol)),form=$('#alert-form');
    form.elements.symbol.value=q?.instrument_key||q?.symbol||asset.symbol;form.elements.currency.value=q?.currency||(asset.market==='us'?'USD':asset.market==='crypto'?'USDT':'INR');form.elements.target.value=q?.price||'';
    $('#asset-dialog').close();panel('alerts');form.elements.target.focus();notice('Asset selected. Choose your target and save the alert.');
  });
  $('#asset-watch').addEventListener('click',async event=>{
    if(!asset)return;const a={...asset},button=event.currentTarget;button.disabled=true;
    try{const key=id(a.market,a.symbol);if(watch.includes(key))await api('discovery/watchlist/'+encodeURIComponent(key),null,{method:'DELETE'});else await api('discovery/watchlist',{market:a.market,symbol:a.symbol});watch=(await api('discovery/watchlist')).symbols;render();stream();$('#asset-feedback').textContent=watch.includes(key)?'Added to your watchlist.':'Removed from your watchlist.';}
    catch(err){$('#asset-feedback').textContent=err.message;}finally{button.disabled=false;}
  });
  $('#asset-capture-form').addEventListener('submit',event=>{
    event.preventDefault();const form=event.target;submit(form,async()=>{
      const data=fields(form),q=asset?.quote;data.price=Number(data.price);
      if(q){data.symbol=q.instrument_key||q.symbol;data.currency=q.currency;data.price=q.price;const provenance='Observed from '+q.provider+' · '+(q.timestamp_kind==='retrieved'?'retrieved ':'quote time ')+(q.as_of||'unknown')+'.';data.note=provenance+'\n'+data.note;if(data.note.length>5000)throw Error('Shorten your note to leave room for the quote details.');}
      try{await api('captures',data);}catch(err){$('#asset-feedback').textContent=err.message;throw err;}
      $('#asset-dialog').close();await refresh();notice('Capture saved to Memory.');
    });
  });
  function renderCapture(){
    const q=captureQuote,button=$('#capture-use-price');
    if(!q){button.disabled=true;return;}
    const old=!q.as_of||Date.now()-Date.parse(q.as_of)>90000;
    $('#capture-live-price').textContent=(q.currency||'')+' '+fmt(q.price);
    $('#capture-live-meta').textContent=q.provider+' · '+(q.timestamp_kind==='retrieved'?'Retrieved ':old?'Last trade (closed market or old quote) ':'As of ')+(q.as_of?date(q.as_of):'unknown time');
    button.disabled=old;
  }
  async function loadCapture(){
    const form=$('#quote-form'),raw=form.elements.symbol.value.trim().toUpperCase(),m=$('#capture-market').value;
    if(!raw||!visible()||$('#discovery-panel-capture').hidden){if(!raw){captureQuote=null;$('#capture-live-price').textContent='Enter an asset above';$('#capture-live-meta').textContent='Select a market and symbol to load its latest quote.';$('#capture-use-price').disabled=true;}return;}
    if(captureBusy)return;
    captureBusy=true;const epoch=captureEpoch;
    $('#capture-live-refresh').disabled=true;
    try{
      let symbol=raw;
      if(m==='crypto'){const aliases={BITCOIN:'BTC',ETHEREUM:'ETH',SOLANA:'SOL',RAYDIUM:'RAY'},base=aliases[raw]||raw;symbol=['USDT','USDC','USD','EUR','BTC','ETH','BNB'].some(q=>base.endsWith(q)&&base.length>q.length)?base:base+'USDT';}
      if(m==='india'||m==='fo'){
        if(!/^(NSE|BSE)_(EQ|FO)\|/.test(raw)){
          const data=await api('discovery/search?'+new URLSearchParams({market:m,q:raw.replace(/\.NS$/,''),kind:$('#discovery-kind').value,expiry:$('#discovery-expiry').value}));
          const exact=data.instruments.filter(r=>r.symbol.toUpperCase()===raw.replace(/\.NS$/,''));
          if(exact.length!==1)throw Error('Choose the exact stock or contract in Live prices, then select Capture idea.');
          symbol=exact[0].instrument_key;
        }
      }
      const params=new URLSearchParams({symbols:symbol});if(m!=='crypto')params.set('market',m);
      const data=await api('discovery/'+(m==='crypto'?'prices?':'quotes?')+params);
      if(epoch!==captureEpoch||!visible())return;
      const q=data.quotes.find(q=>(q.instrument_key||q.symbol)===symbol);
      if(!q)throw Error(data.errors?.[0]?.message||'No quote returned for this asset.');
      captureKey=id(m,symbol);captureQuote=q;renderCapture();
    }catch(err){if(epoch===captureEpoch){captureQuote=null;$('#capture-live-price').textContent='Quote unavailable';$('#capture-live-meta').textContent=err.message;$('#capture-use-price').disabled=true;}}
    finally{captureBusy=false;$('#capture-live-refresh').disabled=false;if(epoch!==captureEpoch)void loadCapture();}
  }
  function captureChanged(){captureEpoch++;captureQuote=null;captureKey='';$('#capture-use-price').disabled=true;$('#capture-live-price').textContent='Loading latest quote…';clearTimeout(captureTimer);captureTimer=setTimeout(()=>void loadCapture(),500);}
  $('#quote-form').elements.symbol.addEventListener('input',captureChanged);
  $('#capture-market').addEventListener('change',captureChanged);
  $('#capture-live-refresh').addEventListener('click',()=>void loadCapture());
  $('#capture-use-price').addEventListener('click',()=>{renderCapture();if(!captureQuote||$('#capture-use-price').disabled)return;const f=$('#quote-form');f.elements.price.value=captureQuote.price;f.elements.currency.value=captureQuote.currency;f.elements.symbol.value=captureQuote.instrument_key||captureQuote.symbol;notice('Latest price filled. Save when you are ready to record it.');});
  $('#discovery-tool-select').addEventListener('change',event=>{if(!event.target.value)return;panel(event.target.value);if(event.target.value==='capture')void loadCapture();});
  setInterval(()=>{renderCapture();if($('#discovery-auto').checked)void loadCapture();},15000);
  window.addEventListener('desk-tab' ,()=>{if(!visible()){version++;if($('#asset-dialog').open)$('#asset-dialog').close();}stream();void load();});
  document.addEventListener('visibilitychange',()=>{stream();if(!document.hidden)void load();});
  $('#discovery-auto').addEventListener('change',()=>{stream();status($('#discovery-auto').checked?'Refreshing…':'Paused · last prices retain their timestamps.');if($('#discovery-auto').checked)void load();});
  setInterval(()=>{stream();if($('#discovery-auto').checked&&Date.now()-lastTick>10000)void load();},15000);
})();
