(function(root){
function createRegimenModel(regimens){
 return (Array.isArray(regimens)?regimens:[]).filter(item=>!item.end_date).map(item=>({id:item.id,cid:item.pubchem_cid,modelCid:'CID'+String(item.pubchem_cid).padStart(9,'0'),name:item.drug_name,dosage:item.dosage||null}));
}
function createPredictionModel(regimens,prediction){
 const medicines=createRegimenModel(regimens),matrix=Array.isArray(prediction?.interaction_matrix)?prediction.interaction_matrix:[];
 return {medicines,cells:medicines.map((_,row)=>medicines.map((__,column)=>({score:row===column?null:Number.isFinite(matrix[row]?.[column])?matrix[row][column]:null}))),toxicityIndex:Number.isFinite(prediction?.regimen_toxicity_index)?prediction.regimen_toxicity_index:null,pairwiseFlags:Array.isArray(prediction?.pairwise_flags)?prediction.pairwise_flags:[]};
}
function safetyNotices(payload={}){
 const notices=[];
 if(payload.degraded_mode)notices.push({level:'warning',message:'Model output is degraded or unverified. Use clinical judgment and do not rely on this result alone.'});
 if(payload.disclaimer)notices.push({level:'warning',message:payload.disclaimer});
 if(payload.model_status?.warning)notices.push({level:'warning',message:payload.model_status.warning});
 if(Array.isArray(payload.unresolved_drugs)&&payload.unresolved_drugs.length)notices.push({level:'warning',message:'Some drugs could not be resolved and are excluded from interaction analysis.'});
 return notices;
}
const api={createRegimenModel,createPredictionModel,safetyNotices};
if(root.window===root)root.ClinicalState=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
