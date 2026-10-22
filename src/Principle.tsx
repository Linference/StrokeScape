import { useState } from 'react';
import { ArrowRight, Check, Cpu, Image, Layers3, Route, ScanLine, Timer, Zap } from 'lucide-react';

const steps = [
  { icon: Image, name: '读取原图', en: 'SOURCE', title: '所有笔触，都从原图出发。', description: '读取像素颜色，校正照片方向，并按画布尺寸缩放。透明区域合成到纸色背景。', detail: '原图提供颜色与结构依据，结果可以追溯。' },
  { icon: ScanLine, name: '感知结构', en: 'ANALYZE', title: '找到画面里，看不见的方向。', description: '用 Sobel 梯度寻找明暗变化，再用结构张量估计局部方向与方向一致性，让笔触顺着边缘、发丝和衣褶延伸。', detail: 'CuPy 可选加速这一阶段的密集数组运算。' },
  { icon: Layers3, name: '生成笔触', en: 'PAINT', title: '从大色块，走向微小细节。', description: '依次铺底、塑形、勾线、补充细节。反复比较当前画布和原图，优先采样误差较大的区域，再沿结构方向生成路径与颜色。', detail: '当前实现为残差引导采样；候选笔触的增益优化仍有研究空间。' },
  { icon: Timer, name: '安排时间', en: 'SEQUENCE', title: '每一笔，都有属于它的时刻。', description: '根据路径长度与图层分配持续时间，上一笔结束后下一笔才开始，图层之间留出短暂停顿。', detail: '保存路径、颜色、宽度、透明度、开始时间与持续时间。' },
  { icon: Route, name: '播放与导出', en: 'RENDER', title: '把静态图像，展开为绘画过程。', description: 'Canvas 按时间逐步画出路径，累计保存已完成的笔触；HTML 保留交互，视频可以直接录制画布，也可选择逐帧导出。', detail: '实时录制只记录画布，预览、HTML 和视频共用绘画渲染代码。' },
];

export default function Principle() {
  const [selected, setSelected] = useState(0);
  const step = steps[selected];
  const Icon = step.icon;
  return <div className="principle-content">
    <div className="principle-flow" aria-label="绘画生成流程">{steps.map((item, index) => <button key={item.en} className={selected === index ? 'selected' : ''} onClick={() => setSelected(index)} aria-pressed={selected === index}>
      <span>{index < selected ? <Check size={18} /> : <item.icon size={18} />}</span><strong>{item.name}</strong><small>{item.en}</small>{index < 4 && <ArrowRight className="principle-arrow" size={12} />}
    </button>)}</div>
    <div className="principle-detail" key={selected}><div className="principle-step-label"><Icon size={17} />STEP 0{selected + 1}</div><h3>{step.title}</h3><p>{step.description}</p><small>{step.detail}</small></div>
    <div className="cupy-explainer"><div className="cupy-symbol"><Cpu size={21} /><ArrowRight size={13} /><Zap size={21} /></div><div><strong>CuPy 是什么？</strong><p>可以把它理解为 NumPy 的 GPU 版本：让兼容的数组运算在 NVIDIA 显卡上执行。它是可选的计算加速库；未安装时，CPU 仍可完成绘画。</p></div></div>
  </div>;
}
