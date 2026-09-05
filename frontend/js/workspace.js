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
UI.text('medicinesNote','All values in this case are illustrative.');UI.text('medicinesFootnote','Add dose and indication for a more complete review.');
UI.text('matrixNote','Select a pair to inspect its model evidence.');UI.text('matrixFootnote','Pairwise estimates do not capture all multi-drug effects.');
UI.text('exploreTitle','Explore a change');UI.text('exploreText','Compare hypothetical candidates and their effects across the whole pairwise matrix.');UI.text('findAlternativesBtn','Find alternatives →');
document.getElementById('matrixLegend').innerHTML=['priority','review','lower','unknown'].map(k=>'<span class="legend-chip legend-'+k+'">'+k[0].toUpperCase()+k.slice(1)+'</span>').join('');
function render(){const s=PharmaStore.getState(),e=UI.escape;
  document.getElementById('contextBar').innerHTML='<span class="context-title">Patient Information</span><span class="pill pill-muted">Age '+s.context.age+'</span><span class="pill pill-muted">'+e(s.context.sex)+'</span><a class="btn btn-edit" href="demographic-lens.html" aria-label="Edit patient information">⌕</a>';
  document.getElementById('medicineList').innerHTML=s.medicines.map((m,i)=>'<li class="medicine-item"><span class="medicine-badge">'+String.fromCharCode(65+i)+'</span><span class="medicine-info"><span class="medicine-name">'+e(m.name)+'</span><br><span class="medicine-detail">'+e(m.dose||'Dose not entered')+'</span></span>'+(PUBCHEM_CID_BY_MEDICINE_ID[m.id]?'<button class="medicine-view3d" type="button" data-view3d="'+e(m.id)+'" data-name="'+e(m.name)+'">View 3D</button>':'')+'<button class="medicine-remove" data-remove="'+e(m.id)+'" aria-label="Remove '+e(m.name)+'">×</button></li>').join('')||'<li class="empty-state">Your regimen is empty. Add medicines to begin.</li>';
  document.getElementById('interactionMatrix').innerHTML=UI.matrix(s,true);UI.text('matrixLegendLabels',UI.key(s.medicines));
  const pair=UI.pair(),value=pair.length===2?PharmaStore.score(...s.selectedPair):null,kind=PharmaDemo.classifyScore(value);
  UI.text('reviewNote',pair.length===2?'Selected pair '+pair.map(m=>String.fromCharCode(65+s.medicines.findIndex(x=>x.id===m.id))).join(' × '):'No pair selected');
  UI.text('priorityPill',pair.length<2?'ADD MEDICINES':kind==='priority'?'HIGH PRIORITY':kind.toUpperCase());document.getElementById('priorityPill').dataset.kind=kind;
  UI.text('scoreValue',value??'—');UI.text('scoreMax','/ 100');UI.text('scoreCaption','Synthetic interaction score');UI.text('reviewDescription',pair.length===2?pair.map(m=>m.name).join(' + ')+'. '+(value===null?'No supported estimate for this pair.':'Inspect associated pathways.'):'Add at least two medicines to start your review.');UI.text('inspectPathwayBtn','Inspect pathway ↗');
  document.getElementById('inspectPathwayBtn').disabled=pair.length<2;document.getElementById('findAlternativesBtn').disabled=pair.length<2;
  const graphBtn=document.getElementById('viewDrugGraphBtn');if(graphBtn)graphBtn.disabled=s.medicines.length<2;
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
