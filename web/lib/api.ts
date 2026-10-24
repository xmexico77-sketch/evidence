/** 极薄的 fetch 封装：统一错误处理，避免每个组件重复写 try/catch。 */

const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${text.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<import("./types").Health>("/api/health"),
  papers: () => request<{ papers: import("./types").Paper[] }>("/api/papers"),
  ask: (question: string, topK = 5) =>
    request<import("./types").AskResponse>("/api/ask", {
      method: "POST",
      body: JSON.stringify({ question, top_k: topK }),
    }),
};
