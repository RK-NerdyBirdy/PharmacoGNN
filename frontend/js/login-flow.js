(function (root) {
  function clinicianRegistration(email, password) {
    return { email: String(email).trim(), password, role: 'CLINICIAN' };
  }

  if (root.window === root) root.LoginFlow = { clinicianRegistration };
  if (typeof module !== 'undefined' && module.exports) module.exports = { clinicianRegistration };
})(typeof window !== 'undefined' ? window : globalThis);
