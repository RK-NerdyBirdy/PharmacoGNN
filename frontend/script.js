(function () {
  const heroWrapper = document.getElementById('heroPinWrapper');

  const stateA = document.querySelectorAll('.state-a');
  const stateB = document.querySelectorAll('.state-b');

  const graphSpacer = document.querySelector('.hero-sticky .graph-spacer');
  const graphIcon = document.querySelector('.hero-sticky .graph-icon');

  const ctaArea = document.querySelector('.cta-area');
  const footerStrip = document.querySelector('.footer-strip');

  const waveBg = document.querySelector('.wave-bg');
  const wave1 = document.querySelector('.wave-1');
  const wave2 = document.querySelector('.wave-2');
  const wave3 = document.querySelector('.wave-3');

  const MAX_SPACER = 150; // px the spacer grows to, pushing the capsule halves apart

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  // ease-in-out for a smoother, less linear feel
  function ease(t) {
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  }

  function getProgress() {
    const rect = heroWrapper.getBoundingClientRect();
    const total = heroWrapper.offsetHeight - window.innerHeight;
    if (total <= 0) return 1;
    return clamp(-rect.top / total, 0, 1);
  }

  function applyProgress(pRaw) {
    const p = ease(pRaw);

    // crossfade: state A fades out over the first half, state B fades in over the second half
    const fadeOutA = clamp(1 - pRaw * 2.2, 0, 1);
    const fadeInB = clamp(pRaw * 2.2 - 1, 0, 1);

    stateA.forEach((el) => {
      el.style.opacity = fadeOutA;
      el.style.transform = `translateY(${-16 * pRaw}px)`;
    });
    stateB.forEach((el) => {
      el.style.opacity = fadeInB;
      el.style.transform = `translateY(${16 * (1 - fadeInB)}px)`;
    });

    // capsule split (spacer growth pushes the two flex halves apart) + graph reveal
    if (graphSpacer) graphSpacer.style.width = `${p * MAX_SPACER}px`;
    if (graphIcon) {
      graphIcon.style.opacity = clamp(p * 1.6, 0, 1);
      graphIcon.style.transform = `scale(${0.5 + p * 0.5}) rotate(${(1 - p) * -30}deg)`;
    }

    // CTA fades away as the capsule opens
    if (ctaArea) {
      ctaArea.style.opacity = clamp(1 - pRaw * 1.8, 0, 1);
      ctaArea.style.transform = `translateY(${p * 20}px)`;
    }

    // waves slide down and out of view (clipped by hero-sticky's overflow:hidden)
    // instead of up, which would uncover hard rectangular gaps at each layer's edge
    if (wave1) wave1.style.transform = `translateY(${p * 220}px)`;
    if (wave2) wave2.style.transform = `translateY(${p * 320}px)`;
    if (wave3) wave3.style.transform = `translateY(${p * 420}px)`;
    // the whole wave block fully fades out well before the pin releases,
    // so nothing is left lingering when the cards section arrives
    if (waveBg) waveBg.style.opacity = clamp(1 - pRaw * 1.35, 0, 1);
    if (footerStrip) footerStrip.style.opacity = clamp(1 - pRaw * 1.6, 0, 1);
  }

  let ticking = false;
  function onScroll() {
    if (!ticking) {
      requestAnimationFrame(() => {
        applyProgress(getProgress());
        ticking = false;
      });
      ticking = true;
    }
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  applyProgress(getProgress());

  // feature card reveal on scroll into view
  const cards = document.querySelectorAll('.feature-card');
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          setTimeout(() => entry.target.classList.add('in-view'), i * 90);
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.2 }
  );
  cards.forEach((card) => observer.observe(card));
})();
