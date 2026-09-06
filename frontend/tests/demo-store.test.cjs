const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createStore,classifyScore}=require('../js/demo-store.js');
const memory=()=>{const m=new Map();return {getItem:k=>m.get(k),setItem:(k,v)=>m.set(k,v)}};
test('addition persists without inventing scores',()=>{const mem=memory(),s=createStore(mem),m=s.addMedicine('Example','10 mg');assert.equal(s.getState().medicines.length,5);assert.equal(s.score('amitriptyline',m.id),null);assert.equal(createStore(mem).getState().medicines[4].name,'Example');assert.throws(()=>s.addMedicine('Example'),/already/)});
test('removing a selected medicine repairs the pair and clears simulation',()=>{const s=createStore(memory());s.simulate('candidate-a');s.removeMedicine('amitriptyline');assert.equal(s.getState().simulation,null);assert.ok(!s.getState().selectedPair.includes('amitriptyline'));s.getState().medicines.forEach(m=>s.removeMedicine(m.id));assert.deepEqual(s.getState().selectedPair,[])});
test('simulation preserves baseline and unknowns; applying changes draft only',()=>{const s=createStore(memory()),p=s.simulate('candidate-a');assert.equal(s.score('amitriptyline','citalopram'),82);assert.equal(s.score('candidate-a','citalopram',p.proposed),32);assert.equal(s.score('candidate-a','medicine-d',p.proposed),null);s.applySimulation();assert.equal(s.getState().medicines[0].id,'candidate-a');assert.equal(s.getState().simulation,null)});
test('demographic fixtures only cover supported cohorts and pairs',()=>{const s=createStore(memory());assert.equal(s.demographicEstimate({age:68,sex:'female',stratify:true}).score,82);assert.equal(s.demographicEstimate({age:68,sex:'male',stratify:true}).score,74);assert.equal(s.demographicEstimate({age:68,sex:'unknown',stratify:true}).score,null);assert.equal(s.demographicEstimate({age:68,sex:'female',stratify:false}).score,68);s.selectPair('medicine-c','medicine-d');assert.equal(s.demographicEstimate({age:68,sex:'female',stratify:true}).score,null);assert.equal(classifyScore(null),'unknown');assert.equal(classifyScore(21),'lower')});
test('invalid persistence and unavailable storage are recoverable',()=>{assert.equal(createStore({getItem:()=>'{',setItem:()=>{}}).getState().medicines.length,4);assert.equal(createStore({getItem:()=>'{"version":1,"medicines":[]}',setItem:()=>{}}).getState().medicines.length,4);const s=createStore({getItem:()=>{throw Error('blocked')},setItem:()=>{throw Error('blocked')}});assert.doesNotThrow(()=>s.addMedicine('Example'));assert.throws(()=>s.updateContext({age:-1,sex:'female',stratify:true}),/age/i)});

test('simulation survives page navigation by rebuilding from a trusted candidate fixture',()=>{const mem=memory(),s=createStore(mem);s.simulate('candidate-b');const restored=createStore(mem).getState();assert.equal(restored.simulation.candidate.id,'candidate-b');assert.equal(restored.simulation.proposed.scores['candidate-b|citalopram'],45)});

// setPendingSubstitution() is the real-data counterpart to simulate() above,
// used for a real /predict/substitute candidate against any two regimen
// drugs (not just the amitriptyline/citalopram fixture). It records the
// candidate as-is rather than computing scores itself -- regimen-simulation.js
// fetches real /predict/regimen scores separately -- so these tests cover
// recording, validation, persistence and non-interference with the demo
// score map, not score computation.
test('setPendingSubstitution records a real candidate and survives page navigation',()=>{
  const mem=memory(),s=createStore(mem);
  const candidate={cid:'CID000001046',name:'Pyrazinamide',score:38,similarity:0.38};
  s.setPendingSubstitution(candidate,'amitriptyline','citalopram');
  const live=s.getState().simulation;
  assert.equal(live.isReal,true);
  assert.deepEqual(live.candidate,candidate);
  assert.equal(live.replacedMedicineId,'amitriptyline');
  assert.equal(live.fixedMedicineId,'citalopram');
  const restored=createStore(mem).getState().simulation;
  assert.equal(restored.isReal,true);
  assert.equal(restored.candidate.name,'Pyrazinamide');
  assert.equal(restored.replacedMedicineId,'amitriptyline');
});
test('setPendingSubstitution rejects a medicine no longer in the regimen',()=>{
  const s=createStore(memory());
  assert.throws(()=>s.setPendingSubstitution({cid:'CID1',name:'X',score:1,similarity:0},'not-a-real-id','citalopram'),/no longer in the regimen/);
});
test('mutating the regimen clears a pending real substitution',()=>{
  const s=createStore(memory());
  s.setPendingSubstitution({cid:'CID1',name:'X',score:1,similarity:0},'amitriptyline','citalopram');
  s.removeMedicine('medicine-d');
  assert.equal(s.getState().simulation,null);
});
test('a pending real substitution for two regimen drugs leaves the demo score map untouched (no fabricated score)',()=>{
  const s=createStore(memory());
  s.setPendingSubstitution({cid:'CID000001046',name:'Pyrazinamide',score:38,similarity:0.38},'amitriptyline','citalopram');
  assert.equal(s.score('amitriptyline','citalopram'),82);
  assert.equal(s.score('amitriptyline','medicine-c'),34);
});
