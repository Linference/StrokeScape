export type Preset = 'sketch' | 'standard' | 'fine';
export type Device = 'auto' | 'cpu' | 'gpu';
export type BrushStyle = 'classic' | 'pencil' | 'marker' | 'dry' | 'watercolor' | 'oil' | 'pointillism' | 'colored_pencil';
export type Region = [number, number, number, number];
export interface Settings { preset: Preset; brush?: BrushStyle; duration: number; device: Device; seed: number; budget?: number | null; maxEdge?: number | null; brushScale?: number; opacityScale?: number; texture?: number; gaps?: number; adaptiveStop?: boolean; stopThreshold?: number; naturalOrder?: boolean }
export interface Stroke { p: number[]; c: string; w: number; o: number; l: number; s: number; dt: number; clip?: Region; b?: BrushStyle; seed?: number; tx?: number; g?: number }
export interface Work {
  version: number; width: number; height: number; paper: string; durationMs: number;
  strokes: Stroke[]; layers: number[]; settings: Settings;
  stats: { count: number; computeSeconds: number; backend: string; gpuScope?: string; fallback?: string; seed: number; mae?: number; psnr?: number; meanJump?: number; stoppedEarly?: boolean; stopReason?: string; requestedBudget?: number; addedCount?: number; errorCurve?: {count:number;mae:number;gain:number|null}[] };
}
export interface ExportState { status?: string; progress?: number; encoder?: string; error?: string; seconds?: number; mode?: 'realtime' | 'frames'; phase?: string }
export interface Task {
  id: string; title: string; created_at: string; status: string; progress: number; stage: string;
  settings: Settings; stats: Work['stats'] | null; error: string | null; export_state: ExportState;
  tags?: string[]; deleted_at?: string | null;
}
export interface Hardware {
  adapters: { name: string; memoryMb: number | null }[];
  cuda: { available: boolean; name?: string; freeMb?: number; totalMb?: number; reason?: string; errorType?: string; errorDetail?: string; hint?: string };
  cpu: number; ffmpeg: boolean; encoders: string[]; preferredEncoder: string | null; platform: string;
}
export interface Renderer {
  render(time: number, cursor?: boolean): { completed: number; layer: number; tip: number[] | null };
  dispose(): void;
}
declare global {
  interface Window {
    StrokeRenderer: new (canvas: HTMLCanvasElement, work: Work, options?: { cacheLimit?: number }) => Renderer;
  }
}
