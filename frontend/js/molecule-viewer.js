// 3D atomic structure viewer for a single drug, backed by PubChem's SDF record.
// Fetches through our own FastAPI proxy (backend/app/api/v1/pubchem.py) so the
// browser never has to call PubChem directly (avoids CORS + respects their
// usage policy of not hammering the public API from arbitrary clients).
(function () {
  // Point this at wherever the FastAPI backend is actually running.
  const API_BASE = 'http://localhost:8000';
  const THREEDMOL_CDN = 'https://3Dmol.org/build/3Dmol-min.js';

  let threeDmolLoadPromise = null;

  function load3Dmol() {
    if (window.$3Dmol) return Promise.resolve();
    if (threeDmolLoadPromise) return threeDmolLoadPromise;

    threeDmolLoadPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = THREEDMOL_CDN;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error('Failed to load 3Dmol.js from CDN'));
      document.head.appendChild(script);
    });
    return threeDmolLoadPromise;
  }

  function closeModal() {
    const overlay = document.getElementById('moleculeModalOverlay');
    if (overlay) overlay.remove();
    document.removeEventListener('keydown', onKeydown);
  }

  function onKeydown(e) {
    if (e.key === 'Escape') closeModal();
  }

  function buildModal(name) {
    closeModal(); // guard against a second overlay stacking on top of one left open

    const overlay = document.createElement('div');
    overlay.id = 'moleculeModalOverlay';
    overlay.className = 'molecule-modal-overlay';
    overlay.innerHTML = `
      <div class="molecule-modal" role="dialog" aria-modal="true" aria-label="3D structure of ${name}">
        <header class="molecule-modal-header">
          <h2>${name}</h2>
          <button type="button" class="molecule-modal-close" aria-label="Close">&times;</button>
        </header>
        <p class="molecule-status" id="moleculeStatus">Loading 3D structure…</p>
        <div class="molecule-viewer-container" id="moleculeViewerContainer"></div>
        <p class="molecule-modal-footnote">3D structure from PubChem. Illustrative only — not for dosing or identification decisions.</p>
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

  function setStatus(text, isError) {
    const el = document.getElementById('moleculeStatus');
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('molecule-status-error', Boolean(isError));
    el.hidden = !text;
  }

  // The backend's own vocabulary uses the model's zero-padded CID form
  // ("CID000001072480") for lookups, but PubChem's REST API — and this
  // proxy's own `cid: int` path param — wants a plain numeric CID (1072480).
  // Static entries (PUBCHEM_CID_BY_MEDICINE_ID in workspace.js) are already
  // plain ints and pass through unchanged; only the real-vocab-search path
  // needs stripping.
  function toPubChemNumericCid(cid) {
    return String(cid).replace(/^CID/i, '').replace(/^0+(?=\d)/, '');
  }

  async function fetchSdf(cid) {
    let resp;
    try {
      resp = await fetch(`${API_BASE}/api/v1/pubchem/molecule/${encodeURIComponent(toPubChemNumericCid(cid))}`);
    } catch {
      // fetch() throws a generic "Failed to fetch" for any network-level failure
      // (backend not running, wrong port, CORS) — the specific cause isn't
      // exposed to JS, so give the most actionable message we can.
      throw new Error(`Could not reach the API at ${API_BASE}. Is the FastAPI backend running?`);
    }
    if (!resp.ok) {
      if (resp.status === 404) {
        throw new Error('No 3D structure is available for this compound.');
      }
      throw new Error(`Could not load structure (server responded ${resp.status}).`);
    }
    return resp.text();
  }

  async function openMoleculeViewer(cid, name) {
    buildModal(name);

    try {
      const [sdfText] = await Promise.all([fetchSdf(cid), load3Dmol()]);

      const container = document.getElementById('moleculeViewerContainer');
      if (!container) return; // modal was closed before this resolved

      const viewer = window.$3Dmol.createViewer(container, { backgroundColor: 'white' });
      viewer.addModel(sdfText, 'sdf');
      // Chunkier ball-and-stick (bigger spheres, thinner sticks) reads as a
      // more polished "molecular model kit" look than the default proportions.
      viewer.setStyle({}, { stick: { radius: 0.12 }, sphere: { scale: 0.38 } });

      // Element labels on each heavy atom (skip hydrogens — a full all-atom
      // label set on a real drug molecule is unreadable clutter).
      const model = viewer.getModel();
      model.selectedAtoms({}).forEach((atom) => {
        if (atom.elem === 'H') return;
        viewer.addLabel(atom.elem, {
          position: { x: atom.x, y: atom.y, z: atom.z },
          fontSize: 11,
          fontColor: 'black',
          backgroundColor: 'white',
          backgroundOpacity: 0.65,
          borderThickness: 0,
          inFront: true,
        });
      });

      viewer.zoomTo();
      viewer.render();
      setStatus('');
    } catch (err) {
      setStatus(
        err && err.message
          ? err.message
          : 'Could not load the 3D structure. Is the backend running at ' + API_BASE + '?',
        true
      );
    }
  }

  window.openMoleculeViewer = openMoleculeViewer;
})();
