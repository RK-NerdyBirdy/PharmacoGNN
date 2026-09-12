renderWorkspaceShell('Settings');

const form = document.getElementById('settingsForm');
const renderOptions = () => {
  const current = PharmaPreferences.get();
  const languageOptions = document.getElementById('languageOptions');
  const themeOptions = document.getElementById('themeOptions');
  languageOptions.innerHTML = PharmaPreferences.languages().map(({ id, label }) => '<label class="settings-choice"><input type="radio" name="language" value="'+id+'" '+(current.language===id?'checked':'')+'><span>'+label+'</span><i aria-hidden="true">'+(current.language===id?PharmaPreferences.t('settings.active'):'')+'</i></label>').join('');
  themeOptions.innerHTML = '<label class="dark-mode-choice"><span><strong>'+PharmaPreferences.t('theme.dark')+'</strong><small>'+PharmaPreferences.t('settings.appearanceHint')+'</small></span><input class="dark-mode-toggle" type="checkbox" name="darkMode" '+(current.theme==='dark'?'checked':'')+'><span class="dark-mode-track" aria-hidden="true"><i></i></span></label>';
};
renderOptions();
form.addEventListener('submit', event => {
  event.preventDefault();
  const data = new FormData(form);
  PharmaPreferences.save({ language: data.get('language'), theme: data.get('darkMode') === 'on' ? 'dark' : 'pink' });
  PharmaPreferences.apply(document);
  PharmaPreferences.translateDocument(document);
  renderOptions();
  UI.announce(PharmaPreferences.t('shell.statusSaved'));
});
