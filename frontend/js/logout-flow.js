(function (root) {
  function logout(apiClient, location) {
    apiClient.logout();
    location.href = 'login.html';
  }
  if (root.window === root) root.LogoutFlow = { logout };
  if (typeof module !== 'undefined' && module.exports) module.exports = { logout };
})(typeof window !== 'undefined' ? window : globalThis);
