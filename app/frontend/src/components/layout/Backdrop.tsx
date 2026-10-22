import {useEffect, useRef} from 'react';

interface Star {
  x: number;
  y: number;
  /** Depth: 1 is far away, near 0 is about to pass the viewer. */
  z: number;
  tone: number;
}

interface Meteor {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
}

/** Colours come from the design tokens (rules/32); the canvas reads them once. */
const TONES = ['--color-star', '--color-star-cool', '--color-star-warm'];
const LINK = '--color-constellation';
const METEOR = '--color-meteor';

/** How far the field moves towards the viewer (depth units per millisecond). */
const SPEED = 0.000032;
/** Stars nearer than this are linked into constellations when they are close on screen. */
const LINK_DEPTH = 0.55;
const LINK_DISTANCE = 140;

/**
 * The "Evren" backdrop, in depth: a star field that drifts slowly towards the viewer, leans a
 * little with the pointer, links nearby stars into faint constellations like a data network, and
 * now and then lets a meteor cross. Purely decorative and hidden from assistive technology; one
 * still frame for users who prefer less motion; it pauses while the tab is hidden.
 */
export function Backdrop() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext('2d');
    if (!element || !context) return;
    const style = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
    const colours = TONES.map((name) => read(name, '#ffffff'));
    const linkColour = read(LINK, 'rgba(124, 244, 255, 0.5)');
    const meteorColour = read(METEOR, '#ffffff');
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

    let stars: Star[] = [];
    let meteor: Meteor | null = null;
    let nextMeteor = 4000 + Math.random() * 6000;
    let frame = 0;
    let last = 0;
    let width = 0;
    let height = 0;
    // The pointer leans the view; the lean eases towards it.
    let leanX = 0;
    let leanY = 0;
    let targetX = 0;
    let targetY = 0;

    const spawn = (z = Math.random()): Star => ({
      x: (Math.random() * 2 - 1) * 1.4,
      y: (Math.random() * 2 - 1) * 1.4,
      z: Math.max(z, 0.05),
      tone: Math.floor(Math.random() * colours.length),
    });

    function resize() {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      element!.width = width * ratio;
      element!.height = height * ratio;
      context!.setTransform(ratio, 0, 0, ratio, 0, 0);
      const count = Math.round(Math.min(320, (width * height) / 5200));
      stars = Array.from({length: count}, () => spawn());
    }

    function project(star: Star) {
      const focal = Math.min(width, height) * 0.55;
      const depth = star.z;
      return {
        sx: width / 2 + leanX * (1 - depth) * 40 + (star.x / depth) * focal * 0.45,
        sy: height / 2 + leanY * (1 - depth) * 40 + (star.y / depth) * focal * 0.45,
        size: Math.max(0.35, (1 - depth) * 2.2),
        alpha: Math.min(1, (1 - depth) * 1.6) * (depth < 0.12 ? depth / 0.12 : 1),
      };
    }

    function draw(elapsed: number) {
      context!.clearRect(0, 0, width, height);
      leanX += (targetX - leanX) * 0.04;
      leanY += (targetY - leanY) * 0.04;

      const near: {sx: number; sy: number; alpha: number}[] = [];
      for (let index = 0; index < stars.length; index++) {
        const star = stars[index];
        if (!still) star.z -= SPEED * elapsed;
        if (star.z <= 0.05) {
          stars[index] = spawn(1);
          continue;
        }
        const {sx, sy, size, alpha} = project(star);
        if (sx < -20 || sx > width + 20 || sy < -20 || sy > height + 20) {
          stars[index] = spawn(1);
          continue;
        }
        context!.globalAlpha = alpha * 0.9;
        context!.fillStyle = colours[star.tone];
        context!.beginPath();
        context!.arc(sx, sy, size, 0, Math.PI * 2);
        context!.fill();
        if (star.z < LINK_DEPTH && near.length < 80) near.push({sx, sy, alpha});
      }

      // Constellations: nearby bright stars joined by hair-thin lines that fade with distance.
      context!.strokeStyle = linkColour;
      context!.lineWidth = 0.6;
      for (let a = 0; a < near.length; a++) {
        for (let b = a + 1; b < near.length; b++) {
          const distance = Math.hypot(near[a].sx - near[b].sx, near[a].sy - near[b].sy);
          if (distance > LINK_DISTANCE) continue;
          context!.globalAlpha = (1 - distance / LINK_DISTANCE) * Math.min(near[a].alpha, near[b].alpha) * 0.55;
          context!.beginPath();
          context!.moveTo(near[a].sx, near[a].sy);
          context!.lineTo(near[b].sx, near[b].sy);
          context!.stroke();
        }
      }

      if (!still) drawMeteor(elapsed);
      context!.globalAlpha = 1;
    }

    function drawMeteor(elapsed: number) {
      nextMeteor -= elapsed;
      if (!meteor && nextMeteor <= 0) {
        const fromLeft = Math.random() < 0.5;
        meteor = {
          x: fromLeft ? Math.random() * width * 0.5 : width * (0.5 + Math.random() * 0.5),
          y: Math.random() * height * 0.35,
          vx: (fromLeft ? 1 : -1) * (0.55 + Math.random() * 0.35),
          vy: 0.22 + Math.random() * 0.18,
          life: 1,
        };
        nextMeteor = 7000 + Math.random() * 9000;
      }
      if (!meteor) return;
      meteor.x += meteor.vx * elapsed;
      meteor.y += meteor.vy * elapsed;
      meteor.life -= elapsed / 1100;
      if (meteor.life <= 0) {
        meteor = null;
        return;
      }
      const tail = 140;
      const length = Math.hypot(meteor.vx, meteor.vy);
      const endX = meteor.x - (meteor.vx / length) * tail;
      const endY = meteor.y - (meteor.vy / length) * tail;
      const gradient = context!.createLinearGradient(meteor.x, meteor.y, endX, endY);
      gradient.addColorStop(0, meteorColour);
      gradient.addColorStop(1, 'transparent');
      context!.globalAlpha = Math.sin(meteor.life * Math.PI);
      context!.strokeStyle = gradient;
      context!.lineWidth = 1.4;
      context!.beginPath();
      context!.moveTo(meteor.x, meteor.y);
      context!.lineTo(endX, endY);
      context!.stroke();
    }

    function loop(time: number) {
      const elapsed = last ? Math.min(time - last, 64) : 16;
      last = time;
      draw(elapsed);
      frame = window.requestAnimationFrame(loop);
    }

    function start() {
      window.cancelAnimationFrame(frame);
      last = 0;
      if (still) draw(0);
      else if (!document.hidden) frame = window.requestAnimationFrame(loop);
    }

    function onResize() {
      resize();
      start();
    }

    function onPointer(event: PointerEvent) {
      targetX = (event.clientX / Math.max(width, 1)) * 2 - 1;
      targetY = (event.clientY / Math.max(height, 1)) * 2 - 1;
    }

    resize();
    start();
    window.addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', start);
    if (!still) window.addEventListener('pointermove', onPointer, {passive: true});
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', start);
      window.removeEventListener('pointermove', onPointer);
    };
  }, []);

  return <canvas ref={canvas} className="backdrop" aria-hidden="true" />;
}
