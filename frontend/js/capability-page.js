(function (root) {
  function pageModel(capability, available) { return available ? { state: 'ready', data: null } : { state: 'unavailable', data: null }; }
  function mount() {
    const page = document.querySelector('[data-capability]'); if (!page) return;
    const capability = page.dataset.capability, available = ApiClient.getCapability(capability);
    const model = pageModel(capability, available); page.dataset.state = model.state;
    document.getElementById('capabilityStatus').textContent = available ? 'This workflow is ready.' : 'This workflow is awaiting its backend endpoint. No clinical data is shown.';
  }
  if (root.window === root) root.CapabilityPage = { pageModel, mount };
  if (typeof module !== 'undefined' && module.exports) module.exports = { pageModel };
})(typeof window !== 'undefined' ? window : globalThis);
