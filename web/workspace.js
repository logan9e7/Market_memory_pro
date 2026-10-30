/* Shared presentation behavior. Data mutations remain in the existing API handlers. */
(() => {
  let memoryLimit=10,captureLimit=10;
  function pane(group,key){
    document.querySelectorAll('[data-pane-group="'+group+'"]').forEach(node=>node.hidden=node.dataset.pane!==key);
    document.querySelectorAll('[data-workspace-group="'+group+'"]').forEach(button=>{const active=button.dataset.workspacePane===key;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
  }
  document.querySelectorAll('[data-workspace-group]').forEach(button=>{
    button.addEventListener('click',()=>pane(button.dataset.workspaceGroup,button.dataset.workspacePane));
    button.addEventListener('keydown',event=>{const tabs=[...document.querySelectorAll('[data-workspace-group="'+button.dataset.workspaceGroup+'"]')];let i=tabs.indexOf(button);if(event.key==='ArrowRight')i=(i+1)%tabs.length;else if(event.key==='ArrowLeft')i=(i+tabs.length-1)%tabs.length;else if(event.key==='Home')i=0;else if(event.key==='End')i=tabs.length-1;else return;event.preventDefault();tabs[i].click();tabs[i].focus();});
  });
  document.addEventListener('click',event=>{
    const opener=event.target.closest('[data-workspace-open]');
    if(opener){const view=opener.dataset.workspaceOpen;setTab(view);if(view==='lab')pane('lab','new');window.scrollTo({top:0,behavior:'smooth'});}
    const switcher=event.target.closest('[data-workspace-switch]');
    if(switcher){const [group,key]=switcher.dataset.workspaceSwitch.split(':');pane(group,key);}
  });
  window.addEventListener('workspace-switch',event=>pane(event.detail.group,event.detail.pane));
  function memory(){
    const query=$('#memory-search').value.trim().toLowerCase(),status=$('#memory-filter').value;
    const rows=[...document.querySelectorAll('#decisions .journal-entry')];
    const matches=rows.filter(row=>(status==='all'||(status==='reviewed'?row.dataset.reviewStatus==='reviewed':row.dataset.reviewStatus==='pending'))&&row.dataset.recordSearch.includes(query));
    rows.forEach(row=>row.hidden=true);matches.slice(0,memoryLimit).forEach(row=>row.hidden=false);
    $('#memory-summary').textContent=rows.length?(matches.length?'Showing '+Math.min(memoryLimit,matches.length)+' of '+matches.length+' matching decisions':'No decisions match this search.'):'No decisions recorded yet.';
    $('#memory-show-more').hidden=matches.length<=memoryLimit;
  }
  function captures(){
    const query=$('#capture-search').value.trim().toLowerCase(),filter=$('#capture-filter').value;
    const rows=[...document.querySelectorAll('#snapshots .capture-entry')];
    const matches=rows.filter(row=>row.dataset.recordSearch.includes(query)&&(filter==='all'||(filter==='manual'?row.dataset.captureKind==='manual':row.dataset.captureKind!=='manual')));
    rows.forEach(row=>row.hidden=true);matches.slice(0,captureLimit).forEach(row=>row.hidden=false);
    $('#capture-summary').textContent=rows.length?'Showing '+Math.min(captureLimit,matches.length)+' of '+matches.length+' matching captures.':'No captures recorded yet.';
    $('#capture-show-more').hidden=matches.length<=captureLimit;
  }
  ['capture-search','capture-filter'].forEach(id=>$('#'+id).addEventListener(id.includes('search')?'input':'change',()=>{captureLimit=10;captures();}));
  $('#capture-show-more').addEventListener('click',()=>{captureLimit+=10;captures();});
  function strategies(){
    const query=$('#strategy-search').value.trim().toLowerCase(),filter=$('#strategy-filter').value;
    const rows=[...document.querySelectorAll('#strategies .strategy-card')];let shown=0;
    rows.forEach(row=>{row.hidden=!(row.dataset.recordSearch.includes(query)&&(filter==='all'||row.dataset.evidenceStatus===filter));if(!row.hidden)shown++;});
    $('#strategy-summary').textContent=rows.length?shown+' of '+rows.length+' strategies shown.':'';
  }
  ['memory-search','memory-filter'].forEach(id=>$('#'+id).addEventListener(id.includes('search')?'input':'change',()=>{memoryLimit=10;memory();}));
  $('#memory-show-more').addEventListener('click',()=>{memoryLimit+=10;memory();});
  ['strategy-search','strategy-filter'].forEach(id=>$('#'+id).addEventListener(id.includes('search')?'input':'change',strategies));
  function sync(){
    memory();captures();strategies();$('#account-name').textContent=state.username||'';
    const waiting=(state.decisions||[]).filter(d=>!d.outcome).length;
    $('#overview-review-title').textContent=waiting?waiting+(waiting===1?' decision needs':' decisions need')+' a review.':'Make room for reflection.';
    $('#overview-review-copy').textContent=waiting?'Close the loop with an outcome and one lesson.':'Capture an observation, then return when the outcome is known.';
  }
  window.addEventListener('workspace-data',sync);
  function authMode(mode){
    const signup=mode==='register',form=$('#auth-form');
    document.querySelectorAll('[data-auth-mode]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.authMode===mode)));
    $('#auth-email-label').hidden=!signup;form.elements.email.required=signup;$('#auth-signup-hint').hidden=!signup;
    form.querySelector('[value="login"]').hidden=signup;form.querySelector('[value="register"]').hidden=!signup;
    form.elements.password.autocomplete=signup?'new-password':'current-password';form.elements.password.minLength=signup?12:8;
    $('#auth-title').textContent=signup?'A place for your next observation.':'Welcome to your desk.';
  }
  document.querySelectorAll('[data-auth-mode]').forEach(button=>button.addEventListener('click',()=>authMode(button.dataset.authMode)));
  window.addEventListener('auth-open',()=>authMode('login'));
  const example=$('#landing-example');example.open=window.matchMedia('(min-width: 901px)').matches;
  sync();authMode('login');
})();
