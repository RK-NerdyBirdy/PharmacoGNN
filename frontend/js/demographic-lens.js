(function () {
  const lensData = {
    pageHeading: 'The same regimen. More context.',
    pageSubhead: 'Compare estimates without hiding uncertainty or missing evidence.',

    contextSubtitle: 'Demo case 004',
    age: '68 years',
    strata: [
      { key: 'female', label: 'Female', selected: true },
      { key: 'male', label: 'Male', selected: false },
      { key: 'unknown', label: 'Unknown / not recorded', selected: false },
    ],
    stratumNote: "Uses the model's dataset definition. Gender identity is not inferred.",

    toggleLabel: 'Compare stratified estimate',
    toggleOn: true,
    toggleNote: 'Changes affect this demo comparison. No universal sex-based multiplier is implied by these estimates.',
    updateLabel: 'Update comparison',

    comparisonSubtitle: 'Amitriptyline × citalopram · Synthetic score, not probability',
    estimates: {
      unstratified: { label: 'Unstratified', score: 68, range: 'Illustrative range 56–79' },
      stratified: { label: 'Female · age 65–74', score: 82, range: 'Illustrative range 67–91' },
    },
    estimateFootnote: 'Uncertainty ranges overlap; the difference is not proof of a subgroup effect.',

    coverageSubtitle: 'Understand what supports the comparison.',
    coverage: [
      { term: 'Population', detail: 'Female · 65–74 years' },
      { term: 'Coverage', detail: 'Limited subgroup representation' },
      { term: 'Calibration', detail: 'Not evaluated in this prototype' },
      { term: 'When unsupported', detail: 'Show insufficient evidence; retain baseline context' },
    ],
  };

  function renderHeading() {
    document.getElementById('pageHeading').textContent = lensData.pageHeading;
    document.getElementById('pageSubhead').textContent = lensData.pageSubhead;
  }

  function renderContextCard() {
    document.getElementById('contextSubtitle').textContent = lensData.contextSubtitle;
    document.getElementById('ageField').textContent = lensData.age;
    document.getElementById('stratumNote').textContent = lensData.stratumNote;
    document.getElementById('toggleLabel').textContent = lensData.toggleLabel;
    document.getElementById('toggleNote').textContent = lensData.toggleNote;
    document.getElementById('updateComparisonBtn').textContent = lensData.updateLabel;

    const list = document.getElementById('stratumList');
    lensData.strata.forEach((s) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'stratum-option' + (s.selected ? ' selected' : '');
      row.dataset.key = s.key;
      row.innerHTML = `<span class="stratum-dot"></span><span>${s.label}</span>`;
      row.addEventListener('click', () => {
        lensData.strata.forEach((opt) => (opt.selected = opt.key === s.key));
        renderStratumList();
      });
      list.appendChild(row);
    });
  }

  function renderStratumList() {
    document.querySelectorAll('.stratum-option').forEach((el) => {
      el.classList.toggle('selected', el.dataset.key === lensData.strata.find((s) => s.selected).key);
    });
  }

  function renderToggle() {
    const btn = document.getElementById('stratifyToggle');
    btn.classList.toggle('on', lensData.toggleOn);
    btn.setAttribute('aria-checked', String(lensData.toggleOn));
  }

  function renderEstimates() {
    document.getElementById('comparisonSubtitle').textContent = lensData.comparisonSubtitle;
    document.getElementById('estimateFootnote').textContent = lensData.estimateFootnote;

    const { unstratified, stratified } = lensData.estimates;
    const delta = stratified.score - unstratified.score;
    const row = document.getElementById('estimateRow');
    row.innerHTML = `
      <div class="estimate-box">
        <span class="estimate-tag">${unstratified.label.toUpperCase()}</span>
        <div class="estimate-score">${unstratified.score}</div>
        <p class="estimate-range">${unstratified.range}</p>
      </div>
      <div class="estimate-box highlighted">
        <span class="estimate-tag">${stratified.label.toUpperCase()}</span>
        <div class="estimate-score-row">
          <div class="estimate-score">${stratified.score}</div>
          <span class="pill pill-muted delta-pill">${delta >= 0 ? '+' : ''}${delta} points</span>
        </div>
        <p class="estimate-range">${stratified.range}</p>
      </div>
    `;
  }

  function renderCoverage() {
    document.getElementById('coverageSubtitle').textContent = lensData.coverageSubtitle;
    const list = document.getElementById('coverageList');
    lensData.coverage.forEach((row) => {
      const dt = document.createElement('dt');
      dt.textContent = row.term;
      const dd = document.createElement('dd');
      dd.textContent = row.detail;
      list.appendChild(dt);
      list.appendChild(dd);
    });
  }

  renderWorkspaceShell('Demographic lens');
  renderHeading();
  renderContextCard();
  renderToggle();
  renderEstimates();
  renderCoverage();

  document.getElementById('stratifyToggle').addEventListener('click', () => {
    lensData.toggleOn = !lensData.toggleOn;
    renderToggle();
  });
})();
