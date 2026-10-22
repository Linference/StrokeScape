import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent, RefObject } from 'react';
import { Columns2, Maximize, Minus, Plus, Scan } from 'lucide-react';
import type { Region } from './types';

export type CanvasView = 'painting' | 'source' | 'compare';
interface Props {
  source: string; title: string; width?: number; height?: number;
  view: CanvasView; canvasRef: RefObject<HTMLCanvasElement | null>;
  preview?: string; selecting?: boolean; selection?: Region | null; onSelection?: (region: Region) => void;
}
type Transform = { zoom: number; x: number; y: number };
const FIT: Transform = { zoom: 1, x: 0, y: 0 };
const limit = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

export default function CanvasViewport({ source, title, width, height, view, canvasRef, preview, selecting, selection, onSelection }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const [area, setArea] = useState({ width: 1, height: 1 });
  const [natural, setNatural] = useState({ width: 1, height: 1 });
  const [transform, setTransform] = useState<Transform>(FIT);
  const [split, setSplit] = useState(50);
  const [dragging, setDragging] = useState(false);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ origin: Transform; x: number; y: number; distance: number } | null>(null);
  const current = useRef(transform);
  const selectionStart = useRef<[number, number] | null>(null);
  current.current = transform;
  const imageWidth = width || natural.width, imageHeight = height || natural.height;
  const fit = Math.max(0.001, Math.min(1, Math.max(1, area.width - 56) / imageWidth, Math.max(1, area.height - 86) / imageHeight));
  const fitted = { width: imageWidth * fit, height: imageHeight * fit };
  const clamp = useCallback((next: Transform): Transform => {
    const zoom = limit(next.zoom, 1, 16);
    const maxX = Math.max(0, (imageWidth * fit * zoom - Math.max(1, area.width - 36)) / 2);
    const maxY = Math.max(0, (imageHeight * fit * zoom - Math.max(1, area.height - 100)) / 2);
    return { zoom, x: limit(next.x, -maxX, maxX), y: limit(next.y, -maxY, maxY) };
  }, [area, fit, imageWidth, imageHeight]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = new ResizeObserver(([entry]) => setArea({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(root);
    return () => observer.disconnect();
  }, []);
  useEffect(() => { setTransform(FIT); setSplit(50); pointers.current.clear(); gesture.current = null; setDragging(false); }, [source, width, height]);
  useEffect(() => { setTransform(previous => clamp(previous)); }, [clamp]);

  const zoomTo = useCallback((value: number, anchor?: { x: number; y: number }) => {
    setTransform(previous => {
      const zoom = limit(value, 1, 16), ratio = zoom / previous.zoom;
      return clamp({ zoom, x: anchor ? anchor.x - (anchor.x - previous.x) * ratio : previous.x,
        y: anchor ? anchor.y - (anchor.y - previous.y) * ratio : previous.y });
    });
  }, [clamp]);
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const wheel = (event: WheelEvent) => {
      if ((event.target as HTMLElement).closest('button,input')) return;
      event.preventDefault();
      const rect = root.getBoundingClientRect();
      zoomTo(current.current.zoom * Math.exp(-limit(event.deltaY, -120, 120) * 0.004),
        { x: event.clientX - rect.left - rect.width / 2, y: event.clientY - rect.top - (rect.height - 24) / 2 });
    };
    root.addEventListener('wheel', wheel, { passive: false });
    return () => root.removeEventListener('wheel', wheel);
  }, [zoomTo]);

  function beginGesture() {
    const values = [...pointers.current.values()];
    if (!values.length) { gesture.current = null; setDragging(false); return; }
    const a = values[0], b = values[1] || a;
    gesture.current = { origin: current.current, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2,
      distance: values.length > 1 ? Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)) : 0 };
  }
  function pointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as HTMLElement).closest('button,input')) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    event.currentTarget.setPointerCapture(event.pointerId);
    beginGesture(); setDragging(transform.zoom > 1);
  }
  function pointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(event.pointerId) || !gesture.current) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const values = [...pointers.current.values()], a = values[0], b = values[1] || a, start = gesture.current;
    const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
    let next = { ...start.origin, x: start.origin.x + cx - start.x, y: start.origin.y + cy - start.y };
    if (values.length > 1 && start.distance) {
      const zoom = limit(start.origin.zoom * Math.hypot(a.x - b.x, a.y - b.y) / start.distance, 1, 16);
      const rect = event.currentTarget.getBoundingClientRect();
      const ax = start.x - rect.left - rect.width / 2, ay = start.y - rect.top - (rect.height - 24) / 2;
      next = { zoom, x: ax - (ax - start.origin.x) * zoom / start.origin.zoom + cx - start.x,
        y: ay - (ay - start.origin.y) * zoom / start.origin.zoom + cy - start.y };
    }
    setTransform(clamp(next));
  }
  function pointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    beginGesture();
  }
  function moveSplit(clientX: number) {
    const rect = sheetRef.current?.getBoundingClientRect();
    if (rect?.width) setSplit(limit((clientX - rect.left) / rect.width * 100, 0, 100));
  }

  return <div className={`inspection-viewport ${transform.zoom > 1 ? 'can-pan' : ''} ${dragging ? 'is-panning' : ''}`}
    ref={rootRef} tabIndex={0} aria-label="画布检查区域" onPointerDown={pointerDown} onPointerMove={pointerMove}
    onPointerUp={pointerUp} onPointerCancel={pointerUp} onLostPointerCapture={pointerUp}
    onDoubleClick={event => { if (!(event.target as HTMLElement).closest('button,input')) setTransform(FIT); }}
    onKeyDown={event => {
      if (event.target !== event.currentTarget) return;
      if (['+', '=', '-', '0', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) event.preventDefault();
      if (event.key === '+' || event.key === '=') zoomTo(transform.zoom * 1.4);
      if (event.key === '-') zoomTo(transform.zoom / 1.4);
      if (event.key === '0') setTransform(FIT);
      const delta = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] }[event.key];
      if (delta) setTransform(previous => clamp({ ...previous, x: previous.x + delta[0], y: previous.y + delta[1] }));
    }}>
    <div ref={sheetRef} className="inspection-sheet" style={{ width: fitted.width, height: fitted.height,
      transform: `translate(-50%, -50%) translate(${transform.x}px, ${transform.y}px) scale(${transform.zoom})`,
      '--viewer-scale': transform.zoom } as CSSProperties}>
      <canvas ref={canvasRef} style={{ visibility: !width || view === 'source' ? 'hidden' : 'visible' }} aria-label={`${title} 绘画结果`} />
      <img src={source} alt={`${title} 原图`} draggable={false}
        onLoad={event => setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
        style={{ visibility: (width || preview) && view === 'painting' ? 'hidden' : 'visible',
          clipPath: width && view === 'compare' ? `inset(0 ${100 - split}% 0 0)` : undefined }} />
      {preview && view === 'painting' && <img src={preview} alt="生成中的实际笔触预览（近似渲染）" draggable={false} />}
      {width && view === 'compare' && <>
        <span className="comparison-label original">原图</span><span className="comparison-label painted">绘画</span>
        <div className="comparison-divider" style={{ left: `${split}%` }}>
          <button className="comparison-handle" role="slider" aria-label="原图对比位置" aria-orientation="horizontal"
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(split)} aria-valuetext={`原图 ${Math.round(split)}%，绘画 ${Math.round(100 - split)}%`}
            onPointerDown={event => { event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId); moveSplit(event.clientX); }}
            onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) moveSplit(event.clientX); }}
            onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
            onKeyDown={event => {
              event.stopPropagation();
              if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) event.preventDefault();
              if (event.key === 'ArrowLeft') setSplit(value => Math.max(0, value - 2));
              if (event.key === 'ArrowRight') setSplit(value => Math.min(100, value + 2));
              if (event.key === 'Home') setSplit(0);
              if (event.key === 'End') setSplit(100);
            }}><Columns2 size={16} /></button>
        </div>
      </>}
      {width && selecting && <div className="refine-selection-surface" aria-label="拖动框选精修区域"
        onDoubleClick={event => event.stopPropagation()}
        onPointerDown={event => {
          event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId);
          const rect = event.currentTarget.getBoundingClientRect();
          selectionStart.current = [limit(Math.floor((event.clientX - rect.left) / rect.width * imageWidth), 0, imageWidth - 2), limit(Math.floor((event.clientY - rect.top) / rect.height * imageHeight), 0, imageHeight - 2)];
        }} onPointerMove={event => {
          if (!event.currentTarget.hasPointerCapture(event.pointerId) || !selectionStart.current) return;
          event.stopPropagation();
          const rect = event.currentTarget.getBoundingClientRect(), [sx, sy] = selectionStart.current;
          const ex = limit(Math.round((event.clientX - rect.left) / rect.width * imageWidth), 0, imageWidth), ey = limit(Math.round((event.clientY - rect.top) / rect.height * imageHeight), 0, imageHeight);
          const x = Math.min(sx, ex), y = Math.min(sy, ey);
          onSelection?.([x, y, Math.min(imageWidth - x, Math.max(2, Math.abs(ex - sx))), Math.min(imageHeight - y, Math.max(2, Math.abs(ey - sy)))]);
        }} onPointerUp={event => { event.stopPropagation(); selectionStart.current = null; }} onPointerCancel={() => { selectionStart.current = null; }}>
        {selection && <div className="refine-selection-box" style={{left:`${selection[0]/imageWidth*100}%`,top:`${selection[1]/imageHeight*100}%`,width:`${selection[2]/imageWidth*100}%`,height:`${selection[3]/imageHeight*100}%`}} />}
      </div>}
    </div>
    <div className="inspection-controls" aria-label="画布缩放工具">
      <button className="icon-button" aria-label="缩小画布" disabled={transform.zoom <= 1} onClick={() => zoomTo(transform.zoom / 1.4)}><Minus size={15} /></button>
      <output aria-label="画布缩放比例" title="100% 表示原始像素大小">{Math.round(transform.zoom * fit * 100)}%</output>
      <button className="icon-button" aria-label="放大画布" disabled={transform.zoom >= 16} onClick={() => zoomTo(transform.zoom * 1.4)}><Plus size={15} /></button>
      <span className="zoom-separator" />
      <button className="zoom-fit" onClick={() => setTransform(FIT)} title="适应画布（0）"><Maximize size={13} />适应</button>
      <button className="zoom-native" onClick={() => zoomTo(1 / fit)} title="按原始像素查看"><Scan size={13} />1:1</button>
    </div>
    <span className="inspection-hint">{view === 'compare' ? '拖动分界线对比 · ' : ''}{transform.zoom > 1 ? '拖动画面 · 双击复位' : '滚轮缩放 · 双指缩放'}</span>
  </div>;
}
