(function () {
  const substitutionData = {
    pageHeading: 'A considered alternative starts here.',
    pageSubhead: 'Compare candidates against the indication and the entire regimen.',

    replaceInfo: {
      label: 'REPLACE IN DRAFT',
      drugName: 'Amitriptyline',
      intentLabel: 'THERAPEUTIC INTENT',
      intentValue: 'Depression · demo scenario',
      tags: ['Preserve indication', 'Review contraindications'],
    },

    rankedNote: 'Ranked by simulated pairwise score',
    bannerText:
      'Candidates are hypothetical UI examples. Lower predicted scores do not establish clinical safety or interchangeability.',

    selectedId: 'a',
    candidates: [
      {
        id: 'a',
        rank: '01',
        name: 'Candidate A',
        subtitle: 'Hypothetical therapeutic alternative',
        badge: { label: 'Best demo score', kind: 'good' },
        score: 32,
        scoreMax: 100,
        delta: -50,
        detail: {
          'Indication match': 'Demo match',
          Contraindications: 'Not evaluated',
          'Dose equivalence': 'Requires review',
          'Regimen coverage': '6 pairwise checks',
        },
      },
      {
        id: 'b',
        rank: '02',
        name: 'Candidate B',
        subtitle: 'Hypothetical therapeutic alternative',
        badge: { label: 'More evidence needed', kind: 'warn' },
        score: 45,
        scoreMax: 100,
        delta: -37,
        detail: {
          'Indication match': 'Partial match',
          Contraindications: 'Not evaluated',
          'Dose equivalence': 'Not modeled',
          'Regimen coverage': '6 pairwise checks',
        },
      },
      {
        id: 'c',
        rank: '03',
        name: 'Candidate C',
        subtitle: 'Hypothetical therapeutic alternative',
        badge: { label: 'Eligibility review', kind: 'warn' },
        score: 57,
        scoreMax: 100,
        delta: -25,
        detail: {
          'Indication match': 'Demo match',
          Contraindications: 'Flag for review',
          'Dose equivalence': 'Requires review',
          'Regimen coverage': '6 pairwise checks',
        },
      },
    ],
    simulateLabel: 'Simulate this candidate',
    detailSubtitle: 'Review before simulating',
  };

  function selectedCandidate() {
    return substitutionData.candidates.find((c) => c.id === substitutionData.selectedId);
  }

  function renderHeading() {
    document.getElementById('pageHeading').textContent = substitutionData.pageHeading;
    document.getElementById('pageSubhead').textContent = substitutionData.pageSubhead;
  }

  function renderReplaceCard() {
    const info = substitutionData.replaceInfo;
    const tagsHtml = info.tags.map((t) => `<span class="pill pill-muted">${t}</span>`).join('');
    document.getElementById('replaceCard').innerHTML = `
      <div class="replace-block">
        <span class="context-label">${info.label}</span>
        <span class="replace-drug-name">${info.drugName}</span>
      </div>
      <div class="replace-block">
        <span class="context-label">${info.intentLabel}</span>
        <div class="field-box replace-intent-box">${info.intentValue}</div>
      </div>
      <div class="replace-tags">${tagsHtml}</div>
    `;
  }

  function renderComparisonHeading() {
    document.getElementById('rankedNote').textContent = substitutionData.rankedNote;
    document.getElementById('candidateBanner').textContent = substitutionData.bannerText;
  }

  function renderCandidateList() {
    const list = document.getElementById('candidateList');
    list.innerHTML = '';
    substitutionData.candidates.forEach((c) => {
      const li = document.createElement('li');
      li.className = 'candidate-row' + (c.id === substitutionData.selectedId ? ' selected' : '');
      li.dataset.id = c.id;
      li.innerHTML = `
        <span class="candidate-rank">${c.rank}</span>
        <div class="candidate-info">
          <span class="candidate-name">${c.name}</span>
          <span class="candidate-subtitle">${c.subtitle}</span>
          <span class="candidate-badge badge-${c.badge.kind}">${c.badge.label}</span>
        </div>
        <div class="candidate-score-block">
          <span class="candidate-score">${c.score}</span>
          <span class="candidate-score-max">/ ${c.scoreMax}</span>
        </div>
        <div class="candidate-delta-block">
          <span class="candidate-delta">${c.delta}</span>
          <span class="candidate-delta-label">points</span>
        </div>
      `;
      li.addEventListener('click', () => {
        substitutionData.selectedId = c.id;
        renderCandidateList();
        renderDetail();
      });
      list.appendChild(li);
    });
  }

  function renderDetail() {
    const c = selectedCandidate();
    const rows = Object.entries(c.detail)
      .map(
        ([term, value]) => `
        <div class="detail-row">
          <span class="detail-term">${term}</span>
          <span class="detail-value">${value}</span>
        </div>`
      )
      .join('');

    document.getElementById('candidateDetailCard').innerHTML = `
      <h2 class="candidate-detail-name">${c.name}</h2>
      <p class="ws-card-note">${substitutionData.detailSubtitle}</p>
      <div class="detail-rows">${rows}</div>
      <button class="btn btn-primary ws-btn-block" id="simulateBtn" type="button">${substitutionData.simulateLabel}</button>
    `;
  }

  renderWorkspaceShell('Substitution engine');
  renderHeading();
  renderReplaceCard();
  renderComparisonHeading();
  renderCandidateList();
  renderDetail();
})();
