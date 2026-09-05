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
    priority: 'rgba(255, 90, 145, 0.95)',
    review: 'rgba(255, 170, 200, 0.9)',
    lower: 'rgba(150, 220, 180, 0.9)',
    unknown: 'rgba(210, 200, 205, 0.6)',
  };

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
    const nodes = medicines.map((m) => ({ id: m.letter, name: m.name }));

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
          label: `${medicines[i].name} × ${medicines[j].name}: ${value === null || value === undefined ? 'not modeled' : value + '/100'}`,
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
        <div class="matrix-legend drug-graph-legend" id="drugGraphLegend"></div>
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

  function renderLegend(thresholds) {
    const legend = document.getElementById('drugGraphLegend');
    if (!legend) return;
    legend.innerHTML = `
      <span class="legend-chip legend-priority">Priority (≥ ${thresholds.priority})</span>
      <span class="legend-chip legend-review">Review (≥ ${thresholds.review})</span>
      <span class="legend-chip legend-lower">Lower</span>
      <span class="legend-chip legend-unknown">Unknown</span>
    `;
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
    renderLegend(source.thresholds);

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
        .nodeLabel((n) => n.name)
        .nodeAutoColorBy('id')
        .nodeOpacity(0.95)
        .nodeVal(6)
        .linkLabel((l) => l.label)
        .linkWidth((l) => 0.6 + (l.value / 100) * 3.5)
        .linkColor((l) => COLOR_BY_CLASS[l.cls])
        .linkOpacity(0.9)
        .width(container.clientWidth)
        .height(container.clientHeight);

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
