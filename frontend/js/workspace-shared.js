const UI = {
  escape:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  text:(id,s)=>{const n=document.getElementById(id);if(n)n.textContent=s;},
  pair:()=>{const s=PharmaStore.getState();return s.selectedPair.map(id=>s.medicines.find(m=>m.id===id)).filter(Boolean);},
  go:page=>{location.href=page+'.html';},
  t:(key,variables)=>window.PharmaPreferences?PharmaPreferences.t(key,variables):key,
  announce:s=>{document.getElementById('statusMessage').textContent=s;},
  matrix(regimen,interactive=false){
    const {medicines}=regimen;const e=UI.escape;
    if(medicines.length<2)return '<caption>Add at least two medicines to compare interactions.</caption>';
    return '<caption class="sr-only">Synthetic pairwise interaction scores. Unknown does not mean safe.</caption><thead><tr><th scope="col">Drug</th>'+medicines.map((m,i)=>'<th scope="col" title="'+e(m.name)+'">'+String.fromCharCode(65+i)+'</th>').join('')+'</tr></thead><tbody>'+medicines.map((a,i)=>'<tr><th scope="row" title="'+e(a.name)+'">'+String.fromCharCode(65+i)+'</th>'+medicines.map(b=>{if(a.id===b.id)return '<td class="cell-diagonal">—</td>';const score=PharmaStore.score(a.id,b.id,regimen),kind=PharmaDemo.classifyScore(score),label=e(a.name+' + '+b.name+': '+(score??'unknown')+'; '+kind);return '<td class="cell-'+kind+'">'+(interactive?'<button type="button" data-a="'+e(a.id)+'" data-b="'+e(b.id)+'" aria-label="'+label+'">'+(score??'?')+'</button>':'<span aria-label="'+label+'">'+(score??'?')+'</span>')+'</td>';}).join('')+'</tr>').join('')+'</tbody>';
  },
  key:meds=>meds.map((m,i)=>String.fromCharCode(65+i)+' '+m.name).join(' · '),
  modal(title,html){const d=document.getElementById('demoDialog');d.innerHTML='<form method="dialog"><button class="dialog-close" aria-label="Close dialog">×</button></form><h2 id="dialogTitle">'+UI.escape(title)+'</h2>'+html;d.showModal();return d;}
};
function renderWorkspaceShell(active){
  window.PharmaPreferences?.apply(document);
  const routes=[['▦','Regimen overview','workspace','nav.regimen'],['◎','Demographic lens','demographic-lens','nav.demographic'],['⌘','Pathway inspector','pathway-inspector','nav.pathway'],['⇄','Substitution engine','substitution-engine','nav.substitution'],['☰','Review & export','regimen-simulation','nav.review'],['◫','Patients','patients','Patients'],['▤','Reports','reports','Reports'],['⇆','Care transfers','transfers','Care transfers']];
  document.getElementById('sidebarNav').innerHTML=routes.map(([icon,label,page,key])=>'<a class="sidebar-nav-item '+(active===label?'active':'')+'" '+(active===label?'aria-current="page"':'')+' href="'+page+'.html"><span aria-hidden="true" class="sidebar-nav-icon">'+icon+'</span>'+UI.t(key)+'</a>').join('');
  const user=PharmaStore.getUser();UI.text('userAvatar',user.initials);document.getElementById('userAvatar').title=user.name+' · '+user.role;
  document.querySelector('.workspace-topbar').insertAdjacentHTML('afterbegin','<a class="case-breadcrumb" href="workspace.html">'+UI.t('shell.workspace')+'</a><span class="pill pill-muted">'+UI.t('shell.synthetic')+'</span>');
  const brand=document.querySelector('.workspace-sidebar .brand');brand.outerHTML='<a class="brand" href="../index.html" aria-label="PharmaGNN home">'+brand.innerHTML+'</a>';
  document.querySelector('.sidebar-callout-title').textContent='A clearer picture.';document.querySelector('.sidebar-callout-text').textContent='Every pair. Every pathway. One considered decision.';
  UI.text('footerLeft','Research prototype • Synthetic scores • Clinician review required');UI.text('footerRight','Model demo-v0.1');
  document.querySelector('.sidebar-footer-link').insertAdjacentHTML('beforebegin','<button class="reset-demo" id="resetDemo" type="button">'+UI.t('shell.reset')+'</button>');
  document.body.insertAdjacentHTML('beforeend','<p class="status-message" id="statusMessage" role="status" aria-live="polite"></p><dialog id="demoDialog" aria-labelledby="dialogTitle"></dialog>');
  document.getElementById('resetDemo').onclick=()=>{UI.modal(UI.t('shell.resetTitle'),'<p>'+UI.t('shell.resetBody')+'</p><button class="btn btn-primary" id="confirmReset">'+UI.t('shell.confirmReset')+'</button>');document.getElementById('confirmReset').onclick=()=>{PharmaStore.reset();UI.go('workspace');};};
  const quick=document.createElement('a');quick.className='quick-add btn btn-secondary';quick.href='workspace.html#add-medicine';quick.textContent=UI.t('shell.addMedicine');
  const settings=document.createElement('a');settings.className='settings-link';settings.href='settings.html';settings.textContent='⚙ '+UI.t('nav.settings');settings.setAttribute('aria-label',UI.t('nav.settings'));
  const logout=document.createElement('button');logout.className='settings-link';logout.type='button';logout.textContent='Log out';logout.onclick=()=>LogoutFlow.logout(ApiClient,location);const topbar=document.querySelector('.workspace-topbar .topbar-right');topbar.prepend(logout,settings);if(active!=='Regimen overview')topbar.prepend(quick);
  window.PharmaPreferences?.translateDocument(document);
}
