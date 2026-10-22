import { useEffect, useRef } from 'react';
import type { BrushStyle, Work } from './types';

export const BRUSHES: { id: BrushStyle; name: string; hint: string }[] = [
  { id: 'classic', name: '圆笔', hint: '平滑圆头 · 保留色彩' },
  { id: 'pencil', name: '石墨铅笔', hint: '灰阶细线 · 断续排线' },
  { id: 'marker', name: '马克笔', hint: '平头宽笔 · 透色叠墨' },
  { id: 'dry', name: '干刷', hint: '疏密刷毛 · 断续留白' },
  { id: 'watercolor', name: '水彩', hint: '柔边晕染 · 透明叠色' },
  { id: 'oil', name: '油画', hint: '浓厚覆盖 · 明暗刷痕' },
  { id: 'pointillism', name: '点彩', hint: '疏密圆点 · 逐点落色' },
  { id: 'colored_pencil', name: '彩色铅笔', hint: '彩色细线 · 交叠排线' },
];

function BrushSwatch({ brush, load }: { brush: BrushStyle; load: () => Promise<void> }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let disposed = false;
    void load().then(() => {
      if (disposed || !ref.current) return;
      const work: Work = { version: 1, width: 112, height: 28, paper: '#f7f4eb', durationMs: 1,
        strokes: [{ p: [8, 19, 28, 9, 51, 18, 77, 9, 103, 15], c: brush === 'pencil' ? '#555555' : '#7864b5',
          w: 10, o: brush === 'marker' ? 0.6 : brush === 'oil' ? 1 : 0.88, l: 0, s: 0, dt: 1 }], layers: [1, 0, 0, 0],
        settings: { preset: 'sketch', brush, duration: 15, device: 'cpu', seed: 42 },
        stats: { count: 1, computeSeconds: 0, backend: 'cpu', seed: 42 } };
      const renderer = new window.StrokeRenderer(ref.current, work, { cacheLimit: 0 });
      renderer.render(1); renderer.dispose();
    }).catch(() => { /* The main renderer reports loading failures. */ });
    return () => { disposed = true; };
  }, [brush, load]);
  return <canvas ref={ref} width={112} height={28} aria-hidden="true" />;
}

export default function BrushPicker({ value, onChange, load, pending }: {
  value: BrushStyle; onChange: (value: BrushStyle) => void; load: () => Promise<void>; pending: boolean;
}) {
  return <div className="brush-section"><div className="section-label"><span>笔刷风格</span><span className="muted">{BRUSHES.length} 种笔触</span></div>
    <div className="brush-options" role="radiogroup" aria-label="笔刷风格">{BRUSHES.map(brush => <button key={brush.id}
      role="radio" aria-label={`${brush.name} ${brush.hint}`} title={`${brush.name} · ${brush.hint}`} aria-checked={value === brush.id} className={`brush-choice ${value === brush.id ? 'selected' : ''}`}
      onClick={() => onChange(brush.id)}><BrushSwatch brush={brush.id} load={load} /><strong>{brush.name}</strong><small>{brush.hint}</small></button>)}</div>
    <p className="brush-description">{BRUSHES.find(brush => brush.id === value)?.hint}</p>
    {pending && <p className="brush-pending" role="status">笔刷已更改，点击“重新生成”应用到作品。</p>}
  </div>;
}
