"use client";

import { useEffect } from "react";

/**
 * 全局登录守卫。
 *
 * 设计要点：**不阻塞渲染**。早期版本在等待 /api/me 时返回"正在校验会话…"，
 * 结果每个页面的 SSR 输出都变成这句占位，用户每次都看到一次闪烁，
 * 而且搜索引擎/截图拿到的也是空白页。
 * 现在改为始终渲染子节点，鉴权在后台进行，只有确认未登录才跳转。
 */
export default function AuthGate({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.location.pathname === "/login") return;

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/me", { cache: "no-store" });
        if (cancelled) return;
        if (res.status === 401) {
          const next = encodeURIComponent(window.location.pathname);
          window.location.href = `/login?next=${next}`;
          return;
        }
        if (!res.ok) return;
        const data = (await res.json()) as { user: string | null; auth_enabled: boolean };
        if (data.auth_enabled && !data.user) {
          const next = encodeURIComponent(window.location.pathname);
          window.location.href = `/login?next=${next}`;
        }
      } catch {
        /* 网络异常时不打扰用户，接口层会给出各自错误提示 */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return <>{children}</>;
}
