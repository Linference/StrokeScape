import { useEffect, useRef } from 'react';

/** Original ambient line field. Decorative only; independent of artwork export. */
export default function Atmosphere({ enabled }: { enabled: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let width = 0, height = 0, frame = 0, last = -100, clock = 0;
    const resize = () => {
      width = innerWidth; height = innerHeight;
      const ratio = Math.min(devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      draw(clock);
    };
    const draw = (time: number) => {
      context.clearRect(0, 0, width, height);
      for (let line = 0; line < 23; line++) {
        context.beginPath();
        for (let point = 0; point <= 64; point++) {
          const x = width * point / 64;
          const y = height * 0.28 + line * 12 + Math.sin(point / 13 + time * .13 + line * .052) * height * .13
            + Math.cos(point / 20 - time * .09) * height * .10 - x * .21;
          if (point === 0) context.moveTo(x, y); else context.lineTo(x, y);
        }
        const opacity = .045 + Math.sin(line / 23 * Math.PI) * .035;
        context.strokeStyle = `rgba(203,179,133,${opacity})`;
        context.lineWidth = .65; context.stroke();
      }
    };
    const tick = (now: number) => {
      if (document.hidden) { last = now; frame = requestAnimationFrame(tick); return; }
      if (now - last >= 1000 / 24) {
        clock += Math.min(now - last, 80) / 1000;
        last = now; draw(clock);
      }
      frame = requestAnimationFrame(tick);
    };
    const start = () => {
      cancelAnimationFrame(frame); resize();
      if (enabled && !reduced.matches) frame = requestAnimationFrame(tick);
    };
    start();
    addEventListener('resize', resize); reduced.addEventListener('change', start);
    return () => { cancelAnimationFrame(frame); removeEventListener('resize', resize); reduced.removeEventListener('change', start); };
  }, [enabled]);

  return <div className={`atmosphere ${enabled ? 'is-animated' : ''}`} aria-hidden="true">
    <div className="ambient-bloom bloom-gold" /><div className="ambient-bloom bloom-teal" /><div className="ambient-bloom bloom-pearl" />
    <canvas ref={ref} className="ambient-lines" /><div className="ambient-grain" /><div className="ambient-vignette" />
  </div>;
}
