// Same real-CID map as workspace.js (kept local/duplicated rather than
// shared, matching this codebase's existing no-shared-config convention).
const PUBCHEM_CID_BY_MEDICINE_ID = { amitriptyline: 2160, citalopram: 2771 };

renderWorkspaceShell('Demographic lens');
UI.text('pageHeading','The same regimen. More context.');UI.text('pageSubhead','Compare estimates without hiding uncertainty or missing evidence.');UI.text('contextSubtitle','Demo case 004');
const context={...PharmaStore.getState().context};
document.getElementById('ageField').outerHTML='<input class="field-box" id="ageField" type="number" min="0" max="120" step="1" required value="'+context.age+'">';
UI.text('stratumNote',"Uses the model’s dataset definition. Gender identity is not inferred.");UI.text('toggleLabel','Compare stratified estimate');UI.text('toggleNote','Changes affect this demo comparison. No universal sex-based multiplier is implied by these estimates.');UI.text('updateComparisonBtn','Update comparison →');
document.getElementById('stratumList').innerHTML=['female','male','unknown'].map(k=>'<button type="button" class="stratum-option" data-sex="'+k+'"><span class="stratum-dot"></span>'+({female:'Female',male:'Male',unknown:'Unknown / not recorded'}[k])+'</button>').join('');
function controls(){document.querySelectorAll('[data-sex]').forEach(b=>{b.classList.toggle('selected',b.dataset.sex===context.sex);b.setAttribute('aria-pressed',b.dataset.sex===context.sex);});const t=document.getElementById('stratifyToggle');t.classList.toggle('on',context.stratify);t.setAttribute('aria-checked',context.stratify);t.setAttribute('aria-labelledby','toggleLabel');}
function estimates(){const v=PharmaStore.demographicEstimate(context),label=context.stratify?context.sex+' · age '+context.age:'Unstratified',e=UI.escape;UI.text('comparisonSubtitle',(UI.pair().map(m=>m.name).join(' × ')||'No pair selected')+' · Synthetic score, not probability');document.getElementById('estimateRow').innerHTML='<div class="estimate-box"><span class="estimate-tag">UNSTRATIFIED</span><div class="estimate-score">'+(v.baseline??'—')+'</div><p class="estimate-range">'+(v.baseline===null?'No supported estimate':'Illustrative range 56–79')+'</p></div><div class="estimate-box highlighted"><span class="estimate-tag">'+e(label.toUpperCase())+'</span><div class="estimate-score-row"><div class="estimate-score">'+(v.score??'—')+'</div>'+(v.score===null?'':'<span class="pill pill-muted">'+(v.score-v.baseline>=0?'+':'')+(v.score-v.baseline)+' points</span>')+'</div><p class="estimate-range">'+e(v.range)+'</p></div>';UI.text('estimateFootnote','Synthetic cohort fixtures only. Differences do not establish a subgroup effect.');UI.text('coverageSubtitle','Understand what supports the comparison.');document.getElementById('coverageList').innerHTML=[['Population',label],['Coverage',v.score===null?'Insufficient evidence':'Limited subgroup representation'],['Calibration','Not evaluated in this prototype'],['When unsupported','Retain baseline; do not infer safety']].map(([a,b])=>'<dt>'+e(a)+'</dt><dd>'+e(b)+'</dd>').join('');syncRealEstimate();}

// Overlays real /predict/pairwise scores (unstratified call, then a second
// call with patient_sex set when the toggle is on) onto the demo estimate
// boxes estimates() just rendered — silently leaves the demo fixture in
// place if the pair isn't two real-CID drugs, or the call fails.
let estimateRequestToken = 0;
async function syncRealEstimate() {
  const myToken = ++estimateRequestToken;
  const pair = UI.pair();
  if (pair.length !== 2 || !window.ApiClient || !ApiClient.isAuthenticated()) return;
  const cidA = PUBCHEM_CID_BY_MEDICINE_ID[pair[0].id];
  const cidB = PUBCHEM_CID_BY_MEDICINE_ID[pair[1].id];
  if (!cidA || !cidB) return;

  try {
    const unstratified = await ApiClient.predictPairwise({
      drug_a_cid: ApiClient.toModelCid(cidA),
      drug_b_cid: ApiClient.toModelCid(cidB),
    });
    let stratified = unstratified;
    if (context.stratify && (context.sex === 'female' || context.sex === 'male')) {
      stratified = await ApiClient.predictPairwise({
        drug_a_cid: ApiClient.toModelCid(cidA),
        drug_b_cid: ApiClient.toModelCid(cidB),
        patient_sex: context.sex.toUpperCase(),
      });
    }
    if (myToken !== estimateRequestToken) return; // context changed while this was in flight

    const boxes = document.querySelectorAll('#estimateRow .estimate-score');
    if (boxes[0]) boxes[0].textContent = Math.round(unstratified.top_risk_score);
    if (boxes[1]) boxes[1].textContent = Math.round(stratified.top_risk_score);
    const delta = Math.round(stratified.top_risk_score - unstratified.top_risk_score);
    const deltaPill = document.querySelector('#estimateRow .pill-muted');
    if (deltaPill) deltaPill.textContent = (delta >= 0 ? '+' : '') + delta + ' points';
  } catch (err) {
    console.warn('Real pairwise prediction unavailable, showing demo estimate:', err.message);
  }
}

document.getElementById('stratumList').onclick=e=>{const b=e.target.closest('[data-sex]');if(b){context.sex=b.dataset.sex;controls();estimates();}};
document.getElementById('stratifyToggle').onclick=()=>{context.stratify=!context.stratify;controls();estimates();};
document.getElementById('updateComparisonBtn').onclick=()=>{const input=document.getElementById('ageField');if(!input.reportValidity())return;context.age=Number(input.value);try{PharmaStore.updateContext(context);estimates();UI.announce('Patient context and comparison updated.');}catch(error){UI.announce(error.message);}};controls();estimates();
