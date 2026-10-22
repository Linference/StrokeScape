import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpRight, Brush, Check, CheckCircle2,
  ChevronDown, ChevronRight, CircleHelp, Clock3, Cpu, Download, Expand, Feather,
  FileImage, FolderOpen, Gauge, ImagePlus, Layers3, Leaf, LoaderCircle, Maximize2,
  Monitor, Mountain, Palette, Pause, Play, Plus, RefreshCw, RotateCcw,
  Settings2, ShieldCheck, SkipBack, SkipForward, SlidersHorizontal, Sparkles,
  Upload, Video, WandSparkles, Waves, Workflow, X, Zap, Sun, Moon, Search, PanelLeftClose, PanelLeftOpen,
} from 'lucide-react';
import { api, jsonPost } from './api';
import Principle from './Principle';
import type { Device, Hardware, Preset, Renderer, Settings, Task, Work } from './types';

type Page = 'studio' | 'library' | 'hardware';
const PRESETS: { id: Preset; name: string; count: number; hint: string; maxEdge: number; duration: number }[] = [
  { id: 'sketch', name: '速写', count: 18000, hint: '快速呈现结构', maxEdge: 960, duration: 90 },
  { id: 'standard', name: '标准', count: 60000, hint: '兼顾结构与细节', maxEdge: 1440, duration: 180 },
  { id: 'fine', name: '精细', count: 150000, hint: '高密度细节重构', maxEdge: 1920, duration: 300 },
];
const LAYERS = [
  { name: '铺底', en: 'BASE', desc: '落下颜色，建立明暗', color: '#8eaaa3', icon: Palette },
  { name: '塑形', en: 'FORM', desc: '沿着结构，勾勒形体', color: '#c8b58e', icon: Mountain },
  { name: '勾线', en: 'LINE', desc: '提炼轮廓，描出骨架', color: '#c29073', icon: Feather },
  { name: '细节', en: 'DETAIL', desc: '一笔一画，渐入佳境', color: '#e4d4ae', icon: Sparkles },
];
const busy = (task: Task | null) => !!task && ['queued', 'running', 'cancelling'].includes(task.status);
const formatTime = (ms: number) => {
  const seconds = Math.floor((ms + 0.5) / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
};
const friendlyStatus = (value: string) => ({ done: '已完成', running: '生成中', queued: '排队中', cancelled: '已取消', failed: '生成失败', interrupted: '已中断', cancelling: '正在取消' }[value] || value);

let rendererLoading: Promise<void> | undefined;
function loadRenderer() {
  if (window.StrokeRenderer) return Promise.resolve();
  if (!rendererLoading) rendererLoading = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/renderer.js'; script.onload = () => resolve(); script.onerror = () => { rendererLoading = undefined; reject(new Error('绘画引擎加载失败')); };
    document.head.appendChild(script);
  });
  return rendererLoading;
}

export default function App() {
  const [page, setPage] = useState<Page>('studio');
  const [inspectorTab, setInspectorTab] = useState<'settings' | 'layers'>('settings');
  const [focusMode, setFocusMode] = useState(false);
  const [libraryQuery, setLibraryQuery] = useState('');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => localStorage.getItem('huixu.theme') === 'dark' ? 'dark' : 'light');
  const [hardware, setHardware] = useState<Hardware | null>(null);
  const [hardwareError, setHardwareError] = useState('');
  const [detecting, setDetecting] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [activeId, setActiveId] = useState<string | null>(() => localStorage.getItem('huixu.active'));
  const [work, setWork] = useState<Work | null>(null);
  const [settings, setSettings] = useState<Settings>({ preset: 'standard', duration: 180, device: 'auto', seed: 42 });
  const [file, setFile] = useState<File | null>(null);
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const [title, setTitle] = useState('山间来信');
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null);
  const [connected, setConnected] = useState(true);
  const [view, setView] = useState<'painting' | 'source'>('painting');
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [currentStroke, setCurrentStroke] = useState(0);
  const [currentLayer, setCurrentLayer] = useState(0);
  const [showCursor, setShowCursor] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [modal, setModal] = useState<'export' | 'help' | 'principle' | null>(null);
  const [motion, setMotion] = useState(() => localStorage.getItem('huixu.motion') !== 'off');
  const [fps, setFps] = useState<24 | 30 | 60>(30);
  const [hardwareEncode, setHardwareEncode] = useState(true);
  const [exportMode, setExportMode] = useState<'realtime' | 'frames'>('realtime');
  const [videoSubmitting, setVideoSubmitting] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const rendererRef = useRef<Renderer | null>(null);
  const timeRef = useRef(0);
  const playingRef = useRef(false);
  const workIdRef = useRef<string | null>(null);
  const historyLoadedRef = useRef(false);
  const shellRef = useRef<HTMLDivElement>(null);
  const active = tasks.find(task => task.id === activeId) || null;
  const visibleTasks = tasks.filter(task => task.title.toLocaleLowerCase().includes(libraryQuery.trim().toLocaleLowerCase()));
  const preset = PRESETS.find(p => p.id === settings.preset)!;
  const targetBudget = settings.budget ?? preset.count;
  const budgetValid = Number.isInteger(targetBudget) && targetBudget >= 200 && targetBudget <= 200000;
  const estimatedLayers = [0.08, 0.2, 0.12].map(ratio => Math.round(Math.min(targetBudget, 30000) * ratio));
  estimatedLayers.push(targetBudget - estimatedLayers.reduce((sum, count) => sum + count, 0));
  const source = localPreview || (activeId ? `/api/tasks/${activeId}/source` : '/api/sample');
  const duration = work?.durationMs || settings.duration * 1000;
  const videoState = active?.export_state;
  const exporting = ['queued', 'running'].includes(videoState?.status || '');
  const layerDurations = useMemo(() => {
    if (!work) return [8, 20, 12, 60];
    const result = [0, 0, 0, 0];
    for (const stroke of work.strokes) result[stroke.l] += stroke.dt;
    return result;
  }, [work]);

  const notify = useCallback((text: string, error = false) => setNotice({ text, error }), []);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(null), notice.error ? 9000 : 4500); return () => clearTimeout(timer); }, [notice]);
  const detectHardware = useCallback(async (refresh = false) => {
    setDetecting(true); setHardwareError('');
    try { setHardware(await api<Hardware>(`/hardware${refresh ? '?refresh=true' : ''}`)); }
    catch (error) { setHardwareError((error as Error).message); }
    finally { setDetecting(false); }
  }, []);
  useEffect(() => { void detectHardware(); }, [detectHardware]);
  useEffect(() => { localStorage.setItem('huixu.motion', motion ? 'on' : 'off'); }, [motion]);
  useEffect(() => {
    localStorage.setItem('huixu.theme', theme);
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f6f6f9' : '#18191d');
  }, [theme]);


  const refreshTasks = useCallback(async () => {
    try {
      const result = await api<Task[]>('/tasks');
      setTasks(result); setConnected(true);
      if (!historyLoadedRef.current) {
        setActiveId(current => current && !result.some(task => task.id === current) ? null : current);
        historyLoadedRef.current = true;
      }
    }
    catch { setConnected(false); }
  }, []);
  useEffect(() => { void refreshTasks(); const timer = setInterval(() => void refreshTasks(), 1400); return () => clearInterval(timer); }, [refreshTasks]);
  useEffect(() => {
    if (activeId) localStorage.setItem('huixu.active', activeId);
    else localStorage.removeItem('huixu.active');
  }, [activeId]);
  useEffect(() => {
    if (page !== 'studio' || !activeId || active?.status !== 'done' || workIdRef.current === activeId) return;
    let disposed = false;
    api<Work>(`/tasks/${activeId}/work`).then(result => {
      if (disposed) return;
      result.durationMs = Math.round(result.durationMs);
      // Historical works retain their actual budget even after defaults change.
      result.settings = { ...result.settings, budget: result.strokes.length,
        maxEdge: result.settings.maxEdge || Math.max(result.width, result.height) };
      workIdRef.current = activeId; setWork(result); setSettings(result.settings);
      setTime(0); timeRef.current = 0; setPlaying(false);
    }).catch(error => { if (!disposed) notify(error.message, true); });
    return () => { disposed = true; };
  }, [activeId, active?.status, notify, page]);
  useEffect(() => { if (active) setTitle(active.title); }, [active?.id]);

  useEffect(() => {
    if (!work || !canvasRef.current || page !== 'studio') return;
    let disposed = false;
    loadRenderer().then(() => {
      if (disposed || !canvasRef.current) return;
      const renderer = new window.StrokeRenderer(canvasRef.current, work);
      rendererRef.current = renderer;
      const state = renderer.render(timeRef.current, showCursor);
      setCurrentStroke(state.completed); setCurrentLayer(state.layer);
    }).catch(error => notify(error.message, true));
    return () => { disposed = true; rendererRef.current?.dispose(); rendererRef.current = null; };
  }, [work, page, notify]);
  useEffect(() => {
    timeRef.current = time;
    const result = rendererRef.current?.render(time, showCursor);
    if (result) { setCurrentStroke(result.completed); setCurrentLayer(result.layer); }
  }, [time, showCursor, work, page]);
  useEffect(() => { playingRef.current = playing; }, [playing]);
  useEffect(() => {
    let request = 0, last = performance.now();
    const tick = (now: number) => {
      if (playingRef.current && work && page === 'studio') {
        const next = Math.min(work.durationMs, timeRef.current + (now - last) * speed);
        timeRef.current = next; setTime(next);
        if (next >= work.durationMs) setPlaying(false);
      }
      last = now; request = requestAnimationFrame(tick);
    };
    request = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(request);
  }, [work, speed, page]);
  useEffect(() => () => { if (localPreview) URL.revokeObjectURL(localPreview); }, [localPreview]);
  useEffect(() => {
    if (!modal) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const selector = 'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),[tabindex="0"]';
    dialog?.querySelector<HTMLElement>(selector)?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setModal(null); return; }
      if (event.key !== 'Tab' || !dialog) return;
      const nodes = Array.from(dialog.querySelectorAll<HTMLElement>(selector));
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', trap);
    return () => { document.removeEventListener('keydown', trap); previous?.focus(); };
  }, [modal]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || !work || page !== 'studio' || modal || ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes((event.target as HTMLElement).tagName)) return;
      event.preventDefault(); togglePlay();
    };
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key);
  }, [work, page, modal]);

  function reset() {
    setPlaying(false); setActiveId(null); setWork(null); workIdRef.current = null; setFile(null); setLocalPreview(null);
    setTitle('山间来信'); setTime(0); setCurrentStroke(0); setCurrentLayer(0); setPage('studio'); setView('painting');
  }
  function selectFile(next: File) {
    if (!/\.(png|jpe?g|webp|bmp|tiff?)$/i.test(next.name) && !next.type.startsWith('image/')) { notify('请选择 PNG、JPEG 或 WebP 图片', true); return; }
    if (next.size > 24 * 1024 * 1024) { notify('图片请控制在 24 MB 以内', true); return; }
    reset(); setFile(next); setTitle(next.name.replace(/\.[^.]+$/, '')); setLocalPreview(URL.createObjectURL(next));
  }
  function openTask(task: Task) {
    setPlaying(false); setWork(null); workIdRef.current = null; setLocalPreview(null); setFile(null);
    setTime(0); setActiveId(task.id); setSettings(task.settings); setTitle(task.title); setView('painting'); setPage('studio');
  }
  async function generate() {
    if (submitting || busy(active)) return;
    if (!budgetValid) {
      notify('笔触预算请输入 200 到 200,000 之间的整数', true); return;
    }
    setSubmitting(true); setPlaying(false);
    try {
      let task: Task;
      if (file) {
        const form = new FormData(); form.append('file', file); form.append('options', JSON.stringify(settings));
        task = await api<Task>('/tasks', { method: 'POST', body: form });
      } else if (activeId) task = await api<Task>(`/tasks/${activeId}/retry`, jsonPost(settings));
      else task = await api<Task>('/tasks/sample', jsonPost(settings));
      setWork(null); workIdRef.current = null; setTime(0); setCurrentStroke(0); setCurrentLayer(0);
      setTasks(previous => [task, ...previous]); setActiveId(task.id); setLocalPreview(null); setFile(null); setView('painting');
      notify('笔触生成已开始，可以在作品集中查看进度');
    } catch (error) { notify((error as Error).message, true); }
    finally { setSubmitting(false); }
  }
  function togglePlay() {
    if (!work) return;
    if (timeRef.current >= work.durationMs) { timeRef.current = 0; setTime(0); }
    setView('painting'); setPlaying(previous => !previous);
  }
  function seek(next: number) { setTime(Math.max(0, Math.min(duration, next))); }
  function step(forward: boolean) {
    if (!work) return;
    setPlaying(false); setView('painting');
    if (forward) {
      const next = work.strokes.find(s => s.s + s.dt > time + 0.001);
      if (next) seek(next.s + next.dt);
    } else {
      for (let index = work.strokes.length - 1; index >= 0; index--) {
        if (work.strokes[index].s < time - 0.001) { seek(work.strokes[index].s); return; }
      }
      seek(0);
    }
  }
  async function cancelGeneration() {
    if (!activeId) return;
    try { const task = await api<Task>(`/tasks/${activeId}/cancel`, { method: 'POST' }); setTasks(previous => previous.map(t => t.id === task.id ? task : t)); }
    catch (error) { notify((error as Error).message, true); }
  }
  async function exportVideo() {
    if (!activeId || videoSubmitting) return;
    setVideoSubmitting(true);
    try {
      const task = await api<Task>(`/tasks/${activeId}/video`, jsonPost({ fps, hardware: hardwareEncode, mode: exportMode }));
      setTasks(previous => previous.map(t => t.id === task.id ? task : t)); notify('视频导出已开始，可继续使用工作台');
    } catch (error) { notify((error as Error).message, true); }
    finally { setVideoSubmitting(false); }
  }
  async function cancelExport() {
    if (!activeId) return;
    try { const task = await api<Task>(`/tasks/${activeId}/video/cancel`, { method: 'POST' }); setTasks(previous => previous.map(t => t.id === task.id ? task : t)); notify('正在停止视频导出'); }
    catch (error) { notify((error as Error).message, true); }
  }
  function jumpLayer(layer: number) {
    if (!work) return;
    const stroke = work.strokes.find(s => s.l === layer);
    if (stroke) { setPlaying(false); setView('painting'); seek(stroke.s); }
  }

  return <div className={`app-shell page-${page} ${motion ? 'motion-on' : 'motion-off'}`} ref={shellRef}>
    <aside className="rail">
      <button className="brand-mark" onClick={() => setPage('studio')} aria-label="绘序成境工作台"><Feather size={27} strokeWidth={1.5} /></button>
      <div className="rail-nav">
        <button className={page === 'studio' ? 'rail-item active' : 'rail-item'} onClick={() => setPage('studio')}><Brush size={21} /><span>工作台</span></button>
        <button className={page === 'library' ? 'rail-item active' : 'rail-item'} onClick={() => { setPage('library'); setPlaying(false); }}><FolderOpen size={21} /><span>作品集</span></button>
        <button className={page === 'hardware' ? 'rail-item active' : 'rail-item'} onClick={() => { setPage('hardware'); setPlaying(false); }}><Cpu size={21} /><span>设备</span></button>
        <button className="rail-item principle-nav" onClick={() => setModal('principle')}><Workflow size={21} /><span>原理</span></button>
      </div>
      <div className="rail-bottom"><button className="rail-item" onClick={() => setModal('help')}><CircleHelp size={21} /><span>使用指南</span></button><div className="rail-avatar">绘</div></div>
    </aside>

    <div className="app-main">
      <header className="topbar">
        <div className="wordmark">绘序成境<span className="wordmark-divider" /><span className="wordmark-en">StrokeScape</span><span className="version">本地创作空间</span></div>
        <div className="topbar-right"><span className="local-status"><span className={`connection-dot ${!connected ? 'offline' : ''}`} />{connected ? '已连接本机' : '连接已断开'}</span><span className="topbar-separator" /><button className={`motion-toggle ${motion ? 'enabled' : ''}`} onClick={() => setMotion(value => !value)} aria-pressed={motion} aria-label="界面动效" title="界面动效"><Sparkles size={16} /></button><button className="icon-button theme-toggle" aria-label={theme === 'light' ? '切换深色外观' : '切换浅色外观'} title={theme === 'light' ? '切换深色外观' : '切换浅色外观'} onClick={() => setTheme(value => value === 'light' ? 'dark' : 'light')}>{theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}</button><button className="icon-button top-help" aria-label="使用指南" onClick={() => setModal('help')}><CircleHelp size={18} /></button></div>
      </header>

      <main className="main-content">
        <section className="page-heading">
          <div><div className="eyebrow">{page === 'studio' ? 'WORKSPACE' : page === 'library' ? 'YOUR COLLECTION' : 'PERFORMANCE'}</div>
            <h1>{page === 'studio' ? '一张图片，一段绘画。' : page === 'library' ? '你的灵感收藏室' : '让创作，顺畅发生。'}</h1>
            <p>{page === 'studio' ? '从静止的瞬间，到一笔一画的过程。' : page === 'library' ? '回到每一幅作品，继续探索它的绘画过程。' : '了解这台电脑的图像计算与视频导出能力。'}</p>
          </div>
          <div className="heading-actions"><button className="button secondary" onClick={reset}><Plus size={17} />新建作品</button><button className="button primary" disabled={!work || busy(active)} onClick={() => setModal('export')}><ArrowDownToLine size={17} />导出作品<ChevronDown size={14} /></button></div>
        </section>

        {!connected && <div className="connection-banner"><Monitor size={17} />本地服务连接已断开。请确认启动窗口仍在运行，恢复后会自动重新连接。</div>}

        {page === 'hardware' && hardware?.cuda.errorDetail && <section className="gpu-diagnostic panel" role="status">
          <div><Zap size={19} /><strong>{hardware.cuda.reason}</strong></div>
          <p>{hardware.cuda.hint}</p>
          <details><summary>查看详细错误 · {hardware.cuda.errorType}</summary><pre>{hardware.cuda.errorDetail}</pre></details>
        </section>}

        {page === 'studio' && <div className={`workspace-grid inspector-${inspectorTab} ${focusMode ? 'focus-mode' : ''}`}>
          <div className="inspector-tabs" role="tablist" aria-label="创作面板"><button id="settings-tab" role="tab" aria-selected={inspectorTab === 'settings'} aria-controls="settings-panel" onClick={() => setInspectorTab('settings')}><SlidersHorizontal size={15} />创作设置</button><button id="layers-tab" role="tab" aria-selected={inspectorTab === 'layers'} aria-controls="layers-panel" onClick={() => setInspectorTab('layers')}><Layers3 size={15} />绘制图层</button></div>
          <section className="settings-panel panel" id="settings-panel" role="tabpanel" aria-labelledby="settings-tab" hidden={inspectorTab !== 'settings'}>
            <div className="panel-title"><SlidersHorizontal size={16} /><h2>创作设置</h2><span>01</span></div>
            <div className="settings-body">
              <div className="section-label"><span>原始图片</span><span className="tiny-tag">本地</span></div>
              <button className={`upload-zone ${dragging ? 'dragging' : ''}`} onClick={() => inputRef.current?.click()}
                onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
                onDrop={event => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files[0]) selectFile(event.dataTransfer.files[0]); }}>
                <div className="upload-preview"><img src={source} alt="当前原始图片缩略图" /><span><ImagePlus size={17} /></span></div>
                <span className="upload-title">{title}</span><span className="upload-hint">点击替换，或拖入图片</span>
              </button>
              <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff" hidden onChange={event => { if (event.target.files?.[0]) selectFile(event.target.files[0]); event.target.value = ''; }} />
              <div className="file-formats">PNG / JPG / WEBP <span>≤ 24 MB</span></div>

              <div className="section-label preset-label"><span>绘制精度</span><span className="muted">笔触预算</span></div>
              <div className="preset-options" role="radiogroup" aria-label="绘制精度">
                {PRESETS.map((item, index) => <button key={item.id} role="radio" aria-checked={settings.preset === item.id} className={`preset-option ${settings.preset === item.id ? 'selected' : ''}`} onClick={() => setSettings(previous => ({ ...previous, preset: item.id, budget: undefined, maxEdge: undefined, duration: item.duration }))}>
                  <span className={`preset-symbol preset-${index}`}><Brush size={18} strokeWidth={index === 2 ? 2 : 1.5} /></span><span className="preset-info"><strong>{item.name}</strong><small>{item.hint}</small></span><span className="preset-number">{item.count / 10000}<small>万笔</small></span><span className="radio-dot">{settings.preset === item.id && <Check size={10} />}</span>
                </button>)}
              </div>

              <div className="stroke-budget">
                <div className="section-label"><label htmlFor="stroke-budget">自定义笔触数量</label><span className="budget-mode">{settings.budget === undefined ? '跟随预设' : '已自定义'}</span></div>
                <div className="budget-input-wrap"><input id="stroke-budget" type="number" inputMode="numeric" min={200} max={200000} step={1} placeholder={String(preset.count)} value={settings.budget ?? ''} aria-invalid={!budgetValid} aria-describedby="stroke-budget-hint" onChange={event => setSettings(previous => ({ ...previous, budget: event.target.value === '' ? undefined : Number(event.target.value) }))} /><span>笔</span></div>
                <div className="budget-current"><span>本次目标 <strong>{targetBudget.toLocaleString()}</strong> 笔</span>{settings.budget !== undefined && <button className="text-button" onClick={() => setSettings(previous => ({ ...previous, budget: undefined }))}>恢复预设</button>}</div>
                <p id="stroke-budget-hint" className={budgetValid ? 'budget-hint' : 'budget-hint budget-error'}>{budgetValid ? '支持 200–200,000 笔，留空使用预设。' : '请输入 200 到 200,000 之间的整数。'}</p>
              </div>

              <div className="section-label duration-label"><span>动画时长</span><strong>{settings.duration}<small> 秒</small></strong></div>
              <input className="range duration-range" aria-label="动画时长（秒）" type="range" min={15} max={600} step={5} value={settings.duration} onChange={event => setSettings(previous => ({ ...previous, duration: Number(event.target.value) }))} style={{ '--range-progress': `${(settings.duration - 15) / 585 * 100}%` } as React.CSSProperties} />
              <div className="range-labels"><span>15 秒</span><span>10 分钟</span></div>

              <div className="section-label device-label"><span>计算设备</span><button className="text-icon" aria-label="查看设备信息" onClick={() => setPage('hardware')}><CircleHelp size={13} /></button></div>
              <div className="segmented device-options">{(['auto', 'cpu', 'gpu'] as Device[]).map(device => <button key={device} className={settings.device === device ? 'selected' : ''} disabled={device === 'gpu' && !hardware?.cuda.available} onClick={() => setSettings(previous => ({ ...previous, device }))}>{device === 'auto' ? '自动' : device.toUpperCase()}</button>)}</div>
              <div className="device-note">{detecting ? <LoaderCircle size={12} className="spin" /> : <span className="mini-dot" />}<span>{detecting ? '正在检测硬件能力' : hardware?.cuda.available ? 'CUDA 可用 · 自动按任务选择' : 'CPU 就绪 · 支持完整绘制'}</span></div>
              <details className="advanced-settings"><summary><Settings2 size={12} />画布设置<span>{settings.maxEdge || preset.maxEdge} px</span></summary><div className="advanced-fields"><label>最长边上限<select value={settings.maxEdge || preset.maxEdge} onChange={event => setSettings(previous => ({ ...previous, maxEdge: Number(event.target.value) }))}>{Array.from(new Set([960, 1440, 1920, 2560, settings.maxEdge || preset.maxEdge])).sort((a, b) => a - b).map(edge => <option key={edge} value={edge}>{edge} px</option>)}</select></label><p>更多笔触会增加数据量与播放开销。原图不会放大。30 FPS 下平均每帧约 {(targetBudget / settings.duration / 30).toFixed(1)} 笔。</p></div></details>
            </div>
            <div className="inspector-footer">
              {busy(active) ? <button className="button generate-button cancel-button" onClick={() => void cancelGeneration()} disabled={active?.status === 'cancelling'}><X size={17} />{active?.status === 'cancelling' ? '正在停止…' : '取消生成'}</button> : <button className="button generate-button" disabled={submitting || !connected || detecting || !budgetValid} onClick={() => void generate()}>{submitting ? <LoaderCircle size={17} className="spin" /> : <WandSparkles size={17} />}{submitting ? '准备画布…' : work ? '重新生成' : '开始绘制'}<ArrowRight size={17} /></button>}
              <p className="generation-hint"><ShieldCheck size={12} />图片与作品仅保存在这台电脑</p>
            </div>
          </section>

          <section className="canvas-column">
            <div className={`canvas-panel panel ${playing ? 'is-playing' : ''} ${busy(active) ? 'is-generating' : ''}`}>
              <div className="canvas-toolbar"><button className="icon-button inspector-toggle" aria-label={focusMode ? '展开设置面板' : '收起设置面板'} aria-pressed={focusMode} title={focusMode ? '展开设置面板' : '收起设置面板'} onClick={() => setFocusMode(value => !value)}>{focusMode ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</button><div className="canvas-document"><span className="document-dot" /><span>{title}</span><small>{work ? '已生成' : busy(active) ? '生成中' : '待绘制'}</small></div><div className="canvas-tools"><div className="segmented view-toggle"><button className={view === 'painting' ? 'selected' : ''} onClick={() => setView('painting')}>绘画</button><button className={view === 'source' ? 'selected' : ''} onClick={() => setView('source')}>原图</button></div><span className="tool-separator" /><button className="icon-button" aria-label="全屏查看画布" onClick={() => { if (!document.fullscreenElement) void stageRef.current?.requestFullscreen().catch(() => notify('当前窗口不支持全屏查看')); else void document.exitFullscreen(); }}><Maximize2 size={15} /></button></div></div>
              <div className={`canvas-stage ${dragging ? 'dragging' : ''}`} ref={stageRef}
                onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files[0]) selectFile(event.dataTransfer.files[0]); }}>

                <div className="stage-exhibit-label"><span>CANVAS</span><span>{work ? `${work.width} × ${work.height}` : '自由创作，从这里开始'}</span></div>

                <div className="artwork-frame"><img className={`source-artwork ${work && view === 'painting' ? 'hidden' : ''}`} src={source} alt={`${title} 原图`} /><canvas ref={canvasRef} className={!work || view === 'source' ? 'hidden' : ''} /></div>
                {!work && !busy(active) && <div className="sample-tag"><span className="mini-dot" />{active?.status === 'failed' ? '生成未完成' : localPreview || activeId ? '原图预览' : '内置原创示例 · 山间来信'}</div>}
                {busy(active) && <div className="generation-overlay"><div className="generation-card"><span className="generation-brush"><Brush size={26} /></span><h3>正在构建绘画过程</h3><p>{active?.stage}</p><div className="progress-track"><span style={{ width: `${Math.max(2, (active?.progress || 0) * 100)}%` }} /></div><div className="generation-progress"><span>{active?.status === 'queued' ? '排队中' : '正在生成笔触'}</span><strong>{Math.round((active?.progress || 0) * 100)}%</strong></div></div></div>}
                {active && ['failed', 'cancelled', 'interrupted'].includes(active.status) && <div className="stage-error"><CircleHelp size={15} /><span>{active.error || active.stage}</span></div>}
                <div className="stage-watermark"><Feather size={12} />绘序成境</div>
              </div>
              <div className="canvas-status"><span><span className="mini-dot" />{work ? playing ? '正在逐笔绘制' : time >= duration ? '作品已完成' : '画布已就绪' : busy(active) ? '正在准备绘画过程' : '一张图片，无限可能'}</span>{work && <span className="live-stroke-count">{currentStroke.toLocaleString()}<small> / {work.strokes.length.toLocaleString()} 笔</small></span>}<span>{work ? `${work.width} × ${work.height}` : '自适应画布'}</span></div>
            </div>

            <div className="player-panel panel">
              <div className="player-top"><div className="player-controls"><button className="icon-button" disabled={!work} aria-label="从头重播" onClick={() => { setPlaying(false); seek(0); }}><RotateCcw size={17} /></button><button className="icon-button" disabled={!work} aria-label="上一笔" onClick={() => step(false)}><SkipBack size={17} /></button><button className="play-button" disabled={!work} aria-label={playing ? '暂停播放' : '播放绘画'} onClick={togglePlay}>{playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}</button><button className="icon-button" disabled={!work} aria-label="下一笔" onClick={() => step(true)}><SkipForward size={17} /></button><div className="player-clock"><strong>{formatTime(time)}</strong><span>/ {formatTime(duration)}</span></div></div><div className="player-options"><button className={`cursor-toggle ${showCursor ? 'enabled' : ''}`} aria-pressed={showCursor} onClick={() => setShowCursor(value => !value)}><Feather size={13} /><span>笔尖</span></button><select aria-label="播放速度" value={speed} onChange={event => setSpeed(Number(event.target.value))}>{[0.25, 0.5, 1, 1.5, 2, 4].map(value => <option key={value} value={value}>{value}×</option>)}</select></div></div>
              <div className="timeline-wrap"><div className="timeline-layer-bands">{LAYERS.map((layer, index) => <div key={layer.en} style={{ flex: Math.max(1, layerDurations[index]), background: layer.color }} />)}</div><input className="timeline-input" aria-label="绘画播放进度" type="range" min="0" max={duration} step="1" value={time} disabled={!work} onChange={event => seek(Number(event.target.value))} /></div>
              <div className="timeline-labels"><span>铺底</span><span>塑形</span><span>勾线</span><span>细节</span></div>
            </div>
            <div className="canvas-footnote"><span><ShieldCheck size={13} />离线创作，安心落笔</span><span>空格播放 / 暂停<span className="keyboard-key">␣</span></span></div>
          </section>

          <aside className="details-column" id="layers-panel" role="tabpanel" aria-labelledby="layers-tab" hidden={inspectorTab !== 'layers'}>
            <section className="layers-panel panel"><div className="panel-title"><Layers3 size={16} /><h2>绘制图层</h2><span>04</span></div><p className="layers-intro">从整体到细节，让画面有序生长。</p><div className="layer-list">{LAYERS.map((layer, index) => {
              const Icon = layer.icon;
              const layerCount = work?.layers[index] ?? estimatedLayers[index];
              const complete = !!work && (currentLayer > index || time >= duration);
              return <button className={`layer-row ${work && currentLayer === index && time < duration ? 'current' : ''}`} key={layer.en} disabled={!work} onClick={() => jumpLayer(index)}><span className="layer-connector" /><span className="layer-icon" style={{ color: layer.color }}><Icon size={18} strokeWidth={1.5} /></span><span className="layer-text"><span className="layer-heading"><strong>{layer.name}</strong><small>{layer.en}</small>{complete && <CheckCircle2 size={12} />}</span><span className="layer-description">{layer.desc}</span><span className="layer-count">{layerCount.toLocaleString()} 笔 {!work && <small>预计</small>}</span></span><ChevronRight className="layer-arrow" size={13} /></button>;
            })}</div><div className="serial-note"><span className="mini-dot" />严格串行 · 每一笔都有自己的时间</div></section>
            <section className="summary-panel panel"><div className="section-label"><span>作品概览</span><Gauge size={15} /></div><div className="summary-stats"><div><small>{work ? '实际笔触' : '目标笔触'}</small><strong>{(work?.stats.count ?? targetBudget).toLocaleString()}<span> 笔</span></strong></div><div><small>动画时长</small><strong>{Math.round(duration / 1000)}<span> 秒</span></strong></div></div><div className="summary-meta"><span>生成用时</span><strong>{work ? `${work.stats.computeSeconds} 秒` : '生成后显示'}</strong></div><div className="summary-meta"><span>计算后端</span><strong>{work ? work.stats.backend === 'cuda' ? 'CUDA + CPU' : 'CPU' : '自动检测'}</strong></div>{work?.stats.fallback && <p className="fallback-note">{work.stats.fallback}</p>}</section>

          </aside>
        </div>}

        {page === 'library' && <section className="library-page"><div className="library-heading"><span>全部作品 <b>{tasks.length}</b></span><label className="library-search"><Search size={16} /><input type="search" placeholder="搜索作品名称" aria-label="搜索作品" value={libraryQuery} onChange={event => setLibraryQuery(event.target.value)} /></label><button className="text-button" onClick={() => void refreshTasks()}><RefreshCw size={14} />刷新</button></div>{visibleTasks.length ? <div className="library-grid">{visibleTasks.map(task => <button className="work-card panel" key={task.id} onClick={() => openTask(task)}><div className="work-thumbnail"><img src={`/api/tasks/${task.id}/source`} alt={task.title} /><span className={`task-status ${task.status}`}>{friendlyStatus(task.status)}</span>{busy(task) && <div className="card-progress"><span style={{ width: `${task.progress * 100}%` }} /></div>}</div><div className="work-card-info"><h3>{task.title}</h3><span>{task.stats ? `${task.stats.count.toLocaleString()} 笔` : task.stage}<span>·</span>{task.settings.duration} 秒</span><div><small>{new Date(task.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</small><ArrowUpRight size={16} /></div></div></button>)}</div> : <div className="empty-library panel"><FolderOpen size={44} strokeWidth={1} /><h2>{libraryQuery ? '没有找到匹配的作品' : '第一幅作品，从这里开始'}</h2><p>{libraryQuery ? '试试其他名称，或清空搜索查看全部作品。' : '导入一张图片，把灵感留在自己的收藏室。'}</p><button className="button primary" onClick={reset}><Plus size={17} />开始创作</button></div>}</section>}

        {page === 'hardware' && <section className="hardware-page"><div className="hardware-overview panel"><div className="hardware-title"><span className="hardware-symbol"><Cpu size={30} strokeWidth={1.3} /></span><div><h2>创作设备</h2><p>计算与编码分别检测，按实际能力启用加速。</p></div><button className="button secondary" disabled={detecting} onClick={() => void detectHardware(true)}><RefreshCw size={15} className={detecting ? 'spin' : ''} />{detecting ? '检测中…' : '重新检测'}</button></div>{hardwareError && <div className="error-message">{hardwareError}</div>}<div className="hardware-cards"><div><Cpu size={22} /><small>CPU 计算</small><strong>{hardware ? `${hardware.cpu} 个逻辑处理器` : '正在检测'}</strong><span>图像处理、笔触生成与时序编排</span><b className="capability-badge available"><Check size={12} />完整支持</b></div><div><Zap size={22} /><small>GPU 图像计算</small><strong>{hardware?.cuda.available ? hardware.cuda.name : '使用 CPU 后端'}</strong><span>{hardware?.cuda.available ? `可用显存 ${hardware.cuda.freeMb?.toLocaleString()} MB · 加速结构分析` : hardware?.cuda.reason || '正在进行计算自检'}</span><b className={`capability-badge ${hardware?.cuda.available ? 'available' : ''}`}>{hardware?.cuda.available ? 'CUDA 可用' : '可选加速'}</b></div><div><Video size={22} /><small>视频编码</small><strong>{hardware?.preferredEncoder || (detecting ? '正在试编码' : '未检测到编码器')}</strong><span>{hardware?.encoders.length ? hardware.encoders.join(' / ') : '需要可用的 FFmpeg 编码器'}</span><b className={`capability-badge ${hardware?.encoders.length ? 'available' : ''}`}>{hardware?.encoders.length ? '已通过试编码' : '等待配置'}</b></div></div></div><div className="hardware-lower"><section className="panel adapter-panel"><h3><Monitor size={17} />已识别的显示设备</h3>{hardware?.adapters.length ? hardware.adapters.map((adapter, index) => <div className="adapter-row" key={index}><span className="adapter-icon"><Monitor size={20} /></span><div><strong>{adapter.name}</strong><small>{adapter.memoryMb ? `${adapter.memoryMb.toLocaleString()} MB 显存（设备报告）` : '显存信息未提供'}</small></div></div>) : <p className="muted">{detecting ? '正在读取设备信息…' : '当前环境未提供显示设备信息，CPU 功能可正常使用。'}</p>}</section><section className="panel policy-panel"><h3><Settings2 size={17} />自动选择策略</h3><p><CheckCircle2 size={15} />小图像优先使用 CPU，减少数据传输开销。</p><p><CheckCircle2 size={15} />CUDA 自检通过后，较大图像可使用 GPU。</p><p><CheckCircle2 size={15} />GPU 计算失败时，重新执行 CPU 特征分析。</p><p><CheckCircle2 size={15} />硬件编码失败时，尝试可用的软件编码器。</p><small>第一版 GPU 计算后端支持 NVIDIA CUDA。AMD / Intel 硬件编码能力单独检测。</small></section></div></section>}

        <footer className="page-footer"><span><Feather size={13} />绘序成境<span className="footer-dot">·</span>把时光，画成风景</span><span>结构感知笔触引擎<span className="footer-dot">/</span>本地离线工作台</span></footer>
      </main>
    </div>

    {notice && <div className={`toast ${notice.error ? 'error' : ''}`} role={notice.error ? 'alert' : 'status'}>{notice.error ? <CircleHelp size={18} /> : <CheckCircle2 size={18} />}<span>{notice.text}</span><button className="icon-button" aria-label="关闭通知" onClick={() => setNotice(null)}><X size={16} /></button></div>}

    {modal && <div className="modal-backdrop" onClick={event => { if (event.target === event.currentTarget) setModal(null); }}><section className={`modal panel ${modal === 'principle' ? 'principle-modal' : ''}`} role="dialog" aria-modal="true" aria-label={modal === 'export' ? '导出作品' : modal === 'principle' ? '工作原理' : '使用指南'}><button className="modal-close icon-button" aria-label="关闭对话框" onClick={() => setModal(null)}><X size={20} /></button>
      {modal === 'principle' ? <><span className="modal-symbol"><Workflow size={27} /></span><div className="eyebrow">THE SCIENCE BEHIND THE STROKES</div><h2>一幅画，是怎样发生的？</h2><p className="modal-description">从原图的结构与颜色出发，计算出可以逐笔播放的绘画过程。</p><Principle /></> : modal === 'help' ? <><span className="modal-symbol"><Feather size={28} /></span><div className="eyebrow">A LITTLE GUIDE</div><h2>从图片，到一笔一画。</h2><p className="modal-description">绘序成境将图像转化为有路径、颜色和时间的数字笔触。无需联网，也可以从内置示例开始。</p><div className="guide-steps"><div><b>01</b><span><strong>选择一张图片</strong><small>点击左侧缩略图上传，或直接拖入画布。</small></span></div><div><b>02</b><span><strong>设定你的绘画节奏</strong><small>选择精度、动画时长和计算设备，点击开始绘制。</small></span></div><div><b>03</b><span><strong>看它慢慢成为风景</strong><small>拖动时间轴、逐笔查看，点击图层跳转阶段。</small></span></div><div><b>04</b><span><strong>保存与分享</strong><small>HTML 保留交互；MP4 用于播放与分享。任务会自动保存在作品集。</small></span></div></div><button className="button primary modal-primary" onClick={() => setModal(null)}>开始创作<ArrowRight size={17} /></button></> : <><span className="modal-symbol"><ArrowDownToLine size={27} /></span><div className="eyebrow">LET YOUR CREATION TRAVEL</div><h2>把这一刻，带走。</h2><p className="modal-description">{title} · {work?.stats.count.toLocaleString()} 笔 · {Math.round(duration / 1000)} 秒</p><a className="export-option" href={`/api/tasks/${activeId}/html`} download><span className="export-icon"><FileImage size={24} /></span><span><strong>交互式 HTML</strong><small>单文件离线播放，保留逐笔与时间轴控制</small></span><Download size={19} /></a><div className="video-export-box"><div className="export-option video-option"><span className="export-icon"><Video size={24} /></span><span><strong>MP4 视频</strong><small>直接录制绘画画布，保留完整绘制过程</small></span></div><div className="video-settings"><label>方式<select aria-label="视频导出方式" value={exportMode} disabled={exporting} onChange={event => setExportMode(event.target.value as 'realtime' | 'frames')}><option value="realtime">实时录制</option><option value="frames">逐帧导出</option></select></label><label>帧率<select value={fps} disabled={exporting} onChange={event => setFps(Number(event.target.value) as 24 | 30 | 60)}>{[24, 30, 60].map(value => <option value={value} key={value}>{value} FPS</option>)}</select></label>{exportMode === 'frames' && <label className="checkbox-label"><input type="checkbox" checked={hardwareEncode} disabled={exporting} onChange={event => setHardwareEncode(event.target.checked)} />优先硬件编码</label>}</div><p className="export-mode-note">{exportMode === 'realtime' ? `画布直接录制，预计约 ${Math.round(duration / 1000)} 秒，另需少量封装时间；期间可继续使用电脑。` : '按固定时间逐帧输出，适合需要精确帧率的作品，耗时取决于画面尺寸。'}</p>{exporting && <div className="export-progress"><div className="progress-track"><span style={{ width: `${Math.max(2, (videoState?.progress || 0) * 100)}%` }} /></div><div><span>{videoState?.status === 'queued' ? '等待导出' : videoState?.mode === 'realtime' ? ({ preparing: '正在准备录制', recording: '正在录制画布', packaging: '正在封装 MP4', encoding: '正在转换 MP4' }[videoState.phase || 'preparing'] || '正在完成录制') : `正在导出 · ${videoState?.encoder || ''}`}</span><strong>{Math.round((videoState?.progress || 0) * 100)}%</strong></div></div>}{videoState?.status === 'failed' && <p className="error-message">{videoState.error}</p>}{videoState?.status === 'cancelled' && <p className="muted">导出已取消，可以重新开始。</p>}<div className="export-actions">{exporting ? <button className="button secondary" onClick={() => void cancelExport()}><X size={15} />取消导出</button> : <button className="button primary" disabled={videoSubmitting || !hardware?.ffmpeg || (exportMode === 'frames' && !hardware?.encoders.length)} onClick={() => void exportVideo()}>{videoSubmitting ? <LoaderCircle size={16} className="spin" /> : <Video size={16} />}{videoState?.status === 'done' ? '重新导出' : '生成 MP4'}</button>}{videoState?.status === 'done' && <a className="button secondary" href={`/api/tasks/${activeId}/video`} download><Download size={16} />下载视频</a>}</div></div><div className="export-footnote"><ShieldCheck size={13} />导出在本机完成，不上传图片。视频渲染可能需要一些时间。</div></>}
    </section></div>}
  </div>;
}
