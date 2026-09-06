// Loaded first on every workspace page. Redirects to login if there's no
// stored token -- a UX gate for this demo, not a security boundary (the
// real enforcement is the backend's own 401 on every protected endpoint).
(function () {
  if (!window.ApiClient || !ApiClient.isAuthenticated()) {
    const next = encodeURIComponent(location.pathname.split('/').pop());
    location.href = 'login.html?next=' + next;
  }
})();
