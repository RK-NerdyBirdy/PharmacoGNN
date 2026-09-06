// Same real-CID lookup as workspace.js: static seed CIDs plus anything the
// user added via the real vocab search (persisted in workspace.js's
// DYNAMIC_CID_STORE_KEY). Kept local/duplicated rather than shared, matching
// this codebase's existing no-shared-config convention.
const PUBCHEM_CID_BY_MEDICINE_ID = { amitriptyline: 2160, citalopram: 2771 };
const DYNAMIC_CID_STORE_KEY = 'pharmagnn_medicine_cids';
function loadDynamicCidMap() {
  try { return JSON.parse(localStorage.getItem(DYNAMIC_CID_STORE_KEY) || '{}'); }
  catch { return {}; }
}
function getMedicineCid(medicineId) {
  return PUBCHEM_CID_BY_MEDICINE_ID[medicineId] || loadDynamicCidMap()[medicineId] || null;
}

renderWorkspaceShell('Substitution engine');
UI.text('rankedNote','Ranked by real model-predicted score ↓');
UI.text('candidateBanner','Candidates are the model\'s own suggestions for replacing one drug in the selected pair. A lower predicted score does not by itself establish clinical safety or interchangeability.');

const e = UI.escape;
const pair = UI.pair();
// This used to always compare amitriptyline against citalopram no matter
// what pair was actually selected in the workspace — the same
// hardcoded-regardless-of-selection bug as the matrix/pathway pages had.
// Now it operates on whichever pair is actually selected, as long as the
// model knows both drugs (has a real CID for each).
const bothReal = pair.length === 2 && getMedicineCid(pair[0].id) && getMedicineCid(pair[1].id);
// Per SubstitutionRequest: drug_a_cid is "the fixed drug in the high-risk
// pair" (kept as-is), drug_b_cid is "the drug to search safer alternatives
// for" (replaced). We replace pair[0], keeping pair[1] fixed.
const replacedDrug = pair[0], fixedDrug = pair[1];

let candidates = []; // real alternatives from the model; empty until/unless syncRealSubstitutes() fills it
let selected = null;
let originalScore = null;

UI.text('pageHeading', replacedDrug ? replacedDrug.name : 'Substitution engine');
UI.text('pageSubhead', 'Candidate comparison');

if (!bothReal) {
  document.getElementById('replaceCard').innerHTML = '<div class="replace-block"><span class="context-label">REPLACE IN DRAFT</span><span class="replace-drug-name">No supported pair selected</span></div>';
} else {
  document.getElementById('replaceCard').innerHTML =
    '<div class="replace-block"><span class="context-label">REPLACE IN DRAFT</span><span class="replace-drug-name">'+e(replacedDrug.name)+'</span></div>' +
    '<div class="replace-block"><span class="context-label">FIXED PARTNER DRUG</span><div class="field-box">'+e(fixedDrug.name)+'</div></div>' +
    '<div class="replace-tags"><span class="pill pill-muted">Preserve regimen</span><span class="pill pill-muted">Review contraindications</span></div>';
}

function render(){
  const list = document.getElementById('candidateList');
  if (!bothReal) {
    list.innerHTML = '<li class="empty-state">Select two medicines the model actually knows (added via the real search) to compare alternatives. <a href="workspace.html">Return to the regimen</a>.</li>';
  } else if (!candidates.length) {
    list.innerHTML = '<li class="empty-state">Loading model-predicted alternatives for '+e(replacedDrug.name)+' + '+e(fixedDrug.name)+'…</li>';
  } else {
    list.innerHTML = candidates.map((c,i)=>'<li><button type="button" class="candidate-row '+(selected&&c.cid===selected.cid?'selected':'')+'" data-cid="'+e(c.cid)+'" aria-pressed="'+(selected&&c.cid===selected.cid)+'"><span class="candidate-rank">0'+(i+1)+'</span><span class="candidate-info"><span class="candidate-name">'+e(c.name)+'</span><span class="candidate-subtitle">Model-predicted alternative</span><span class="candidate-badge '+(i?'badge-warn':'badge-good')+'">'+(i?'More evidence needed':'Best predicted score')+'</span></span><span class="candidate-score-block"><span class="candidate-score">'+Math.round(c.score)+'</span><span class="candidate-score-max">/ 100</span></span><span class="candidate-delta-block"><span class="candidate-delta">'+(Math.round(c.score-originalScore))+'</span><span class="candidate-delta-label">points</span></span></button></li>').join('');
  }

  const card=document.getElementById('candidateDetailCard');
  if(!bothReal){card.innerHTML='<h2>Evidence is needed</h2><p>Alternatives are not invented for unsupported medicines.</p>';return;}
  if(!selected){card.innerHTML='<h2>'+(candidates.length?'Choose a candidate':'No alternative found')+'</h2><p>'+(candidates.length?'':'The model did not return a safer alternative for this pair (either it is not high-risk, or none reduce risk).')+'</p>';return;}
  const count=PharmaStore.getState().medicines.length;
  card.innerHTML='<h2 class="candidate-detail-name">'+e(selected.name)+'</h2><div class="detail-rows">'+[['Predicted risk reduction',Math.round(originalScore-selected.score)+' points'],['Similarity to original',Math.round(selected.similarity*100)+'%'],['Regimen coverage',count*(count-1)/2+' pairwise checks']].map(([a,b])=>'<div class="detail-row"><span class="detail-term">'+a+'</span><span class="detail-value">'+b+'</span></div>').join('')+'</div><button class="btn btn-primary ws-btn-block" id="simulateBtn">Simulate this candidate</button>';
  document.getElementById('simulateBtn').onclick=()=>{
    try{PharmaStore.setPendingSubstitution({cid:selected.cid,name:selected.name,score:selected.score,similarity:selected.similarity},replacedDrug.id,fixedDrug.id);UI.go('regimen-simulation');}
    catch(err){UI.announce(err.message);}
  };
}
document.getElementById('candidateList').onclick=event=>{const b=event.target.closest('[data-cid]');if(b){selected=candidates.find(c=>c.cid===b.dataset.cid);render();}};
render();

// Fetches real alternatives from /predict/substitute for whichever pair is
// actually selected — replacing the old behavior of always querying
// amitriptyline vs citalopram regardless of selection.
async function syncRealSubstitutes() {
  if (!bothReal || !window.ApiClient || !ApiClient.isAuthenticated()) return;
  try {
    const result = await ApiClient.substitute({
      drug_a_cid: ApiClient.toModelCid(getMedicineCid(fixedDrug.id)),
      drug_b_cid: ApiClient.toModelCid(getMedicineCid(replacedDrug.id)),
    });
    originalScore = result.original_top_risk_score;
    candidates = result.alternatives.map((alt) => ({
      cid: alt.cid,
      name: alt.name,
      score: alt.new_top_risk_score,
      similarity: alt.similarity_to_original,
    }));
    selected = candidates[0] || null;
    render();
  } catch (err) {
    console.warn('Real substitution candidates unavailable:', err.message);
    candidates = [];
    render();
  }
}
syncRealSubstitutes();
