renderWorkspaceShell('Substitution engine');UI.text('pageHeading','Amitriptyline');UI.text('pageSubhead','Candidate comparison');
UI.text('rankedNote','Ranked by simulated pairwise score ↓');UI.text('candidateBanner','Candidates are hypothetical UI examples. Lower predicted scores do not establish clinical safety or interchangeability.');
const candidates=PharmaStore.getCandidates();let selected=candidates[0];
const e=UI.escape;
document.getElementById('replaceCard').innerHTML='<div class="replace-block"><span class="context-label">REPLACE IN DRAFT</span><span class="replace-drug-name">'+(candidates.length?'Amitriptyline':'No supported alternative fixture')+'</span></div><div class="replace-block"><span class="context-label">THERAPEUTIC INTENT</span><div class="field-box">Depression · demo scenario</div></div><div class="replace-tags"><span class="pill pill-muted">Preserve indication</span><span class="pill pill-muted">Review contraindications</span></div>';
function render(){document.getElementById('candidateList').innerHTML=candidates.map((c,i)=>'<li><button type="button" class="candidate-row '+(c.id===selected.id?'selected':'')+'" data-candidate="'+c.id+'" aria-pressed="'+(c.id===selected.id)+'"><span class="candidate-rank">0'+(i+1)+'</span><span class="candidate-info"><span class="candidate-name">'+e(c.name)+'</span><span class="candidate-subtitle">Hypothetical therapeutic alternative</span><span class="candidate-badge '+(i?'badge-warn':'badge-good')+'">'+e(c.badge)+'</span></span><span class="candidate-score-block"><span class="candidate-score">'+c.score+'</span><span class="candidate-score-max">/ 100</span></span><span class="candidate-delta-block"><span class="candidate-delta">'+(c.score-82)+'</span><span class="candidate-delta-label">points</span></span></button></li>').join('')||'<li class="empty-state">No candidate fixtures for the selected pair. <a href="workspace.html">Return to the regimen</a> to select amitriptyline and citalopram, or reset the demo.</li>';
  const card=document.getElementById('candidateDetailCard');if(!selected){card.innerHTML='<h2>Evidence is needed</h2><p>Alternatives are not invented for unsupported medicines.</p>';return;}const count=PharmaStore.getState().medicines.length;
  card.innerHTML='<h2 class="candidate-detail-name">'+e(selected.name)+'</h2><div class="detail-rows">'+[['Contraindications','Not evaluated'],['Dose equivalence','Requires review'],['Regimen coverage',count*(count-1)/2+' pairwise checks']].map(([a,b])=>'<div class="detail-row"><span class="detail-term">'+a+'</span><span class="detail-value">'+b+'</span></div>').join('')+'</div><button class="btn btn-primary ws-btn-block" id="simulateBtn">Simulate this candidate</button>';document.getElementById('simulateBtn').onclick=()=>{PharmaStore.simulate(selected.id);UI.go('regimen-simulation');};
}
document.getElementById('candidateList').onclick=event=>{const b=event.target.closest('[data-candidate]');if(b){selected=candidates.find(c=>c.id===b.dataset.candidate);render();}};render();

// Overlays real /predict/substitute alternatives onto the demo candidate
// fixture (replacing the current selected pair's fixed partner drug —
// citalopram — with a safer alternative to amitriptyline). Keeps the demo
// fixtures' ids so simulate()/badges keep working structurally; only the
// displayed name/score/badge reflect the real backend response.
const CID_CITALOPRAM = 2771, CID_AMITRIPTYLINE = 2160;
async function syncRealSubstitutes() {
  if (!candidates.length || !window.ApiClient || !ApiClient.isAuthenticated()) return;
  try {
    const result = await ApiClient.substitute({
      drug_a_cid: String(CID_CITALOPRAM),
      drug_b_cid: String(CID_AMITRIPTYLINE),
    });
    result.alternatives.slice(0, candidates.length).forEach((alt, i) => {
      candidates[i].name = alt.name;
      candidates[i].score = Math.round(alt.new_top_risk_score);
      candidates[i].badge = alt.risk_reduction > 20 ? 'Best predicted score' : 'More evidence needed';
    });
    render();
  } catch (err) {
    console.warn('Real substitution candidates unavailable, showing demo fixture:', err.message);
  }
}
syncRealSubstitutes();
