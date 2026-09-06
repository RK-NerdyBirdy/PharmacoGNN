// 3D relationship graph of the drugs in the current regimen: one node per drug,
// one link per pairwise interaction score. Built from the exact same data that
// drives the 2D interaction matrix on the Regimen Overview page (see
// window.getRegimenGraphData in workspace.js) — this is a different view of the
// same numbers, not a separate dataset.
//
// The "grid" background is a plain 2D canvas (dot-field.js) sitting behind a
// transparent-background 3d-force-graph canvas, not a 3D object in the scene.
// Node/link labels are hover tooltips (nodeLabel/linkLabel), not persistent
// 3D sprites: this library's CDN bundle keeps its own internal Three.js
// instance private (nothing exposes it on `window`), so neither a separately
// loaded Three.js nor three-spritetext (which needs a global THREE to exist)
// can interoperate with it — both attempts crashed the render loop outright.
(function () {
  const FORCE_GRAPH_CDN = 'https://cdn.jsdelivr.net/npm/3d-force-graph@1/dist/3d-force-graph.min.js';

  // Mirrors the color tokens used for the 2D matrix cells (css/workspace.css)
  // so the two views read as the same classification.
  const COLOR_BY_CLASS = {
    priority: 'rgba(239, 55, 123, 1)',
    review: 'rgba(243, 146, 184, 0.95)',
    lower: 'rgba(105, 188, 157, 0.9)',
    unknown: 'rgba(191, 177, 185, 0.42)',
  };
  const WIDTH_BY_CLASS = { priority: 8, review: 4.5, lower: 1.8, unknown: 0.35 };

  let forceGraphLoadPromise = null;
  let activeCleanup = null;

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`Failed to load ${src} from CDN`));
      document.head.appendChild(script);
    });
  }

  function loadForceGraph() {
    if (window.ForceGraph3D) return Promise.resolve();
    if (!forceGraphLoadPromise) forceGraphLoadPromise = loadScript(FORCE_GRAPH_CDN);
    return forceGraphLoadPromise;
  }

  function classifyScore(value, thresholds) {
    if (value === null || value === undefined) return 'unknown';
    if (value >= thresholds.priority) return 'priority';
    if (value >= thresholds.review) return 'review';
    return 'lower';
  }

  function buildGraphData({ medicines, matrixScores, thresholds }) {
    const nodes = medicines.map((m) => ({
      id: m.letter,
      name: m.name,
      label: `${m.letter} · ${m.name}`,
    }));

    const links = [];
    for (let i = 0; i < medicines.length; i++) {
      for (let j = i + 1; j < medicines.length; j++) {
        const a = medicines[i].letter;
        const b = medicines[j].letter;
        const value = matrixScores[[a, b].sort().join('-')];
        const cls = classifyScore(value, thresholds);
        links.push({
          source: a,
          target: b,
          value: value === null || value === undefined ? 0 : value,
          cls,
          label: `${a} · ${medicines[i].name} × ${b} · ${medicines[j].name}: ${value === null || value === undefined ? 'not modeled' : value + '/100'}`,
        });
      }
    }
    return { nodes, links };
  }

  function closeModal() {
    const overlay = document.getElementById('drugGraphModalOverlay');
    if (overlay) overlay.remove();
    document.removeEventListener('keydown', onKeydown);
    if (activeCleanup) {
      activeCleanup();
      activeCleanup = null;
    }
  }

  function onKeydown(e) {
    if (e.key === 'Escape') closeModal();
  }

  function buildModal() {
    closeModal(); // guard against a second overlay stacking on top of one left open

    const overlay = document.createElement('div');
    overlay.id = 'drugGraphModalOverlay';
    overlay.className = 'molecule-modal-overlay';
    overlay.innerHTML = `
      <div class="molecule-modal drug-graph-modal" role="dialog" aria-modal="true" aria-label="3D drug relationship map">
        <header class="molecule-modal-header">
          <h2>Regimen relationship map</h2>
          <button type="button" class="molecule-modal-close" aria-label="Close">&times;</button>
        </header>
        <p class="ws-card-note">Drag to rotate, scroll to zoom, move the cursor around.</p>
        <p class="molecule-status" id="drugGraphStatus">Loading 3D map…</p>
        <div class="drug-graph-stage" id="drugGraphStage">
          <div class="drug-graph-container" id="drugGraphContainer"></div>
        </div>
        <div class="drug-graph-guide">
          <div class="drug-graph-guide-section">
            <h3>Drug key</h3>
            <div class="drug-graph-node-key" id="drugGraphNodeKey"></div>
          </div>
          <div class="drug-graph-guide-section">
            <h3>Connection key</h3>
            <div class="matrix-legend drug-graph-legend" id="drugGraphLegend"></div>
          </div>
        </div>
      </div>
    `;
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });
    overlay.querySelector('.molecule-modal-close').addEventListener('click', closeModal);
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onKeydown);
    return overlay;
  }

  function renderLegend(source) {
    const { thresholds, medicines } = source;
    const legend = document.getElementById('drugGraphLegend');
    if (!legend) return;
    legend.innerHTML = `
      <span class="drug-graph-edge-sample priority"></span><span>Priority ≥ ${thresholds.priority}: bold edge</span>
      <span class="drug-graph-edge-sample review"></span><span>Review ≥ ${thresholds.review}: medium edge</span>
      <span class="drug-graph-edge-sample lower"></span><span>Lower score: fine edge</span>
      <span class="drug-graph-edge-sample unknown"></span><span>Unknown: faint edge</span>
    `;
    const nodeKey = document.getElementById('drugGraphNodeKey');
    if (nodeKey) nodeKey.innerHTML = medicines.map((medicine) =>
      `<span class="drug-graph-node-label"><b>${medicine.letter}</b><span title="${medicine.name}">${medicine.name}</span></span>`
    ).join('');
  }

  function setStatus(text, isError) {
    const el = document.getElementById('drugGraphStatus');
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('molecule-status-error', Boolean(isError));
    el.hidden = !text;
  }

  async function openDrugGraph() {
    if (!window.getRegimenGraphData) {
      throw new Error('getRegimenGraphData is not available on this page');
    }
    const source = window.getRegimenGraphData();
    buildModal();
    renderLegend(source);

    try {
      await loadForceGraph();
      const stage = document.getElementById('drugGraphStage');
      const container = document.getElementById('drugGraphContainer');
      if (!container) return; // modal was closed before this resolved

      const destroyDotField = window.createDotField(stage, {
        background: 'rgba(38, 16, 28, 1)',
      });

      const data = buildGraphData(source);

      const graph = window.ForceGraph3D()(container)
        .graphData(data)
        .backgroundColor('rgba(0,0,0,0)') // transparent — the dot field shows through
        .nodeLabel((n) => n.label)
        .nodeColor(() => '#f6d5e2')
        .nodeOpacity(1)
        .nodeVal(10)
        .linkLabel((l) => l.label)
        .linkWidth((l) => WIDTH_BY_CLASS[l.cls])
        .linkColor((l) => COLOR_BY_CLASS[l.cls])
        .linkOpacity((l) => l.cls === 'unknown' ? 0.28 : 0.95)
        .linkDirectionalParticles((l) => l.cls === 'priority' ? 3 : 0)
        .linkDirectionalParticleWidth((l) => l.cls === 'priority' ? 2.5 : 0)
        .linkDirectionalParticleColor((l) => COLOR_BY_CLASS[l.cls])
        .width(container.clientWidth)
        .height(container.clientHeight);

      graph.d3Force('charge').strength(-260);
      graph.d3Force('link').distance((link) => link.cls === 'priority' ? 105 : 145);
      // Wait for the force layout to spread out, then frame the actual graph
      // rather than leaving a small cluster in the middle of the full stage.
      window.setTimeout(() => {
        if (document.body.contains(container)) graph.zoomToFit(300, 90);
      }, 750);

      function onResize() {
        if (!document.body.contains(container)) return;
        graph.width(container.clientWidth).height(container.clientHeight);
      }
      window.addEventListener('resize', onResize);

      activeCleanup = () => {
        window.removeEventListener('resize', onResize);
        destroyDotField();
      };

      setStatus('');
    } catch (err) {
      setStatus(err && err.message ? err.message : 'Could not load the 3D map.', true);
    }
  }

  window.openDrugGraph = openDrugGraph;
})();
