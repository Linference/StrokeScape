import type { Region, Settings, Work } from './types';

export function BrushControls({settings, onChange}: {settings:Settings;onChange:(settings:Settings)=>void}) {
  const sliders = [{key:'brushScale' as const,name:'笔触粗细',min:.3,max:3,step:.1},{key:'opacityScale' as const,name:'着色强度',min:.2,max:1.5,step:.05},{key:'texture' as const,name:'纹理强度',min:0,max:2,step:.1},{key:'gaps' as const,name:'断续留白',min:0,max:2,step:.1}];
  return <details className="creative-tools"><summary>笔刷与生成策略<span>可调节</span></summary><div className="creative-fields">
    {sliders.map(item=><label key={item.key}>{item.name}<output>{(settings[item.key]??1).toFixed(2)}×</output><input aria-label={item.name} type="range" min={item.min} max={item.max} step={item.step} value={settings[item.key]??1} onChange={event=>onChange({...settings,[item.key]:Number(event.target.value)})}/></label>)}
    <p>重新生成或局部精修时生效。圆笔保留平滑笔形；断续留白作用于铅笔、彩铅和干刷。</p>
    <label className="creative-checkbox"><input type="checkbox" checked={settings.naturalOrder??true} onChange={event=>onChange({...settings,naturalOrder:event.target.checked})}/>自然绘画顺序</label><p>优先衔接邻近区域与相近颜色，每隔一组笔触重新寻找重要区域。</p>
    <label className="creative-checkbox"><input type="checkbox" checked={settings.adaptiveStop??false} onChange={event=>onChange({...settings,adaptiveStop:event.target.checked})}/>细节改善趋缓时自动停止</label><p>开启后笔数为上限；只在细节层检查误差趋势，实际笔数可能更少。</p>
    {settings.adaptiveStop&&<label>停止灵敏度<select aria-label="停止灵敏度" value={settings.stopThreshold??.03} onChange={event=>onChange({...settings,stopThreshold:Number(event.target.value)})}><option value={.01}>保守 · 尽量保留细节</option><option value={.03}>标准</option><option value={.1}>积极 · 优先减少冗余</option></select></label>}
    <button className="text-button" onClick={()=>onChange({...settings,brushScale:1,opacityScale:1,texture:1,gaps:1})}>重置笔刷参数</button>
  </div></details>;
}

export function RefineTools({work,selection,selecting,budget,busy,onSelection,onSelecting,onBudget,onRefine}: {work:Work;selection:Region|null;selecting:boolean;budget:number;busy:boolean;onSelection:(region:Region)=>void;onSelecting:(value:boolean)=>void;onBudget:(value:number)=>void;onRefine:()=>void}) {
  const remaining=500000-work.strokes.length;
  const valid=selection&&selection[0]>=0&&selection[1]>=0&&selection[2]>=2&&selection[3]>=2&&selection[0]+selection[2]<=work.width&&selection[1]+selection[3]<=work.height;
  return <details className="refine-tools panel" open><summary>局部精修<span>保留原作 · 另存新作品</span></summary><div className="refine-body"><div className="refine-instructions"><p>框选后只在选区追加笔触，也可输入像素坐标。关闭框选后可继续缩放拖动。</p><button className={`button ${selecting?'primary':'secondary'}`} aria-pressed={selecting} onClick={()=>onSelecting(!selecting)}>{selecting?'完成框选':'框选精修区域'}</button></div><div className="region-fields">{(['X','Y','宽','高'] as const).map((label,index)=><label key={label}>{label}<input type="number" aria-label={`精修选区${label}`} min={index<2?0:2} max={index%2?work.height:work.width} value={selection?.[index]??0} onChange={event=>{const next=[...(selection??[0,0,work.width,work.height])] as Region;next[index]=Number(event.target.value);onSelection(next);}}/></label>)}</div><div className="refine-submit"><label>追加笔触<input type="number" aria-label="精修追加笔触" min={200} max={Math.min(100000,remaining)} step={100} value={budget} onChange={event=>onBudget(Number(event.target.value))}/></label><button className="button primary" disabled={busy||!valid||!Number.isInteger(budget)||budget<200||budget>Math.min(100000,remaining)} onClick={onRefine}>{busy?'正在提交…':'开始局部精修'}</button></div><small>总笔触上限 500,000；当前可追加 {remaining.toLocaleString()} 笔。采用当前笔刷参数，选区外保持不变。</small></div></details>;
}

export function QualitySummary({work}:{work:Work}) {
  const stats=work.stats;
  if(stats.mae===undefined)return null;
  const curve=stats.errorCurve??[],max=Math.max(1,...curve.map(p=>p.mae));
  return <section className="quality-summary"><div><strong>质量与预算</strong><span>{stats.stoppedEarly?'已提前停止':'已完成预算'}</span></div><dl><div><dt>近似 MAE</dt><dd>{stats.mae.toFixed(2)}</dd></div><div><dt>近似 PSNR</dt><dd>{stats.psnr?.toFixed(2)} dB</dd></div><div><dt>平均落笔间距</dt><dd>{stats.meanJump?.toFixed(1)} px</dd></div></dl>{curve.length>1&&<svg viewBox="0 0 250 55" role="img" aria-label="细节层误差变化曲线"><polyline fill="none" stroke="currentColor" strokeWidth="2" points={curve.map((p,i)=>`${i/(curve.length-1)*246+2},${51-p.mae/max*46}`).join(' ')}/></svg>}<p>{stats.stopReason}。指标来自 OpenCV 反馈画布，与最终 Canvas 渲染存在差异，不能代表审美或动画自然度。</p></section>;
}
