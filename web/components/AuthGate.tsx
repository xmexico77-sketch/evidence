"use client";

import { useEffect, useState } from "react";

/**
 * 全局登录守卫。
 *
 * AUTH_ENABLED=0 时后端直接放行，这里什么都不做；
 * 开启后若 /api/me 拿不到用户，跳转到 /login 并带上回跳地址。
 */
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.location.pathname === "/login") {
      setReady(true);
      return;
    }
    (async () => {
      try {
        const res = await fetch("/api/me", { cache: "no-store" });
        if (res.ok) {
          const data = (await res.json()) as { user: string | null; auth_enabled: boolean };
          if (!data.auth_enabled || data.user) {
            setReady(true);
            return;
          }
        }
        if (res.status === 401) {
          const next = encodeURIComponent(window.location.pathname);
          window.location.href = `/login?next=${next}`;
          return;
        }
        // 网络异常时不要卡死页面
        setReady(true);
      } catch {
        setReady(true);
      }
    })();
  }, []);

  if (!ready) return <div className="empty" style={{ padding: 40 }}>正在校验会话…</div>;
  return <>{children}</>;
}
