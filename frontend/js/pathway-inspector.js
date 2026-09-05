(function () {
  const inspectorData = {
    pageHeading: 'Amitriptyline × citalopram',
    pageSubhead: 'Score 82 / 100',

    pair: { label: 'Amitriptyline × citalopram', score: 82, scoreMax: 100 },
    findAlternativesLabel: 'Find alternatives →',
    pathwayFootnote: 'Select a node to inspect its source and limitations.',
    evidenceButtonLabel: 'View evidence details',
    nodePillLabel: 'Evidence inspection',

    edgeLegend: [
      { kind: 'curated', label: 'Curated association' },
      { kind: 'model', label: 'Model-associated edge' },
    ],

    nodeSubtitleByType: {
      DRUG: 'Selected drug node',
      PROTEIN: 'Selected protein node',
      'MODEL CONTEXT': 'Selected model-context node',
      'PREDICTED ASSOCIATION': 'Selected predicted-outcome node',
    },

    pathways: {
      cardiac: {
        label: 'Cardiac',
        subtitle: 'Illustrative subgraph · Cardiac pathway selected',
        selectedNodeId: 'kcnh2',
        nodes: [
          { id: 'amitriptyline', label: 'Amitriptyline', type: 'DRUG', x: 90, y: 55 },
          { id: 'citalopram', label: 'Citalopram', type: 'DRUG', x: 500, y: 55 },
          { id: 'kcnh2', label: 'KCNH2 / hERG', type: 'PROTEIN', x: 140, y: 175 },
          { id: 'assoc', label: 'Associated node', type: 'MODEL CONTEXT', x: 450, y: 175 },
          { id: 'outcome', label: 'QT-related outcome', type: 'PREDICTED ASSOCIATION', x: 295, y: 265 },
        ],
        edges: [
          { from: 'amitriptyline', to: 'kcnh2', kind: 'curated' },
          { from: 'citalopram', to: 'assoc', kind: 'curated' },
          { from: 'kcnh2', to: 'outcome', kind: 'curated' },
          { from: 'assoc', to: 'outcome', kind: 'curated' },
          { from: 'kcnh2', to: 'assoc', kind: 'model' },
        ],
      },
      serotonergic: {
        label: 'Serotonergic',
        subtitle: 'Illustrative subgraph · Serotonergic pathway selected',
        selectedNodeId: 'sert',
        nodes: [
          { id: 'amitriptyline', label: 'Amitriptyline', type: 'DRUG', x: 90, y: 55 },
          { id: 'citalopram', label: 'Citalopram', type: 'DRUG', x: 500, y: 55 },
          { id: 'sert', label: 'SERT', type: 'PROTEIN', x: 140, y: 175 },
          { id: 'assoc2', label: 'Associated node', type: 'MODEL CONTEXT', x: 450, y: 175 },
          { id: 'outcome2', label: 'Serotonergic outcome', type: 'PREDICTED ASSOCIATION', x: 295, y: 265 },
        ],
        edges: [
          { from: 'amitriptyline', to: 'sert', kind: 'curated' },
          { from: 'citalopram', to: 'sert', kind: 'curated' },
          { from: 'sert', to: 'outcome2', kind: 'curated' },
          { from: 'assoc2', to: 'outcome2', kind: 'model' },
          { from: 'sert', to: 'assoc2', kind: 'model' },
        ],
      },
    },

    activePathwayKey: 'cardiac',
  };


  if(!PharmaStore.hasFixture()){
    renderWorkspaceShell('Pathway inspector');
    document.querySelector('.workspace-content').innerHTML='<h1 class="workspace-heading">Evidence is still needed.</h1><article class="ws-card empty-state"><h2>No pathway fixture for this pair</h2><p>'+UI.escape(UI.pair().map(m=>m.name).join(' + ')||'Add two medicines first')+'</p><p>The demo only includes pathways for amitriptyline and citalopram. Unknown does not mean safe.</p><a class="btn btn-primary" href="workspace.html">Return to regimen</a></article>';
    return;
  }
  function activePathway() {
    return inspectorData.pathways[inspectorData.activePathwayKey];
  }

  function nodeById(id) {
    return activePathway().nodes.find((n) => n.id === id);
  }

  function renderHeading() {
    document.getElementById('pageHeading').textContent = inspectorData.pageHeading;
    document.getElementById('pageSubhead').textContent = inspectorData.pageSubhead;
  }

  function renderToolbar() {
    document.getElementById('pairPill').textContent = inspectorData.pair.label;
    document.getElementById('scorePill').textContent = `Score ${inspectorData.pair.score} / ${inspectorData.pair.scoreMax}`;
    document.getElementById('findAlternativesBtn').textContent = inspectorData.findAlternativesLabel;
    document.getElementById('pathwayFootnote').textContent = inspectorData.pathwayFootnote;
  }

  function renderTabs() {
    const tabs = document.getElementById('pathwayTabs');
    tabs.innerHTML = '';
    Object.entries(inspectorData.pathways).forEach(([key, pathway]) => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'pathway-tab' + (key === inspectorData.activePathwayKey ? ' active' : '');
      tab.textContent = pathway.label;
      tab.addEventListener('click', () => {
        inspectorData.activePathwayKey = key;
        renderTabs();
        renderGraph();
        renderNodeDetail();
      });
      tabs.appendChild(tab);
    });
  }

  function renderEdgeLegend() {
    const legend = document.getElementById('edgeLegend');
    legend.innerHTML = inspectorData.edgeLegend
      .map(
        (item) => `
      <span class="edge-legend-item">
        <span class="edge-swatch edge-swatch-${item.kind}"></span>${item.label}
      </span>`
      )
      .join('');
  }

  const NODE_W = 148;
  const NODE_H = 54;
  const NS = 'http://www.w3.org/2000/svg';

  function svgEl(tag, attrs) {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    return el;
  }

  function renderGraph() {
    const pathway = activePathway();
    document.getElementById('pathwaySubtitle').textContent = pathway.subtitle;

    const svg = document.getElementById('pathwaySvg');
    svg.innerHTML = '';

    pathway.edges.forEach((edge) => {
      const a = nodeById(edge.from);
      const b = nodeById(edge.to);
      const line = svgEl('line', {
        x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        class: `pathway-edge pathway-edge-${edge.kind}`,
      });
      svg.appendChild(line);
    });

    pathway.nodes.forEach((node) => {
      const g = svgEl('g', { class: 'pathway-node', 'data-id': node.id, tabindex: '0' });
      const isSelected = node.id === pathway.selectedNodeId;
      const rect = svgEl('rect', {
        x: node.x - NODE_W / 2,
        y: node.y - NODE_H / 2,
        width: NODE_W,
        height: NODE_H,
        rx: 14,
        class: 'pathway-node-rect' + (isSelected ? ' selected' : ''),
      });
      const label = svgEl('text', {
        x: node.x, y: node.y - 3, class: 'pathway-node-label' + (isSelected ? ' selected' : ''),
        'text-anchor': 'middle',
      });
      label.textContent = node.label;
      const type = svgEl('text', {
        x: node.x, y: node.y + 15, class: 'pathway-node-type' + (isSelected ? ' selected' : ''),
        'text-anchor': 'middle',
      });
      type.textContent = node.type;

      g.appendChild(rect);
      g.appendChild(label);
      g.appendChild(type);
      g.setAttribute('role','button'); g.setAttribute('aria-label',node.label+' — '+node.type);
      g.addEventListener('click', () => selectNode(node.id));
      g.addEventListener('keydown', e => {if(e.key==='Enter'||e.key===' '){e.preventDefault();selectNode(node.id);}});
      svg.appendChild(g);
    });
  }

  function selectNode(id) {
    activePathway().selectedNodeId = id;
    renderGraph();
    renderNodeDetail();
  }

  function renderNodeDetail() {
    const pathway = activePathway();
    const node = nodeById(pathway.selectedNodeId);

    document.getElementById('nodeTitle').textContent = node.label;
    document.getElementById('nodeSubtitle').textContent =
      inspectorData.nodeSubtitleByType[node.type] || 'Selected node';
    document.getElementById('nodePill').textContent = inspectorData.nodePillLabel;

    document.getElementById('whyTitle').textContent = 'Why this node appears';
    document.getElementById('whyText').textContent =
      node.label + ' is shown in this illustrative ' + pathway.label.toLowerCase() + ' subgraph. Its connection requires source validation.';

    document.getElementById('sourceStatusLabel').textContent = 'SOURCE STATUS';
    document.getElementById('sourceStatusText').textContent =
      'Illustrative graph only. Attach curated source records, dates and edge-level citations when the model is integrated.';

    document.getElementById('attributionLabel').textContent = 'MODEL ATTRIBUTION';
    document.getElementById('attributionText').textContent =
      'Attribution is not causal proof. Unverified edges remain labeled.';

    document.getElementById('viewEvidenceBtn').textContent = inspectorData.evidenceButtonLabel;
  }

  document.getElementById('findAlternativesBtn').onclick=()=>UI.go('substitution-engine');
  document.getElementById('viewEvidenceBtn').onclick=()=>UI.modal('Evidence details','<p>This is an illustrative graph, not a validated causal explanation.</p><dl><dt>Selected node</dt><dd>'+UI.escape(nodeById(activePathway().selectedNodeId).label)+'</dd><dt>Source status</dt><dd>Curated source records are not connected yet.</dd><dt>Model</dt><dd>demo-v0.1 · synthetic fixtures</dd></dl>');
  renderWorkspaceShell('Pathway inspector');
  renderHeading();
  renderToolbar();
  renderTabs();
  renderEdgeLegend();
  renderGraph();
  renderNodeDetail();
})();
