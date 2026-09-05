(function () {
  // All copy and numbers for this screen live here, in one place, clearly
  // marked as demo/synthetic data — nothing is hardcoded into the markup.
  // A real integration would replace this object with a fetch() to the API.
  const caseData = {
    pageHeading: 'One regimen. A clearer picture.',
    pageSubhead: 'Review the priority pairs, then explore what might change.',

    patientContext: {
      caseLabel: 'DEMO CASE 004',
      title: 'Patient context',
      tags: ['Age 68', 'Female stratum'],
      meta: '4 medicines · 6 unique pairs',
      editLabel: 'Edit context',
    },

    medicines: [
      { letter: 'A', name: 'Amitriptyline', detail: 'Dose not entered' },
      { letter: 'B', name: 'Citalopram', detail: 'Dose not entered' },
      { letter: 'C', name: 'Medicine C', detail: 'Demo placeholder' },
      { letter: 'D', name: 'Medicine D', detail: 'Demo placeholder' },
    ],
    medicinesNote: 'All values in this case are illustrative.',
    addMedicineLabel: '+ Add a medicine',
    medicinesFootnote: 'Add dose and indication for a more complete review.',

    matrixNote: 'Select a pair to inspect its model evidence.',
    // symmetric pairwise scores keyed by "LETTER-LETTER"; null = not modeled yet
    matrixScores: {
      'A-B': 82, 'A-C': 34, 'A-D': null,
      'B-C': 21, 'B-D': 47,
      'C-D': 18,
    },
    matrixThresholds: { priority: 70, review: 20 },
    matrixLegend: [
      { key: 'priority', label: 'Priority' },
      { key: 'review', label: 'Review' },
      { key: 'lower', label: 'Lower' },
      { key: 'unknown', label: 'Unknown' },
    ],
    matrixFootnote: 'Pairwise estimates do not capture all multi-drug effects.',

    selectedPair: {
      letters: ['A', 'B'],
      priorityLabel: 'HIGH PRIORITY',
      score: 82,
      scoreMax: 100,
      caption: 'Synthetic interaction score',
      description: 'Amitriptyline + citalopram. Inspect associated cardiac and serotonergic pathways.',
      ctaLabel: 'Inspect pathway',
    },

    exploreChange: {
      title: 'Explore a change',
      text: 'Compare hypothetical candidates and their effects across the whole pairwise matrix.',
      ctaLabel: 'Find alternatives',
    },
  };

  function medicineByLetter(letter) {
    return caseData.medicines.find((m) => m.letter === letter);
  }

  function classifyScore(value) {
    if (value === null || value === undefined) return 'unknown';
    if (value >= caseData.matrixThresholds.priority) return 'priority';
    if (value >= caseData.matrixThresholds.review) return 'review';
    return 'lower';
  }

  function pairKey(a, b) {
    return [a, b].sort().join('-');
  }

  function renderHeading() {
    document.getElementById('pageHeading').textContent = caseData.pageHeading;
    document.getElementById('pageSubhead').textContent = caseData.pageSubhead;
  }

  function renderContextBar() {
    const bar = document.getElementById('contextBar');
    const ctx = caseData.patientContext;
    const tagsHtml = ctx.tags.map((t) => `<span class="pill pill-muted">${t}</span>`).join('');
    bar.innerHTML = `
      <div>
        <span class="context-label">${ctx.caseLabel}</span>
        <span class="context-title">${ctx.title}</span>
      </div>
      ${tagsHtml}
      <span class="context-meta">${ctx.meta}</span>
      <button class="btn btn-edit" type="button">${ctx.editLabel}</button>
    `;
  }

  function renderMedicines() {
    document.getElementById('medicinesNote').textContent = caseData.medicinesNote;
    document.getElementById('addMedicineBtn').textContent = caseData.addMedicineLabel;
    document.getElementById('medicinesFootnote').textContent = caseData.medicinesFootnote;

    const list = document.getElementById('medicineList');
    caseData.medicines.forEach((med) => {
      const li = document.createElement('li');
      li.className = 'medicine-item';
      li.innerHTML = `
        <span class="medicine-badge">${med.letter}</span>
        <span>
          <span class="medicine-name">${med.name}</span><br />
          <span class="medicine-detail">${med.detail}</span>
        </span>
        <button class="medicine-remove" type="button" aria-label="Remove ${med.name}">&times;</button>
      `;
      list.appendChild(li);
    });
  }

  function renderMatrix() {
    document.getElementById('matrixNote').textContent = caseData.matrixNote;
    document.getElementById('matrixFootnote').textContent = caseData.matrixFootnote;

    const letters = caseData.medicines.map((m) => m.letter);
    const table = document.getElementById('interactionMatrix');

    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    headRow.appendChild(document.createElement('th'));
    letters.forEach((l) => {
      const th = document.createElement('th');
      th.textContent = l;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    letters.forEach((rowLetter) => {
      const tr = document.createElement('tr');
      const rowHead = document.createElement('th');
      rowHead.textContent = rowLetter;
      tr.appendChild(rowHead);

      letters.forEach((colLetter) => {
        const td = document.createElement('td');
        if (rowLetter === colLetter) {
          td.textContent = '—';
          td.className = 'cell-diagonal';
        } else {
          const value = caseData.matrixScores[pairKey(rowLetter, colLetter)];
          const cls = classifyScore(value);
          td.textContent = value === null || value === undefined ? '?' : value;
          td.className = `cell-${cls}`;
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    document.getElementById('matrixLegendLabels').innerHTML = caseData.medicines
      .map((m) => `${m.letter} ${m.name}`)
      .join(' &middot; ');

    const legend = document.getElementById('matrixLegend');
    caseData.matrixLegend.forEach((item) => {
      const chip = document.createElement('span');
      chip.className = `legend-chip legend-${item.key}`;
      chip.textContent = item.label;
      legend.appendChild(chip);
    });
  }

  function renderReviewCard() {
    const pair = caseData.selectedPair;
    const [a, b] = pair.letters;
    document.getElementById('reviewNote').textContent = `Selected pair ${a} × ${b}`;
    document.getElementById('priorityPill').textContent = pair.priorityLabel;
    document.getElementById('scoreValue').textContent = pair.score;
    document.getElementById('scoreMax').textContent = `/ ${pair.scoreMax}`;
    document.getElementById('scoreCaption').textContent = pair.caption;
    document.getElementById('reviewDescription').textContent = pair.description;
    document.getElementById('inspectPathwayBtn').textContent = pair.ctaLabel;
  }

  function renderExploreCard() {
    const ex = caseData.exploreChange;
    document.getElementById('exploreTitle').textContent = ex.title;
    document.getElementById('exploreText').textContent = ex.text;
    document.getElementById('findAlternativesBtn').textContent = ex.ctaLabel;
  }

  renderWorkspaceShell('Regimen overview');
  renderHeading();
  renderContextBar();
  renderMedicines();
  renderMatrix();
  renderReviewCard();
  renderExploreCard();

  // clicking a matrix cell loads that pair into the "Review first" card
  document.getElementById('interactionMatrix').addEventListener('click', (e) => {
    const td = e.target.closest('td');
    if (!td || td.classList.contains('cell-diagonal')) return;
    const cells = Array.from(td.parentElement.children);
    const colIndex = cells.indexOf(td);
    const letters = caseData.medicines.map((m) => m.letter);
    const rowLetter = td.parentElement.firstElementChild.textContent;
    const colLetter = letters[colIndex - 1];
    const value = caseData.matrixScores[pairKey(rowLetter, colLetter)];

    caseData.selectedPair = {
      letters: [rowLetter, colLetter],
      priorityLabel:
        classifyScore(value) === 'priority'
          ? 'HIGH PRIORITY'
          : classifyScore(value) === 'review'
          ? 'REVIEW'
          : classifyScore(value) === 'lower'
          ? 'LOWER RISK'
          : 'NOT MODELED',
      score: value === null || value === undefined ? '—' : value,
      scoreMax: 100,
      caption: 'Synthetic interaction score',
      description: `${medicineByLetter(rowLetter).name} + ${medicineByLetter(colLetter).name}. Inspect associated pathways.`,
      ctaLabel: 'Inspect pathway',
    };
    renderReviewCard();
  });

  document.getElementById('inspectPathwayBtn').addEventListener('click', () => {
    window.location.href = 'pathway-inspector.html';
  });
})();
