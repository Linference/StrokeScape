/* Shared deterministic Canvas renderer: app, standalone HTML and video export. */
(function (root) {
  'use strict';
  function brushPaths(points, width, opacity, style = 'classic', index = 0, seed = 42, texture = 1, gaps = 1) {
    if (!['classic', 'pencil', 'marker', 'dry', 'watercolor', 'oil', 'pointillism', 'colored_pencil'].includes(style)) throw new Error('Unknown brush style');
    if (style === 'classic') return [{ p: points, w: width, o: opacity, cap: 'round', keep: null }];
    let state = (seed ^ Math.imul(index + 1, 0x9e3779b1)) >>> 0;
    const random = () => { state = (1664525 * state + 1013904223) >>> 0; return state / 4294967296; };
    const count = points.length / 2, normals = [];
    for (let v = 0; v < count; v++) {
      const a = Math.max(0, v - 1), b = Math.min(count - 1, v + 1);
      const dx = points[b * 2] - points[a * 2], dy = points[b * 2 + 1] - points[a * 2 + 1];
      const length = Math.max(Math.hypot(dx, dy), 1e-6);
      normals.push([-dy / length, dx / length]);
    }
    if (style === 'pointillism') {
      const lengths = [0];
      for (let v = 1; v < count; v++) lengths.push(lengths[v - 1] + Math.hypot(points[v * 2] - points[v * 2 - 2], points[v * 2 + 1] - points[v * 2 - 1]));
      const total = lengths[lengths.length - 1], dots = [];
      const dotCount = Math.max(2, Math.min(32, Math.ceil(total / Math.max(0.75, width * 0.72)) + 1));
      let segment = 1;
      for (let dot = 0; dot < dotCount; dot++) {
        const t = dot / (dotCount - 1), distance = total * t;
        while (segment < count - 1 && lengths[segment] < distance) segment++;
        const part = (distance - lengths[segment - 1]) / Math.max(1e-6, lengths[segment] - lengths[segment - 1]);
        const offset = (random() - 0.5) * width * 0.9 * texture, [nx, ny] = normals[segment - 1];
        const x = points[segment * 2 - 2] + (points[segment * 2] - points[segment * 2 - 2]) * part + nx * offset;
        const y = points[segment * 2 - 1] + (points[segment * 2 + 1] - points[segment * 2 - 1]) * part + ny * offset;
        dots.push([x, y, Math.max(0.22, width * (0.17 + random() * 0.17)), t]);
      }
      return [{ p: points, w: width, o: opacity, cap: 'round', keep: null, dots }];
    }
    const paths = [], passes = ['pencil', 'marker'].includes(style) ? 3 : 5;
    for (let lane = 0; lane < passes; lane++) {
      let offset, thickness, alpha, cap, tone = null;
      if (style === 'marker') {
        offset = lane === 0 ? 0 : lane === 1 ? -0.4 : 0.4;
        thickness = lane === 0 ? width : width * 0.13;
        alpha = lane === 0 ? opacity : opacity * 0.22; cap = 'butt';
      } else if (style === 'pencil' || style === 'colored_pencil') {
        offset = (lane - (style === 'pencil' ? 1 : 2)) * (style === 'pencil' ? 0.27 : 0.17);
        thickness = Math.max(0.22, width * ((style === 'pencil' ? 0.13 : 0.08) + random() * 0.12));
        alpha = opacity * (0.58 + random() * 0.32); cap = 'round';
      } else if (style === 'watercolor') {
        offset = lane < 3 ? 0 : lane === 3 ? -0.4 : 0.4;
        thickness = width * (lane < 3 ? [1.35, 1.05, 0.78][lane] : 0.09);
        alpha = opacity * (lane < 3 ? [0.12, 0.22, 0.34][lane] : 0.12); cap = 'round';
      } else if (style === 'oil') {
        offset = lane === 0 ? 0 : (lane - 2.5) * 0.2;
        thickness = width * (lane === 0 ? 1.05 : 0.055 + random() * 0.04);
        alpha = opacity * (lane === 0 ? 0.97 : 0.35 + random() * 0.35); cap = 'round';
        tone = lane === 0 ? 0 : lane % 2 ? 0.16 : -0.12;
      } else {
        offset = (lane - 2) * 0.19;
        thickness = Math.max(0.22, width * (0.08 + random() * 0.09));
        alpha = opacity * (0.7 + random() * 0.3); cap = 'butt';
      }
      const shifted = [];
      for (let v = 0; v < count; v++) {
        const jitter = style === 'marker' ? 0 : (random() - 0.5) * (style === 'oil' ? 0.04 : 0.12);
        const distance = (offset + jitter) * width * texture;
        shifted.push(points[v * 2] + normals[v][0] * distance, points[v * 2 + 1] + normals[v][1] * distance);
      }
      const keep = ['pencil', 'colored_pencil', 'dry'].includes(style) ? Array.from({ length: count - 1 }, () => random() > (['pencil', 'colored_pencil'].includes(style) ? 0.13 : 0.24) * gaps) : null;
      if (keep && !keep.some(Boolean)) keep[Math.floor(keep.length / 2)] = true;
      const path = { p: shifted, w: thickness, o: alpha, cap, keep };
      if (tone !== null) path.tone = tone;
      paths.push(path);
    }
    return paths;
  }
  class StrokeRenderer {
    constructor(canvas, work, options = {}) {
      this.canvas = canvas;
      this.work = work;
      this.brush = work.settings?.brush || 'classic';
      this.seed = work.settings?.seed ?? 42;
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
      let end = [s.p[0], s.p[1]];
      for (let i = 1; i < lengths.length; i++) {
        const x = s.p[i * 2], y = s.p[i * 2 + 1];
        if (lengths[i] <= target) {
          end = [x, y];
        } else {
          const part = (target - lengths[i - 1]) / Math.max(0.00001, lengths[i] - lengths[i - 1]);
          end = [s.p[i * 2 - 2] + (x - s.p[i * 2 - 2]) * part, s.p[i * 2 - 1] + (y - s.p[i * 2 - 1]) * part];
          break;
        }
      }
      // Geometry and missing bristle segments are seeded per stroke, never per
      // frame. Seeking and replay therefore reproduce the same texture.
      if (s.clip) { ctx.save(); ctx.beginPath(); ctx.rect(...s.clip); ctx.clip(); }
      for (const path of brushPaths(s.p, s.w, s.o, s.b || this.brush, index, s.seed ?? this.seed, s.tx ?? this.work.settings?.texture ?? 1, s.g ?? this.work.settings?.gaps ?? 1)) {
        const tone = path.tone || 0;
        const color = tone ? '#' + [1, 3, 5].map(offset => {
          const value = parseInt(s.c.slice(offset, offset + 2), 16);
          return Math.round(value + (tone > 0 ? (255 - value) * tone : value * tone)).toString(16).padStart(2, '0');
        }).join('') : s.c;
        ctx.strokeStyle = color;
        if (path.dots) {
          ctx.fillStyle = color;
          ctx.globalAlpha = path.o;
          for (const [x, y, radius, at] of path.dots) {
            if (at > fraction) break;
            ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill();
          }
          continue;
        }
        ctx.beginPath();
        ctx.moveTo(path.p[0], path.p[1]);
        for (let i = 1; i < lengths.length; i++) {
          const ratio = Math.min(1, (target - lengths[i - 1]) / Math.max(0.00001, lengths[i] - lengths[i - 1]));
          if (ratio <= 0) break;
          const x = path.p[i * 2 - 2] + (path.p[i * 2] - path.p[i * 2 - 2]) * ratio;
          const y = path.p[i * 2 - 1] + (path.p[i * 2 + 1] - path.p[i * 2 - 1]) * ratio;
          if (!path.keep || path.keep[i - 1]) ctx.lineTo(x, y);
          else ctx.moveTo(x, y);
          if (ratio < 1) break;
        }
        ctx.lineWidth = path.w;
        ctx.lineCap = path.cap;
        ctx.lineJoin = 'round';
        ctx.globalAlpha = path.o;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      if (s.clip) ctx.restore();
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
  root.StrokeBrushes = { paths: brushPaths };
})(typeof window === 'undefined' ? globalThis : window);
