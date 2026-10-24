"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AskResponse, Health, Paper } from "@/lib/types";

const SAMPLES = [
  "训练用了多少块 GPU，什么型号？",
  "标签平滑的取值是多少？",
  "Transformer 的多头注意力有几个头？",
];

export default function Workbench() {
  const [health, setHealth] = useState<Health | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [offline, setOffline] = useState<string | null>(null);
  const [question, setQuestion] = useState(SAMPLES[0]);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [h, p] = await Promise.all([api.health(), api.papers()]);
        setHealth(h);
        setPapers(p.papers);
      } catch (e) {
        setOffline(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  const ask = useCallback(async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.ask(q));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [question, busy]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>证源</strong>
          <span>Evidence</span>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Link href="/discover" className="pill">
            论文发现
          </Link>
          <Link href="/graph" className="pill">
            引用图谱
          </Link>
        </div>
        <div>
          {health ? (
            <span className="pill ok">● 已连接 · {health.chunks} 块</span>
          ) : (
            <span className="pill bad">● 未连接</span>
          )}
        </div>

        <div>
          <p className="section-title">文献库</p>
          {papers.length === 0 && <div className="empty">暂无文献</div>}
          {papers.map((p) => (
            <Link
              className="paper-row"
              key={p.id}
              href={`/paper/${p.id}`}
              style={{ color: "inherit" }}
            >
              <span className="t">{p.title || p.id}</span>
              <span className="m">
                {p.arxiv_id || p.id} · {p.pages}p · {p.chunks}块
              </span>
            </Link>
          ))}
        </div>

        {health && (
          <div>
            <p className="section-title">模型</p>
            <span className={`pill ${health.llm === "deepseek" ? "ok" : "warn"}`}>
              {health.llm === "deepseek" ? "DeepSeek" : "抽取式替身"}
            </span>
          </div>
        )}
      </aside>

      <main className="main">
        <h1 style={{ fontSize: 20, margin: "0 0 4px" }}>科研问答</h1>
        <p className="dim" style={{ margin: "0 0 20px", fontSize: 13 }}>
          每个结论都带锚点。锚点校验不通过的内容不会被输出。
        </p>

        {offline && (
          <div className="card" style={{ borderColor: "#4d2424" }}>
            <strong className="mono" style={{ color: "var(--bad)" }}>
              后端未连接
            </strong>
            <p className="dim" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
              请先启动 API：<code className="mono">uvicorn app.main:app --port 8000</code>
              <br />
              错误：{offline}
            </p>
          </div>
        )}

        <div className="ask-box">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void ask();
            }}
            placeholder="用中文提问，检索英文论文…"
          />
          <button onClick={() => void ask()} disabled={busy || !question.trim()}>
            {busy ? "检索中…" : "提问"}
          </button>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>
          {SAMPLES.map((s) => (
            <button
              key={s}
              className="pill"
              style={{ background: "transparent" }}
              onClick={() => setQuestion(s)}
            >
              {s}
            </button>
          ))}
        </div>

        {error && (
          <div className="card" style={{ borderColor: "#4d2424", color: "var(--bad)" }}>
            {error}
          </div>
        )}

        {result && (
          <div className="card">
            <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
              <span className={`pill ${result.grounded ? "ok" : "warn"}`}>
                {result.grounded ? "有据" : result.insufficient ? "拒答" : "未通过校验"}
              </span>
              <span className="pill mono">置信度 {result.confidence.toFixed(2)}</span>
              <span className="pill mono">引用 {result.citations.length}</span>
              {result.repaired && <span className="pill warn">已重写一次</span>}
              {result.invalid_markers.length > 0 && (
                <span className="pill bad mono">
                  非法编号 {result.invalid_markers.join(",")}
                </span>
              )}
            </div>

            <div className="answer">{result.answer}</div>

            {result.citations.length > 0 && (
              <div className="cite-list">
                {result.citations.map((c) => (
                  <div className="cite" key={c.marker}>
                    <div className="top">
                      <strong style={{ color: "var(--accent)" }}>{c.marker}</strong>
                      <span>{c.anchor.label}</span>
                      <span className="faint">
                        高亮 {c.anchor.boxes?.length ?? 0} 段
                      </span>
                      <Link
                        href={{
                          pathname: `/paper/${c.anchor.paper_id}`,
                          query: {
                            page: c.anchor.page,
                            box: (c.anchor.boxes?.[0]?.bbox ?? c.anchor.bbox).join(","),
                          },
                        }}
                        style={{ marginLeft: "auto", fontSize: 11.5 }}
                      >
                        在原文中查看 →
                      </Link>
                    </div>
                    <div className="snippet">{c.snippet}…</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
