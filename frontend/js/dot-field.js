// Reusable animated dot-grid background (à la reactbits.dev "Dot Field"):
// a canvas of evenly-spaced dots that brighten/enlarge near the cursor.
// Plain 2D canvas, no dependencies — meant to sit behind a transparent-
// background WebGL canvas (3d-force-graph, 3Dmol) so it reads as one scene.
(function () {
  function createDotField(container, options) {
    const opts = Object.assign(
      {
        spacing: 26,
        baseRadius: 1.1,
        maxRadius: 3,
        baseColor: 'rgba(226, 58, 114, 0.35)',
        hotColor: 'rgba(255, 130, 180, 0.95)',
        influenceRadius: 130,
        background: null, // e.g. 'rgba(38, 16, 28, 1)' — null leaves it transparent
      },
      options || {}
    );

    const canvas = document.createElement('canvas');
    canvas.className = 'dot-field-canvas';
    container.appendChild(canvas);
    const ctx = canvas.getContext('2d');

    let width = 0;
    let height = 0;
    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    let mouseX = null;
    let mouseY = null;
    let raf = null;

    function resize() {
      width = container.clientWidth;
      height = container.clientHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();

    function onMouseMove(e) {
      const rect = container.getBoundingClientRect();
      mouseX = e.clientX - rect.left;
      mouseY = e.clientY - rect.top;
    }
    function onMouseLeave() {
      mouseX = null;
      mouseY = null;
    }
    container.addEventListener('mousemove', onMouseMove);
    container.addEventListener('mouseleave', onMouseLeave);

    function draw() {
      ctx.clearRect(0, 0, width, height);
      if (opts.background) {
        ctx.fillStyle = opts.background;
        ctx.fillRect(0, 0, width, height);
      }

      for (let y = opts.spacing / 2; y < height; y += opts.spacing) {
        for (let x = opts.spacing / 2; x < width; x += opts.spacing) {
          let radius = opts.baseRadius;
          let color = opts.baseColor;

          if (mouseX !== null) {
            const dist = Math.hypot(x - mouseX, y - mouseY);
            if (dist < opts.influenceRadius) {
              const t = 1 - dist / opts.influenceRadius; // 0..1, closer = higher
              radius = opts.baseRadius + (opts.maxRadius - opts.baseRadius) * t;
              color = t > 0.5 ? opts.hotColor : opts.baseColor;
            }
          }

          ctx.beginPath();
          ctx.arc(x, y, radius, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
        }
      }

      raf = requestAnimationFrame(draw);
    }
    draw();

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);

    return function destroy() {
      if (raf) cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      container.removeEventListener('mousemove', onMouseMove);
      container.removeEventListener('mouseleave', onMouseLeave);
      canvas.remove();
    };
  }

  window.createDotField = createDotField;
})();
