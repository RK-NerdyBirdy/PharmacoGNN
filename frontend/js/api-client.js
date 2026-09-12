(function(root){
const TOKEN='pharmagnn_token',CAPABILITIES=Object.freeze({patientList:true,invitations:true,activation:false,reports:true,transfers:true,careTeam:true});
function decodeJwt(token){try{const s=String(token).split('.')[1].replace(/-/g,'+').replace(/_/g,'/');return JSON.parse(typeof atob==='function'?atob(s):Buffer.from(s,'base64').toString('utf8'))}catch{return null}}
function createApiClient(o={}){
 const fetcher=o.fetch||root.fetch?.bind(root),storage=o.storage||root.localStorage,base=o.apiBase||root.PHARMAGNN_API_BASE||'http://localhost:8000';let timer=null;
 const fail=(message,more={})=>Object.assign(new Error(message),more);
 const getToken=()=>{try{return storage?.getItem(TOKEN)||null}catch{return null}};
 const clearToken=()=>{if(timer!==null&&root.clearTimeout)root.clearTimeout(timer);timer=null;try{storage?.removeItem(TOKEN)}catch{}};
 const getSession=()=>{const token=getToken(),claims=decodeJwt(token);return claims?{token,role:claims.role,userId:claims.sub,expiresAt:claims.exp}:null};
 const refresh=async()=>{const data=await request('/api/v1/auth/refresh',{method:'POST'});setToken(data.access_token);return data};
 const setToken=token=>{try{storage?.setItem(TOKEN,token)}catch{};if(timer!==null&&root.clearTimeout)root.clearTimeout(timer);const s=getSession();if(s?.expiresAt&&root.setTimeout)timer=root.setTimeout(()=>refresh().catch(()=>{}),Math.max(0,s.expiresAt*1000-Date.now()-300000))};
 const unavailable=capability=>Promise.reject(fail('This backend capability is not available yet. No clinical data has been shown.',{code:'CAPABILITY_UNAVAILABLE',capability}));
 async function request(path,{method='GET',body,auth=true,form=false,binary=false}={}){
  if(!fetcher)throw fail('Browser networking is unavailable.',{code:'NETWORK_UNAVAILABLE'});const headers={};if(auth&&getToken())headers.Authorization='Bearer '+getToken();let data;
  if(body!==undefined){data=form?new URLSearchParams(body):JSON.stringify(body);if(!form)headers['Content-Type']='application/json'}
  let res;try{res=await fetcher(base+path,{method,headers,body:data})}catch{throw fail('Could not reach the API at '+base+'. Is the FastAPI backend running?',{code:'NETWORK_ERROR'})}
  if(res.status===401&&auth){clearToken();throw fail('Session expired. Please log in again.',{code:'SESSION_EXPIRED',status:401})}
  if(!res.ok){let p;try{p=await res.json()}catch{}
   if(res.status===429)throw fail('Too many requests. Please wait a moment and try again.',{code:'RATE_LIMITED',status:429,retryAfter:res.headers.get('Retry-After')});
   if(res.status===404)throw fail('Not found, or you do not have access.',{code:'NOT_FOUND_OR_NO_ACCESS',status:404});
   if(res.status===422){const m=Array.isArray(p?.detail)?p.detail.map(x=>x.msg).filter(Boolean).join('; '):typeof p?.detail==='string'?p.detail:'Please correct the highlighted fields.';throw fail(m,{code:'VALIDATION_ERROR',status:422,details:p?.detail})}
   // Transfer OTP endpoints use a non-standard detail shape for a wrong code:
   // {"detail":{"message":"Incorrect code","attempts_remaining":N}} -- surface
   // both the message and the count rather than falling through to a generic
   // "Request failed (400)" that would lose the remaining-attempts info.
   if(res.status===400&&p?.detail&&typeof p.detail==='object')throw fail(p.detail.message||'Request failed (400)',{code:'API_ERROR',status:400,attemptsRemaining:p.detail.attempts_remaining});
   if(res.status===410)throw fail(typeof p?.detail==='string'?p.detail:'This has expired.',{code:'GONE',status:410});
   if(res.status===423)throw fail(typeof p?.detail==='string'?p.detail:'This is locked.',{code:'LOCKED',status:423});
   if(res.status===409)throw fail(typeof p?.detail==='string'?p.detail:'This conflicts with an existing record.',{code:'CONFLICT',status:409});
   throw fail(typeof p?.detail==='string'?p.detail:p?.error||'Request failed ('+res.status+')',{code:'API_ERROR',status:res.status})}
  if(binary)return res.blob();
  return res.status===204?null:res.json()
 }
 const cid=x=>/^CID\d{9}$/.test(String(x))?String(x):'CID'+String(x||'').replace(/^CID/i,'').padStart(9,'0'),patient=id=>'/api/v1/patients/'+encodeURIComponent(id);
 const post=(path,body)=>request(path,{method:'POST',body}),patch=(path,body)=>request(path,{method:'PATCH',body});
 return {request,getToken,clearToken,logout:clearToken,setToken,getSession,getCapability:n=>Boolean(CAPABILITIES[n]),getErrorMessage:e=>e?.message||'Something went wrong. Please try again.',isAuthenticated:()=>Boolean(getToken()),toModelCid:cid,
  register:(email,password,role)=>post('/api/v1/auth/register',{email,password,role}),async login(email,password){const d=await request('/api/v1/auth/login',{method:'POST',auth:false,body:{email,password}});setToken(d.access_token);return d},refresh,getHealth:()=>request('/health',{auth:false}),
  getMyProfile:()=>request('/api/v1/patients/me'),createMyProfile:x=>post('/api/v1/patients/me',x),getPatient:id=>request(patient(id)),updatePatient:(id,x)=>patch(patient(id),x),getPatientConditions:id=>request(patient(id)+'/conditions'),addCondition:(id,x)=>post(patient(id)+'/conditions',x),updateCondition:(id,c,x)=>patch(patient(id)+'/conditions/'+encodeURIComponent(c),x),getPatientRegimens:(id,active=false)=>request(patient(id)+'/regimens'+(active?'?active_only=true':'')),addRegimen:(id,x)=>post(patient(id)+'/regimens',x),updateRegimen:(id,r,x)=>patch(patient(id)+'/regimens/'+encodeURIComponent(r),x),
  predictPairwise:x=>post('/api/v1/predict/pairwise',x),predictRegimen:x=>post('/api/v1/predict/regimen',x),substitute:x=>post('/api/v1/predict/substitute',x),explainInteraction:x=>post('/api/v1/explain/interaction',x),searchDrugs(q,limit=20,offset=0){const p=new URLSearchParams({limit:String(limit),offset:String(offset)});if(q)p.set('q',q);return request('/api/v1/vocab/drugs?'+p)},getDrugByCid:x=>request('/api/v1/vocab/drugs/'+encodeURIComponent(x)),listAdverseEffects:()=>request('/api/v1/vocab/adverse-effects'),
  getPatientList(limit=50,offset=0){return request('/api/v1/patients?limit='+limit+'&offset='+offset)},
  createPatient:x=>post('/api/v1/patients',x),
  resendInvite:id=>post(patient(id)+'/invite/resend'),
  getPatientAccess:id=>request(patient(id)+'/access'),
  importPrescription:(id,x)=>post(patient(id)+'/prescriptions',x),
  validateActivation:()=>unavailable('activation'),activateAccount:()=>unavailable('activation'),
  getReports(patientId,limit=50,offset=0){return request(patient(patientId)+'/reports?limit='+limit+'&offset='+offset)},
  createReport:patientId=>post(patient(patientId)+'/reports'),
  getReport:id=>request('/api/v1/reports/'+encodeURIComponent(id)),
  getReportPdfBlob:id=>request('/api/v1/reports/'+encodeURIComponent(id)+'/pdf',{binary:true}),
  getReportQrBlob:id=>request('/api/v1/reports/'+encodeURIComponent(id)+'/qr',{binary:true}),
  deleteReport:id=>request('/api/v1/reports/'+encodeURIComponent(id),{method:'DELETE'}),
  createTransfer:(patientId,x)=>post(patient(patientId)+'/transfers',x),
  getTransfers(limit=50,offset=0){return request('/api/v1/transfers?limit='+limit+'&offset='+offset)},
  getTransfer:id=>request('/api/v1/transfers/'+encodeURIComponent(id)),
  consentTransfer:(id,otp)=>post('/api/v1/transfers/'+encodeURIComponent(id)+'/consent',{otp}),
  declineTransfer:id=>post('/api/v1/transfers/'+encodeURIComponent(id)+'/decline'),
  cancelTransfer:id=>post('/api/v1/transfers/'+encodeURIComponent(id)+'/cancel'),
  resendTransferOtp:id=>post('/api/v1/transfers/'+encodeURIComponent(id)+'/resend-otp'),
  getCareTeam:id=>request(patient(id)+'/access')}
}
const client=createApiClient();if(root.window===root)root.ApiClient=client;if(typeof module!=='undefined'&&module.exports)module.exports={createApiClient,decodeJwt,CAPABILITIES}
})(typeof window!=='undefined'?window:globalThis);
