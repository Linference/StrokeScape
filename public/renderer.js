/* Shared deterministic Canvas renderer: app, standalone HTML and video export. */
(function (root) {
  'use strict';
  class StrokeRenderer {
    constructor(canvas, work, options = {}) {
      this.canvas = canvas;
      this.work = work;
      this.canvas.width = work.width;
      this.canvas.height = work.height;
      this.ctx = canvas.getContext('2d', { alpha: false });
      this.base = document.createElement('canvas');
      this.base.width = work.width;
      this.base.height = work.height;
      this.baseCtx = this.base.getContext('2d', { alpha: false, willReadFrequently: true });
      this.completed = 0;
      this.cache = new Map();
      // Bound checkpoint memory as fine-mode output resolution grows. Spread
      // checkpoints over the whole work instead of retaining only its last part.
      this.cacheLimit = Math.min(options.cacheLimit ?? 6,
        Math.floor(32 * 1024 * 1024 / Math.max(1, work.width * work.height * 4)));
      this.cacheStride = Math.max(1200, Math.ceil(work.strokes.length / (this.cacheLimit + 1)));
      this.lengths = work.strokes.map(s => {
        const lengths = [0];
        for (let i = 2; i < s.p.length; i += 2) {
          lengths.push(lengths[lengths.length - 1] + Math.hypot(s.p[i] - s.p[i - 2], s.p[i + 1] - s.p[i - 1]));
        }
        return lengths;
      });
      this.clear();
    }
    clear() {
      this.baseCtx.globalAlpha = 1;
      this.baseCtx.fillStyle = this.work.paper || '#f7f4eb';
      this.baseCtx.fillRect(0, 0, this.work.width, this.work.height);
      this.completed = 0;
    }
    draw(ctx, index, fraction = 1) {
      const s = this.work.strokes[index];
      if (!s || fraction <= 0) return null;
      const lengths = this.lengths[index];
      const target = lengths[lengths.length - 1] * Math.min(1, fraction);
      ctx.beginPath();
      ctx.moveTo(s.p[0], s.p[1]);
      let end = [s.p[0], s.p[1]];
      for (let i = 1; i < lengths.length; i++) {
        const x = s.p[i * 2], y = s.p[i * 2 + 1];
        if (lengths[i] <= target) {
          ctx.lineTo(x, y);
          end = [x, y];
        } else {
          const part = (target - lengths[i - 1]) / Math.max(0.00001, lengths[i] - lengths[i - 1]);
          end = [s.p[i * 2 - 2] + (x - s.p[i * 2 - 2]) * part, s.p[i * 2 - 1] + (y - s.p[i * 2 - 1]) * part];
          ctx.lineTo(end[0], end[1]);
          break;
        }
      }
      ctx.strokeStyle = s.c;
      ctx.lineWidth = s.w;
      ctx.lineCap = ctx.lineJoin = 'round';
      ctx.globalAlpha = s.o;
      ctx.stroke();
      ctx.globalAlpha = 1;
      return end;
    }
    render(time, cursor = false) {
      time = Math.max(0, Math.min(this.work.durationMs, time));
      const strokes = this.work.strokes;
      let lo = 0, hi = strokes.length;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (strokes[mid].s + strokes[mid].dt <= time + 0.00001) lo = mid + 1;
        else hi = mid;
      }
      const desired = lo;
      if (desired < this.completed) {
        let best = 0;
        for (const key of this.cache.keys()) if (key <= desired && key > best) best = key;
        if (best) {
          this.baseCtx.putImageData(this.cache.get(best), 0, 0);
          this.completed = best;
        } else this.clear();
      }
      while (this.completed < desired) {
        this.draw(this.baseCtx, this.completed);
        this.completed++;
        if (this.cacheLimit && this.completed < strokes.length && this.completed % this.cacheStride === 0 && !this.cache.has(this.completed)) {
          if (this.cache.size >= this.cacheLimit) this.cache.delete(this.cache.keys().next().value);
          this.cache.set(this.completed, this.baseCtx.getImageData(0, 0, this.work.width, this.work.height));
        }
      }
      this.ctx.drawImage(this.base, 0, 0);
      const active = strokes[desired];
      let tip = null;
      if (active && time >= active.s) tip = this.draw(this.ctx, desired, (time - active.s) / active.dt);
      if (cursor && tip) {
        this.ctx.beginPath();
        this.ctx.arc(tip[0], tip[1], Math.max(2, Math.min(this.work.width, this.work.height) / 180), 0, Math.PI * 2);
        this.ctx.fillStyle = '#c99a5c';
        this.ctx.fill();
      }
      return { completed: desired, layer: active?.l ?? 3, tip };
    }
    dispose() {
      this.cache.clear();
      this.base.width = this.base.height = 1;
    }
  }
  root.StrokeRenderer = StrokeRenderer;
})(typeof window === 'undefined' ? globalThis : window);
