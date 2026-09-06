// PubChem CIDs for the seed catalog's real compounds, used by the "View 3D"
// button next to a medicine — only entries here get the button. Custom-added
// or placeholder medicines (Medicine C/D, anything typed into the add-a-
// medicine form) intentionally have no CID and no button.
const PUBCHEM_CID_BY_MEDICINE_ID = {
  amitriptyline: 2160,
  citalopram: 2771,
};

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

function render(){const s=PharmaStore.getState(),e=UI.escape;
  document.getElementById('contextBar').innerHTML='<span class="context-title">Patient Information</span><span class="pill pill-muted">Age '+s.context.age+'</span><span class="pill pill-muted">'+e(s.context.sex)+'</span><a class="btn btn-edit" href="demographic-lens.html" aria-label="Edit patient information">✎</a>';
  document.getElementById('medicineList').innerHTML=s.medicines.map((m,i)=>'<li class="medicine-item"><span class="medicine-badge">'+String.fromCharCode(65+i)+'</span><span class="medicine-info"><span class="medicine-name">'+e(m.name)+'</span><br><span class="medicine-detail">'+e(m.dose||'Dose not entered')+'</span></span>'+(PUBCHEM_CID_BY_MEDICINE_ID[m.id]?'<button class="medicine-view3d" type="button" data-view3d="'+e(m.id)+'" data-name="'+e(m.name)+'">View 3D</button>':'')+'<button class="medicine-remove" data-remove="'+e(m.id)+'" aria-label="Remove '+e(m.name)+'">×</button></li>').join('')||'<li class="empty-state">Your regimen is empty. Add medicines to begin.</li>';
  document.getElementById('interactionMatrix').innerHTML=UI.matrix(s,true);UI.text('matrixLegendLabels',UI.key(s.medicines));
  applyMatrixScale();
  const pair=UI.pair(),value=pair.length===2?PharmaStore.score(...s.selectedPair):null,kind=PharmaDemo.classifyScore(value);
  UI.text('reviewTitle',pair.length===2?pair.map(m=>m.name).join(' + '):'Select a pair');UI.text('reviewNote','');
  UI.text('priorityPill',pair.length<2?'ADD MEDICINES':kind==='priority'?'HIGH PRIORITY':kind.toUpperCase());document.getElementById('priorityPill').dataset.kind=kind;
  UI.text('scoreValue',value??'—');if(value!==null){const node=document.getElementById('scoreValue');const countKey=pair.map(m=>m.id).join('|')+':'+value;if(node.dataset.countKey!==countKey){node.dataset.countKey=countKey;const start=performance.now();const tick=now=>{const t=Math.min(1,(now-start)/1000);node.textContent=Math.round(value*(t*t*(3-2*t)))+'%';if(t<1)requestAnimationFrame(tick)};node.textContent='0%';requestAnimationFrame(tick)}}UI.text('scoreMax','');UI.text('scoreCaption','Synthetic interaction score');UI.text('reviewDescription',pair.length===2?pair.map(m=>m.name).join(' + ')+'. '+(value===null?'No supported estimate for this pair.':'Inspect associated pathways.'):'Add at least two medicines to start your review.');UI.text('inspectPathwayBtn','Inspect pathway ↗');
  document.getElementById('inspectPathwayBtn').disabled=pair.length<2;document.getElementById('findAlternativesBtn').disabled=pair.length<2;
  const graphBtn=document.getElementById('viewDrugGraphBtn');if(graphBtn)graphBtn.disabled=s.medicines.length<2;
  syncRealPredictions();
}

// Overlays real GNN predictions from POST /predict/regimen onto the
// already-rendered demo matrix, for whichever medicines have a real PubChem
// CID (PUBCHEM_CID_BY_MEDICINE_ID) — placeholder/custom-added medicines keep
// their demo "?" cells since the backend has no drug to look them up by.
// Silently leaves the demo values in place on any failure (backend down,
// unauthenticated, <2 real-CID medicines) so the page still works standalone.
let predictionRequestToken = 0;
async function syncRealPredictions() {
  const myToken = ++predictionRequestToken;
  const s = PharmaStore.getState();
  const eligible = s.medicines
    .map((m, i) => ({ m, letter: String.fromCharCode(65 + i), cid: PUBCHEM_CID_BY_MEDICINE_ID[m.id] }))
    .filter((x) => x.cid);
  if (eligible.length < 2 || !window.ApiClient || !ApiClient.isAuthenticated()) return;

  let result;
  try {
    result = await ApiClient.predictRegimen({ drug_cids: eligible.map((x) => String(x.cid)) });
  } catch (err) {
    console.warn('Real regimen prediction unavailable, showing demo scores:', err.message);
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
}
document.getElementById('medicineList').onclick=e=>{
  const remove=e.target.closest('[data-remove]');
  if(remove){PharmaStore.removeMedicine(remove.dataset.remove);render();UI.announce('Medicine removed. Regimen updated.');return;}
  const view3d=e.target.closest('[data-view3d]');
  if(view3d)window.openMoleculeViewer(PUBCHEM_CID_BY_MEDICINE_ID[view3d.dataset.view3d],view3d.dataset.name);
};
document.getElementById('interactionMatrix').onclick=e=>{const b=e.target.closest('[data-a]');if(b){PharmaStore.selectPair(b.dataset.a,b.dataset.b);render();UI.announce('Selected '+UI.pair().map(m=>m.name).join(' and '));}};
document.getElementById('inspectPathwayBtn').onclick=()=>UI.go('pathway-inspector');document.getElementById('findAlternativesBtn').onclick=()=>UI.go('substitution-engine');
const drugGraphBtn=document.getElementById('viewDrugGraphBtn');if(drugGraphBtn)drugGraphBtn.onclick=()=>window.openDrugGraph();
function addMedicine(){const d=UI.modal('Add a medicine','<form id="medicineForm"><label class="field-label" for="medicineName">Medicine name</label><input class="field-box" id="medicineName" name="name" required maxlength="60" autocomplete="off" list="medicineOptions"><datalist id="medicineOptions"><option>Amitriptyline</option><option>Citalopram</option><option>Medicine C</option><option>Medicine D</option></datalist><label class="field-label" for="medicineDose">Dose / notes (optional)</label><input class="field-box" id="medicineDose" name="dose" maxlength="40"><p class="field-note">New combinations display unknown until a supported fixture or API result exists.</p><p id="medicineError" role="alert"></p><button class="btn btn-primary" type="submit">Add medicine</button></form>');document.getElementById('medicineForm').onsubmit=e=>{e.preventDefault();try{PharmaStore.addMedicine(document.getElementById('medicineName').value,document.getElementById('medicineDose').value);d.close();render();UI.announce('Medicine added. Regimen updated.');}catch(error){UI.text('medicineError',error.message);}};document.getElementById('medicineName').focus();}
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
      const letterKey = [String.fromCharCode(65 + i), String.fromCharCode(65 + j)].sort().join('-');
      matrixScores[letterKey] = PharmaStore.score(s.medicines[i].id, s.medicines[j].id, s);
    }
  }
  return { medicines, matrixScores, thresholds: { priority: 70, review: 30 } };
};
