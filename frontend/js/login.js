(function () {
  function nextPage() {
    return new URLSearchParams(location.search).get('next') || 'workspace.html';
  }

  // Already signed in — skip straight through.
  if (ApiClient.isAuthenticated()) {
    location.href = nextPage();
    return;
  }

  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const showRegister = document.getElementById('showRegister');
  const showLogin = document.getElementById('showLogin');
  const loginError = document.getElementById('loginError');
  const registerError = document.getElementById('registerError');

  showRegister.addEventListener('click', () => {
    loginForm.hidden = true;
    registerForm.hidden = false;
    showRegister.hidden = true;
    showLogin.hidden = false;
  });
  showLogin.addEventListener('click', () => {
    registerForm.hidden = true;
    loginForm.hidden = false;
    showLogin.hidden = true;
    showRegister.hidden = false;
  });

  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    loginError.textContent = '';
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;
    try {
      await ApiClient.login(email, password);
      location.href = nextPage();
    } catch (err) {
      loginError.textContent = err.message || 'Could not sign in.';
    }
  });

  registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    registerError.textContent = '';
    const email = document.getElementById('registerEmail').value.trim();
    const password = document.getElementById('registerPassword').value;
    const role = document.getElementById('registerRole').value;
    try {
      await ApiClient.register(email, password, role);
      await ApiClient.login(email, password);
      location.href = nextPage();
    } catch (err) {
      registerError.textContent = err.message || 'Could not create account.';
    }
  });
})();
