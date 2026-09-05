// Shared workspace chrome: sidebar nav, topbar, sidebar callout, footer.
// Rendered the same way on every workspace page from one config object,
// so nothing about the shell is hardcoded per-page.
const WORKSPACE_SHELL = {
  user: { initials: 'YS' },

  nav: [
    { icon: '▦', label: 'Regimen overview', href: 'workspace.html' },
    { icon: '◎', label: 'Demographic lens', href: 'demographic-lens.html' },
    { icon: '⌘', label: 'Pathway inspector', href: 'pathway-inspector.html' },
    { icon: '⇄', label: 'Substitution engine', href: 'substitution-engine.html' },
    { icon: '☰', label: 'Review & export', href: null },
  ],

  sidebarCallout: {
    title: 'A clearer picture.',
    text: 'Every pair. Every pathway. One considered decision.',
  },

  footer: {
    left: 'Research prototype • Synthetic scores • Clinician review required',
    right: 'Model demo—v0.1',
  },
};

function renderWorkspaceShell(activeLabel) {
  const nav = document.getElementById('sidebarNav');
  WORKSPACE_SHELL.nav.forEach((item) => {
    const isActive = item.label === activeLabel;
    const el = document.createElement(item.href ? 'a' : 'button');
    el.className = 'sidebar-nav-item' + (isActive ? ' active' : '');
    if (item.href) {
      el.href = item.href;
    } else {
      el.type = 'button';
      el.disabled = true;
    }
    el.innerHTML = `<span class="sidebar-nav-icon">${item.icon}</span><span>${item.label}</span>`;
    nav.appendChild(el);
  });

  document.getElementById('userAvatar').textContent = WORKSPACE_SHELL.user.initials;

  document.querySelector('.sidebar-callout-title').textContent = WORKSPACE_SHELL.sidebarCallout.title;
  document.querySelector('.sidebar-callout-text').textContent = WORKSPACE_SHELL.sidebarCallout.text;

  document.getElementById('footerLeft').textContent = WORKSPACE_SHELL.footer.left;
  document.getElementById('footerRight').textContent = WORKSPACE_SHELL.footer.right;
}
