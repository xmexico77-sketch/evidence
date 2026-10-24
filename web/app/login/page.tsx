"use client";

import { useCallback, useState } from "react";

export default function LoginPage() {
  const [username, setUsername] = useState("reviewer");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(res.status === 401 ? "账号或密码错误" : text.slice(0, 120));
      }
      const next =
        new URLSearchParams(window.location.search).get("next") || "/";
      window.location.href = next.startsWith("/") ? next : "/";
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [busy, password, username]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
      }}
    >
      <div className="card" style={{ width: 360 }}>
        <div className="brand" style={{ marginBottom: 6 }}>
          <strong>证源</strong>
          <span>Evidence</span>
        </div>
        <p className="dim" style={{ fontSize: 12.5, margin: "0 0 18px" }}>
          科研助手 Agent · 请使用比赛提供的账号登录
        </p>

        <label className="section-title" style={{ display: "block", marginBottom: 6 }}>
          账号
        </label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={{
            width: "100%",
            background: "var(--bg-raise)",
            border: "1px solid var(--line)",
            borderRadius: 8,
            padding: "9px 12px",
            color: "var(--fg)",
            marginBottom: 12,
          }}
        />

        <label className="section-title" style={{ display: "block", marginBottom: 6 }}>
          密码
        </label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
          }}
          style={{
            width: "100%",
            background: "var(--bg-raise)",
            border: "1px solid var(--line)",
            borderRadius: 8,
            padding: "9px 12px",
            color: "var(--fg)",
            marginBottom: 16,
          }}
        />

        {err && (
          <div style={{ color: "var(--bad)", fontSize: 12.5, marginBottom: 12 }}>{err}</div>
        )}

        <button
          onClick={() => void submit()}
          disabled={busy}
          style={{
            width: "100%",
            background: "var(--accent)",
            border: "none",
            borderRadius: 8,
            padding: "10px 0",
            fontWeight: 640,
            color: "#05121f",
          }}
        >
          {busy ? "登录中…" : "登录"}
        </button>
      </div>
    </div>
  );
}
