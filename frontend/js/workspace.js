// Real PubChem CIDs for the two seed-fixture drugs that happen to be real
// compounds (Amitriptyline/Citalopram). Anything added through the "Add a
// medicine" flow below gets its real CID recorded in DYNAMIC_CID_STORE_KEY
// instead — see getMedicineCid()/rememberMedicineCid(). Nothing in this file
// invents a CID for a drug the picker didn't return from the real backend.
const PUBCHEM_CID_BY_MEDICINE_ID = {
  amitriptyline: 2160,
  citalopram: 2771,
};

// Persists {medicineId: pubchemCid} for medicines added via the real vocab
// search, so a real CID survives a reload (PharmaStore's own ids are
// otherwise opaque — it doesn't know or care about PubChem CIDs).
const DYNAMIC_CID_STORE_KEY = 'pharmagnn_medicine_cids';
function loadDynamicCidMap() {
  try {
    return JSON.parse(localStorage.getItem(DYNAMIC_CID_STORE_KEY) || '{}');
  } catch {
    return {};
  }
}
function rememberMedicineCid(medicineId, cid) {
  const map = loadDynamicCidMap();
  map[medicineId] = cid;
  try {
    localStorage.setItem(DYNAMIC_CID_STORE_KEY, JSON.stringify(map));
  } catch {}
}
function getMedicineCid(medicineId) {
  return PUBCHEM_CID_BY_MEDICINE_ID[medicineId] || loadDynamicCidMap()[medicineId] || null;
}

renderWorkspaceShell('Regimen overview');
UI.text('pageHeading','One regimen. A clearer picture.');UI.text('pageSubhead','Review the priority pairs, then explore what might change.');
UI.text('medicinesNote');UI.text('medicinesFootnote','Add dose and indication for a more complete review.');
UI.text('exploreTitle','Explore a change');UI.text('exploreText','');UI.text('findAlternativesBtn','Find alternatives →');
document.getElementById('matrixLegend').innerHTML=['priority','review','lower','unknown'].map(k=>'<span class="legend-chip legend-'+k+'">'+k[0].toUpperCase()+k.slice(1)+'</span>').join('');
// Shrinks the interaction matrix's cell size/font as the regimen grows, via
// CSS custom properties consumed in css/workspace.css. Measures the card's
// actually-available width (minus a fixed side margin, kept centered) against
// the table's natural (max-size) width, rather than guessing from medicine
// count. Shrinking — not scrolling — is the primary way this stays contained;
// overflow-x:auto on .matrix-wrap only ever engages as a last-resort safety
// net if cells have already hit MATRIX_MIN_CELL and it still doesn't fit.
const MATRIX_SIDE_MARGIN = 16; // px, each side — also set as --matrix-side-margin
const MATRIX_MAX_CELL = 78, MATRIX_MIN_CELL = 18;
const MATRIX_MAX_FONT = 16, MATRIX_MIN_FONT = 9;
function applyMatrixScale() {
  const card = document.getElementById('matrixCard');
  const table = document.getElementById('interactionMatrix');
  if (!card || !table) return;

  // Measure against the natural/max size first, not whatever scale was left
  // from the previous render — otherwise a shrink can never recover once a
  // medicine is later removed.
  card.style.setProperty('--matrix-cell-size', MATRIX_MAX_CELL + 'px');
  card.style.setProperty('--matrix-font-size', MATRIX_MAX_FONT + 'px');
  // max-content (not '') for measuring: clearing the inline width falls
  // back to the base .interaction-matrix{width:100%} rule, which would
  // measure the stretched width instead of the table's true content size.
  table.style.setProperty('width', 'max-content', 'important');

  const available = card.clientWidth - MATRIX_SIDE_MARGIN * 2;
  let needed = table.scrollWidth;

  if (needed > available && available > 0) {
    // border-spacing doesn't shrink along with the cells, so scaling purely
    // by width ratio can slightly overshoot; a small safety margin avoids
    // landing just barely over the line into a scrollbar anyway.
    const scale = Math.max((available / needed) * 0.92, MATRIX_MIN_CELL / MATRIX_MAX_CELL);
    card.style.setProperty('--matrix-cell-size', Math.round(MATRIX_MAX_CELL * scale) + 'px');
    card.style.setProperty('--matrix-font-size', Math.max(MATRIX_MIN_FONT, Math.round(MATRIX_MAX_FONT * scale)) + 'px');
    needed = table.scrollWidth;
  }

  table.style.setProperty('width', needed + 'px', 'important');

  // CSS margin:0 auto on this <table> didn't reliably resolve to centering
  // in testing (computed to 0/0 regardless of a definite width being set —
  // an engine quirk specific to auto-margin resolution on table boxes here),
  // so the side margins are computed and set explicitly instead.
  const wrap = card.querySelector('.matrix-wrap');
  const sideMargin = Math.max(0, Math.round((wrap.clientWidth - needed) / 2));
  table.style.setProperty('margin-left', sideMargin + 'px', 'important');
  table.style.setProperty('margin-right', sideMargin + 'px', 'important');
}
window.addEventListener('resize', () => requestAnimationFrame(applyMatrixScale));

// The demo fixture (PharmaStore) invents a plausible-looking score for any
// pair, including drugs with no real CID (e.g. the seed's Medicine C/D
// placeholders) — that's exactly the fabricated-data-shown-as-real problem.
// Right after the demo table renders, blank out any cell whose pair isn't
// backed by two real, model-known CIDs, before syncRealPredictions() has
// even had a chance to run. syncRealPredictions() then fills in the pairs
// it can with genuine model output; whatever's left honestly reads "?".
function markUnverifiedCells() {
  const table = document.getElementById('interactionMatrix');
  if (!table) return;
  table.querySelectorAll('td[class^="cell-"]:not(.cell-diagonal) button[data-a]').forEach((btn) => {
    if (getMedicineCid(btn.dataset.a) && getMedicineCid(btn.dataset.b)) return;
    const cell = btn.closest('td');
    cell.className = 'cell-unknown';
    btn.textContent = '?';
  });
}

// Renders the review card (title/pill/score/description) for the currently
// selected pair from a given score. Shared by render() (demo-fixture score,
// or null when the pair isn't real-CID-backed) and syncRealPredictions()
// (the genuine model score, once it arrives) so the two never disagree —
// whichever rendered last wins, and syncRealPredictions always runs last.
function renderReviewCard(pair,value){
  const kind=PharmaDemo.classifyScore(value);
  UI.text('reviewTitle',pair.length===2?pair.map(m=>m.name).join(' + '):'Select a pair');UI.text('reviewNote','');
  UI.text('priorityPill',pair.length<2?'ADD MEDICINES':kind==='priority'?'HIGH PRIORITY':kind.toUpperCase());document.getElementById('priorityPill').dataset.kind=kind;
  UI.text('scoreValue',value??'—');if(value!==null){const node=document.getElementById('scoreValue');const countKey=pair.map(m=>m.id).join('|')+':'+value;if(node.dataset.countKey!==countKey){node.dataset.countKey=countKey;const start=performance.now();const tick=now=>{const t=Math.min(1,(now-start)/1000);node.textContent=Math.round(value*(t*t*(3-2*t)))+'%';if(t<1)requestAnimationFrame(tick)};node.textContent='0%';requestAnimationFrame(tick)}}UI.text('scoreMax','');UI.text('scoreCaption',value===null?'Synthetic interaction score':'Model-predicted interaction score');UI.text('reviewDescription',pair.length===2?pair.map(m=>m.name).join(' + ')+'. '+(value===null?'No supported estimate for this pair.':'Inspect associated pathways.'):'Add at least two medicines to start your review.');UI.text('inspectPathwayBtn','Inspect pathway ↗');
  document.getElementById('inspectPathwayBtn').disabled=pair.length<2;document.getElementById('findAlternativesBtn').disabled=pair.length<2;
}

function render(){const s=PharmaStore.getState(),e=UI.escape;
  document.getElementById('contextBar').innerHTML='<span class="context-title">Patient Information</span><span class="pill pill-muted">Age '+s.context.age+'</span><span class="pill pill-muted">'+e(s.context.sex)+'</span><a class="btn btn-edit" href="demographic-lens.html" aria-label="Edit patient information">✎</a>';
  document.getElementById('medicineList').innerHTML=s.medicines.map((m,i)=>'<li class="medicine-item"><span class="medicine-badge">'+String.fromCharCode(65+i)+'</span><span class="medicine-info"><span class="medicine-name" title="'+e(m.name)+'">'+e(m.name)+'</span><br><span class="medicine-detail">'+e(m.dose||'Dose not entered')+'</span></span>'+(getMedicineCid(m.id)?'<button class="medicine-view3d" type="button" data-view3d="'+e(m.id)+'" data-name="'+e(m.name)+'">View 3D</button>':'')+'<button class="medicine-remove" data-remove="'+e(m.id)+'" aria-label="Remove '+e(m.name)+'">×</button></li>').join('')||'<li class="empty-state">Your regimen is empty. Add medicines to begin.</li>';
  document.getElementById('interactionMatrix').innerHTML=UI.matrix(s,true);UI.text('matrixLegendLabels',UI.key(s.medicines));
  markUnverifiedCells();
  applyMatrixScale();
  const pair=UI.pair();
  const bothReal=pair.length===2&&getMedicineCid(pair[0].id)&&getMedicineCid(pair[1].id);
  const value=bothReal?PharmaStore.score(...s.selectedPair):null;
  renderReviewCard(pair,value);
  const graphBtn=document.getElementById('viewDrugGraphBtn');if(graphBtn)graphBtn.disabled=s.medicines.length<2;
  syncRealPredictions();
}

// Fetches real GNN predictions from POST /predict/regimen for every medicine
// with a real CID (getMedicineCid) and overlays them onto the matrix,
// overwriting markUnverifiedCells()'s placeholders with genuine model
// output. Pairs still missing a real CID on either side stay honestly "?" —
// nothing here ever falls back to a fabricated number.
let predictionRequestToken = 0;
async function syncRealPredictions() {
  const myToken = ++predictionRequestToken;
  const s = PharmaStore.getState();
  const eligible = s.medicines
    .map((m, i) => ({ m, letter: String.fromCharCode(65 + i), cid: getMedicineCid(m.id) }))
    .filter((x) => x.cid);
  if (eligible.length < 2 || !window.ApiClient || !ApiClient.isAuthenticated()) return;

  let result;
  try {
    result = await ApiClient.predictRegimen({ drug_cids: eligible.map((x) => ApiClient.toModelCid(x.cid)) });
  } catch (err) {
    console.warn('Real regimen prediction unavailable — leaving unverified pairs as "?":', err.message);
    return;
  }
  if (myToken !== predictionRequestToken) return; // state changed while this was in flight

  const table = document.getElementById('interactionMatrix');
  eligible.forEach((row, i) => {
    eligible.forEach((col, j) => {
      if (i === j) return;
      const score = result.interaction_matrix[i][j];
      const kind = PharmaDemo.classifyScore(score);
      const rowIndex = row.letter.charCodeAt(0) - 65; // 0-based position in the full medicine list
      const colIndex = col.letter.charCodeAt(0) - 65;
      const cell = table.querySelector(
        `tbody tr:nth-child(${rowIndex + 1}) td:nth-child(${colIndex + 2})`
      );
      if (!cell) return;
      cell.className = `cell-${kind}`;
      const target = cell.querySelector('button, span') || cell;
      target.textContent = Math.round(score);
    });
  });

  // The review card below the matrix shows the same selected pair — keep it
  // in agreement with the cell just overwritten above rather than leaving it
  // on whatever demo-fixture value render() computed synchronously earlier.
  const pair = UI.pair();
  if (pair.length === 2) {
    const i = eligible.findIndex((x) => x.m.id === pair[0].id);
    const j = eligible.findIndex((x) => x.m.id === pair[1].id);
    if (i !== -1 && j !== -1) {
      renderReviewCard(pair, Math.round(result.interaction_matrix[i][j]));
    }
  }
}
document.getElementById('medicineList').onclick=e=>{
  const remove=e.target.closest('[data-remove]');
  if(remove){PharmaStore.removeMedicine(remove.dataset.remove);render();UI.announce('Medicine removed. Regimen updated.');return;}
  const view3d=e.target.closest('[data-view3d]');
  if(view3d)window.openMoleculeViewer(getMedicineCid(view3d.dataset.view3d),view3d.dataset.name);
};
document.getElementById('interactionMatrix').onclick=e=>{const b=e.target.closest('[data-a]');if(b){PharmaStore.selectPair(b.dataset.a,b.dataset.b);const pair=UI.pair(),shownScore=Number(b.textContent.trim()),value=Number.isFinite(shownScore)&&b.textContent.trim()!==''?shownScore:PharmaStore.score(...PharmaStore.getState().selectedPair);renderReviewCard(pair,value);UI.announce('Selected '+pair.map(m=>m.name).join(' and '));}};
document.getElementById('inspectPathwayBtn').onclick=()=>UI.go('pathway-inspector');document.getElementById('findAlternativesBtn').onclick=()=>UI.go('substitution-engine');
const drugGraphBtn=document.getElementById('viewDrugGraphBtn');if(drugGraphBtn)drugGraphBtn.onclick=()=>window.openDrugGraph();

// "Add a medicine" only ever offers drugs the model actually knows — a live
// search against the real /vocab/drugs endpoint, never free text. A result
// must be clicked (recording its real cid) before the form can submit, so
// there's no path to adding a drug the backend can't look up.
function addMedicine(){
  const d=UI.modal('Add a medicine','<form id="medicineForm"><label class="field-label" for="medicineSearch">Search the model\'s drug list</label><input class="field-box" id="medicineSearch" name="search" autocomplete="off" placeholder="Start typing a drug name…"><ul id="medicineResults" class="candidate-list" style="max-height:220px;overflow-y:auto;margin-top:8px"></ul><label class="field-label" for="medicineDose">Dose / notes (optional)</label><input class="field-box" id="medicineDose" name="dose" maxlength="40"><p class="field-note">Only drugs the model was trained on can be added — search results are the model\'s real vocabulary, not free text.</p><p id="medicineError" role="alert"></p><button class="btn btn-primary" type="submit" id="medicineSubmit" disabled>Add medicine</button></form>');
  const searchInput=document.getElementById('medicineSearch');
  const resultsList=document.getElementById('medicineResults');
  const submitBtn=document.getElementById('medicineSubmit');
  let selected=null;
  let searchToken=0;

  async function runSearch(q){
    const myToken=++searchToken;
    if(!q||q.trim().length<2){resultsList.innerHTML='';return;}
    let results;
    try{results=await ApiClient.searchDrugs(q.trim(),20,0);}
    catch(err){if(myToken===searchToken)resultsList.innerHTML='<li class="empty-state">'+UI.escape(err.message||'Search failed.')+'</li>';return;}
    if(myToken!==searchToken)return;
    resultsList.innerHTML=results.length?results.map(r=>'<li><button type="button" class="candidate-row" data-cid="'+UI.escape(r.cid)+'" data-name="'+UI.escape(r.name)+'">'+UI.escape(r.name)+'</button></li>').join(''):'<li class="empty-state">No matching drug in the model\'s vocabulary.</li>';
  }
  let debounce=null;
  searchInput.addEventListener('input',()=>{selected=null;submitBtn.disabled=true;clearTimeout(debounce);debounce=setTimeout(()=>runSearch(searchInput.value),250);});
  resultsList.addEventListener('click',e=>{
    const b=e.target.closest('[data-cid]');if(!b)return;
    selected={cid:b.dataset.cid,name:b.dataset.name};
    searchInput.value=b.dataset.name;
    resultsList.innerHTML='';
    submitBtn.disabled=false;
  });

  document.getElementById('medicineForm').onsubmit=e=>{
    e.preventDefault();
    if(!selected){UI.text('medicineError','Pick a drug from the search results first.');return;}
    try{
      const created=PharmaStore.addMedicine(selected.name,document.getElementById('medicineDose').value);
      rememberMedicineCid(created.id,selected.cid);
      d.close();render();UI.announce('Medicine added. Regimen updated.');
    }catch(error){UI.text('medicineError',error.message);}
  };
  searchInput.focus();
}
document.getElementById('addMedicineBtn').onclick=addMedicine;render();if(location.hash==='#add-medicine')addMedicine();

// Exposed so drug-graph.js can build the 3D relationship graph from the same
// live regimen state driving the 2D matrix above — not a separate dataset.
// Thresholds (70/30) match PharmaDemo.classifyScore exactly, so the 3D view's
// priority/review/lower coloring agrees with the 2D matrix's.
window.getRegimenGraphData = function () {
  const s = PharmaStore.getState();
  const medicines = s.medicines.map((m, i) => ({ letter: String.fromCharCode(65 + i), name: m.name }));
  const matrixScores = {};
  for (let i = 0; i < s.medicines.length; i++) {
    for (let j = i + 1; j < s.medicines.length; j++) {
      const a = s.medicines[i], b = s.medicines[j];
      const letterKey = [String.fromCharCode(65 + i), String.fromCharCode(65 + j)].sort().join('-');
      matrixScores[letterKey] = getMedicineCid(a.id) && getMedicineCid(b.id) ? PharmaStore.score(a.id, b.id, s) : null;
    }
  }
  return { medicines, matrixScores, thresholds: { priority: 70, review: 30 } };
};
