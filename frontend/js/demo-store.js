/* Demo-only provider. Replace provider methods with an API adapter when integrating inference/auth. */
(function (root) {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const key = (a,b) => [a,b].sort().join('|');
  const candidates = [
    {id:'candidate-a',name:'Candidate A',score:32,otherScore:26,badge:'Best demo score'},
    {id:'candidate-b',name:'Candidate B',score:45,otherScore:30,badge:'More evidence needed'},
    {id:'candidate-c',name:'Candidate C',score:57,otherScore:33,badge:'Eligibility review'}
  ];
  const fixture = {
    version:1, user:{name:'Yuna Sawant',initials:'YS',role:'Demo clinician'},
    context:{age:68,sex:'female',stratify:true},
    medicines:[{id:'amitriptyline',name:'Amitriptyline',dose:''},{id:'citalopram',name:'Citalopram',dose:''},{id:'medicine-c',name:'Medicine C',dose:''},{id:'medicine-d',name:'Medicine D',dose:''}],
    scores:{[key('amitriptyline','citalopram')]:82,[key('amitriptyline','medicine-c')]:34,[key('amitriptyline','medicine-d')]:null,[key('citalopram','medicine-c')]:21,[key('citalopram','medicine-d')]:47,[key('medicine-c','medicine-d')]:18},
    selectedPair:['amitriptyline','citalopram'],simulation:null
  };
  const provider = {getInitialCase:()=>clone(fixture),getUser:()=>clone(fixture.user),getCandidates:()=>clone(candidates)};
  function classifyScore(n){return n==null?'unknown':n>=70?'priority':n>=30?'review':'lower';}
  // Name cap is 250, not the older 60 — real PubChem/model vocabulary names
  // (IUPAC names for compounds with no common name) routinely run well past
  // 60 characters, and the "Add a medicine" search now feeds real vocabulary
  // names in here instead of short hand-typed ones.
  const MEDICINE_NAME_MAX = 250;
  function valid(s){return s?.version===1 && Array.isArray(s.medicines) && s.medicines.length<=12 && s.medicines.every(m=>typeof m.id==='string' && typeof m.name==='string' && m.name.length<=MEDICINE_NAME_MAX && typeof m.dose==='string') && new Set(s.medicines.map(m=>m.id)).size===s.medicines.length && s.context && Number.isInteger(s.context.age) && s.context.age>=0 && s.context.age<=120 && ['female','male','unknown'].includes(s.context.sex) && typeof s.context.stratify==='boolean' && s.scores && Object.values(s.scores).every(v=>v===null || Number.isFinite(v)&&v>=0&&v<=100) && Array.isArray(s.selectedPair);}
  function createStore(storage, source=provider){
    const storageKey='pharmagnn-demo-v1'; let state=source.getInitialCase(),restoreCandidate;
    try {const loaded=JSON.parse(storage?.getItem(storageKey)||'null');if(valid(loaded)){restoreCandidate=loaded.simulation?.candidate?.id;state=loaded;state.simulation=null;}}catch{}
    // Simulation is reconstructible and deliberately not restored from untrusted browser storage.
    function repair(){if(state.selectedPair.length!==2 || new Set(state.selectedPair).size!==2 || !state.selectedPair.every(id=>state.medicines.some(m=>m.id===id)))state.selectedPair=state.medicines.length>=2?state.medicines.slice(0,2).map(m=>m.id):[];}
    repair();
    const save=()=>{repair();try{storage?.setItem(storageKey,JSON.stringify(state));}catch{}return clone(state);};
    const score=(a,b,regimen=state)=>regimen.scores[key(a,b)]??null;
    const store = {
      getState:()=>clone(state),getUser:()=>source.getUser(),score,
      addMedicine(name,dose=''){
        name=String(name).trim();dose=String(dose).trim();
        if(!name||name.length>MEDICINE_NAME_MAX||dose.length>40)throw Error('Enter a medicine name (up to '+MEDICINE_NAME_MAX+' characters) and a dose up to 40 characters.');
        if(state.medicines.length>=12)throw Error('This demo supports up to 12 medicines.');
        if(state.medicines.some(m=>m.name.toLowerCase()===name.toLowerCase()))throw Error('This medicine is already in the regimen.');
        const known=source.getInitialCase().medicines.find(m=>m.name.toLowerCase()===name.toLowerCase());
        const med={id:known?.id||'custom-'+Date.now()+'-'+Math.random().toString(36).slice(2,7),name:known?.name||name,dose};
        state.medicines.push(med);state.simulation=null;save();return clone(med);
      },
      removeMedicine(id){state.medicines=state.medicines.filter(m=>m.id!==id);state.simulation=null;return save();},
      selectPair(a,b){if(a===b||![a,b].every(id=>state.medicines.some(m=>m.id===id)))throw Error('Select two medicines in this regimen.');state.selectedPair=[a,b];state.simulation=null;return save();},
      updateContext(context){if(!Number.isInteger(context.age)||context.age<0||context.age>120)throw Error('Enter a whole-number age between 0 and 120.');if(!['female','male','unknown'].includes(context.sex))throw Error('Choose a supported stratum.');state.context={age:context.age,sex:context.sex,stratify:!!context.stratify};state.simulation=null;return save();},
      hasFixture:()=>state.selectedPair.length===2&&key(...state.selectedPair)===key('amitriptyline','citalopram'),
      demographicEstimate(context=state.context){const supported=state.selectedPair.length===2&&key(...state.selectedPair)===key('amitriptyline','citalopram');if(!supported)return {baseline:null,score:null,range:'No cohort fixture for this pair'};if(!context.stratify)return {baseline:68,score:68,range:'Illustrative range 56–79'};if(context.age<65||context.age>74||context.sex==='unknown')return {baseline:68,score:null,range:'Insufficient evidence for this cohort'};return context.sex==='female'?{baseline:68,score:82,range:'Illustrative range 67–91'}:{baseline:68,score:74,range:'Illustrative range 60–86'};},
      getCandidates(){return state.selectedPair.length===2 && key(...state.selectedPair)===key('amitriptyline','citalopram')?source.getCandidates():[];},
      simulate(id){const candidate=this.getCandidates().find(c=>c.id===id);if(!candidate)throw Error('No supported candidate for this pair.');const original={medicines:clone(state.medicines),scores:clone(state.scores)};const proposed=clone(original);proposed.medicines=proposed.medicines.map(m=>m.id==='amitriptyline'?{id:candidate.id,name:candidate.name,dose:'Requires review'}:m);for(const med of proposed.medicines){if(med.id!==candidate.id)proposed.scores[key(candidate.id,med.id)]=med.id==='citalopram'?candidate.score:med.id==='medicine-c'?candidate.otherScore:null;}state.simulation={candidate,original,proposed};save();return clone(state.simulation);},
      applySimulation(){if(!state.simulation)throw Error('Choose and simulate a candidate first.');state.medicines=state.simulation.proposed.medicines;state.scores=state.simulation.proposed.scores;state.selectedPair=[state.simulation.candidate.id,'citalopram'];state.simulation=null;return save();},
      reset(){state=source.getInitialCase();return save();}
    };
    if(restoreCandidate){try{store.simulate(restoreCandidate);}catch{}}
    return store;
  }
  const api={createStore,classifyScore,provider};
  if(typeof module!=='undefined')module.exports=api;
  if(typeof window!=='undefined'){root.PharmaDemo=api;let storage;try{storage=window.localStorage;}catch{}root.PharmaStore=createStore(storage);}
})(globalThis);
