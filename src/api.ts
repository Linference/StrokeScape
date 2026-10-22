export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, init);
  if (!response.ok) {
    let message = `请求未完成（${response.status}）`;
    try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : message; } catch { /* retain status */ }
    throw new Error(message);
  }
  return response.json();
}
export const jsonPost = (value: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
