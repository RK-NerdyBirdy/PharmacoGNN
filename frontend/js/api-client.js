// Thin fetch wrapper for the real FastAPI backend. Nothing here changes any
// backend behavior -- it just calls the endpoints as they're documented in
// API_REFERENCE.md. Every method throws a plain Error with a readable message
// on failure so callers can show it directly.
(function () {
  const API_BASE = window.PHARMAGNN_API_BASE || 'http://localhost:8000';
  const TOKEN_KEY = 'pharmagnn_token';

  // The model's vocabulary (backend/weights/drug2idx.json) keys drugs by
  // zero-padded "CID000002160", not the plain PubChem numeric CID (2160) --
  // gnn_engine does an exact dict lookup with no normalization, so sending
  // the bare number 404s every time even for a drug the model genuinely
  // knows. This is the one conversion point every caller should go through.
  function toModelCid(pubchemCid) {
    return 'CID' + String(pubchemCid).padStart(9, '0');
  }

  function getToken() {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  }
  function setToken(token) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {}
  }
  function clearToken() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {}
  }

  async function request(path, { method = 'GET', body, auth = true } = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (auth) {
      const token = getToken();
      if (token) headers.Authorization = 'Bearer ' + token;
    }

    let res;
    try {
      res = await fetch(API_BASE + path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new Error(`Could not reach the API at ${API_BASE}. Is the FastAPI backend running?`);
    }

    if (res.status === 401 && auth) {
      // Only for requests that carried a token — a 401 on login/register
      // itself (auth:false) means wrong credentials, not an expired
      // session, and should surface the backend's real detail message below.
      clearToken();
      throw new Error('Session expired. Please log in again.');
    }
    if (!res.ok) {
      let detail = '';
      try {
        const data = await res.json();
        detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
      } catch {}
      throw new Error(detail || `Request failed (${res.status})`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  const ApiClient = {
    getToken,
    isAuthenticated: () => Boolean(getToken()),
    logout: clearToken,
    toModelCid,

    async register(email, password, role) {
      return request('/api/v1/auth/register', { method: 'POST', auth: false, body: { email, password, role } });
    },
    async login(email, password) {
      const data = await request('/api/v1/auth/login', { method: 'POST', auth: false, body: { email, password } });
      setToken(data.access_token);
      return data;
    },
    async refresh() {
      const data = await request('/api/v1/auth/refresh', { method: 'POST' });
      setToken(data.access_token);
      return data;
    },

    getMyProfile: () => request('/api/v1/patients/me'),
    createMyProfile: (payload) => request('/api/v1/patients/me', { method: 'POST', body: payload }),
    updateProfile: (patientId, payload) => request(`/api/v1/patients/${patientId}`, { method: 'PATCH', body: payload }),
    getPatientConditions: (patientId) => request(`/api/v1/patients/${patientId}/conditions`),
    getPatientRegimens: (patientId) => request(`/api/v1/patients/${patientId}/regimens`),

    predictPairwise: (payload) => request('/api/v1/predict/pairwise', { method: 'POST', body: payload }),
    predictRegimen: (payload) => request('/api/v1/predict/regimen', { method: 'POST', body: payload }),
    substitute: (payload) => request('/api/v1/predict/substitute', { method: 'POST', body: payload }),
    explainInteraction: (payload) => request('/api/v1/explain/interaction', { method: 'POST', body: payload }),

    searchDrugs(q, limit = 20, offset = 0) {
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      params.set('limit', limit);
      params.set('offset', offset);
      return request('/api/v1/vocab/drugs?' + params.toString());
    },
    getDrugByCid: (cid) => request(`/api/v1/vocab/drugs/${cid}`),
    listAdverseEffects: () => request('/api/v1/vocab/adverse-effects'),
  };

  window.ApiClient = ApiClient;
})();
