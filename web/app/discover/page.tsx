"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { Discovery } from "@/lib/types";

const CATEGORIES = ["cs.CL", "cs.CV", "cs.LG", "cs.AI", "cs.IR"];

export default function DiscoverPage() {
  const [items, setItems] = useState<Discovery[]>([]);
  const [query, setQuery] = useState("efficient attention");
  const [category, setCategory] = useState("cs.CL");
  const [mode, setMode] = useState<"search" | "track">("search");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, number>>({});
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(
    async (nextMode: "search" | "track") => {
      setBusy(true);
      setErr(null);
      setNote("正在检索 arXiv 并补全开源实现信息，约需 10–30 秒…");
      try {
        const params = new URLSearchParams({
          category,
          limit: "8",
          enrich: "true",
        });
        if (nextMode === "search" && query.trim()) params.set("q", query.trim());
        const res = await fetch(`/api/discover?${params.toString()}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
        const data = (await res.json()) as { items: Discovery[] };
        setItems(data.items);
        setMode(nextMode);
        setNote(data.items.length === 0 ? "没有新的可推荐论文（可能都已在库中）" : null);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
        setNote(null);
      } finally {
        setBusy(false);
      }
    },
    [category, query],
  );

  useEffect(() => {
    void load("search");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const vote = useCallback(async (id: string, verdict: number) => {
    setFeedback((prev) => ({ ...prev, [id]: verdict }));
    try {
      await fetch("/api/discover/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, verdict }),
      });
    } catch {
      /* 反馈失败不阻塞浏览 */
    }
  }, []);

  const ingest = useCallback(async (id: string) => {
    const btnNote = `正在下载并解析 ${id} …`;
    setNote(btnNote);
    try {
      const res = await fetch("/api/discover/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ arxiv_id: id }),
      });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      const data = (await res.json()) as { paper_id: string; chunks: number };
      setNote(`已入库 ${data.paper_id}（${data.chunks} 块），可在工作台提问`);
    } catch (e) {
      setNote(`入库失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>证源</strong>
          <span>Discover</span>
        </div>
        <Link href="/" className="pill" style={{ alignSelf: "flex-start" }}>
          ← 返回工作台
        </Link>
        <div>
          <p className="section-title">分类</p>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              className={`outline-item ${c === category ? "l1" : ""}`}
              onClick={() => setCategory(c)}
            >
              <span className="txt mono">{c}</span>
            </button>
          ))}
        </div>
        <div>
          <p className="section-title">排序依据</p>
          <div className="dim" style={{ fontSize: 12, lineHeight: 1.7 }}>
            60% 与你文献库的语义相近度
            <br />
            25% 可复现性（有无开源实现）
            <br />
            15% 方向偏好（点赞记录）
          </div>
        </div>
      </aside>

      <main className="main">
        <h1 style={{ fontSize: 20, margin: "0 0 4px" }}>论文发现</h1>
        <p className="dim" style={{ margin: "0 0 18px", fontSize: 13 }}>
          在 arXiv 上检索或追踪新论文，按可复现性加权排序，一键下钻入库。
        </p>

        <div className="ask-box">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void load("search");
            }}
            placeholder="检索词，例如 efficient attention"
          />
          <button onClick={() => void load("search")} disabled={busy}>
            检索
          </button>
          <button
            onClick={() => void load("track")}
            disabled={busy}
            style={{ background: "transparent", color: "var(--fg-dim)", borderColor: "var(--line)" }}
          >
            追踪最新
          </button>
        </div>

        {note && <div className="card" style={{ marginBottom: 14 }}>{note}</div>}
        {err && (
          <div className="card" style={{ borderColor: "#4d2424", color: "var(--bad)" }}>
            {err}
          </div>
        )}

        {items.map((d) => (
          <div className="card" key={d.id} style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
              <strong style={{ fontSize: 14 }}>{d.title}</strong>
            </div>
            <div className="para-meta mono" style={{ marginTop: 4 }}>
              {d.id} · {d.published} · {d.categories}
            </div>
            <div className="dim" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.6 }}>
              {d.summary.slice(0, 260)}…
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <span className="pill mono">score {d.score.toFixed(3)}</span>
              <span className="pill mono">相近 {d.relevance.toFixed(2)}</span>
              <span className={`pill mono ${d.reproducibility >= 0.85 ? "ok" : ""}`}>
                可复现 {d.reproducibility.toFixed(2)}
              </span>
              {d.cited_by > 0 && <span className="pill mono">引用 {d.cited_by}</span>}
              {d.repo && (
                <a className="pill" href={d.repo} target="_blank" rel="noreferrer">
                  代码 ★{d.repo_stars}
                </a>
              )}
              <button
                className="pill"
                style={{ background: "transparent" }}
                onClick={() => void vote(d.id, 1)}
              >
                {feedback[d.id] === 1 ? "已赞" : "👍"}
              </button>
              <button
                className="pill"
                style={{ background: "transparent" }}
                onClick={() => void vote(d.id, -1)}
              >
                {feedback[d.id] === -1 ? "已踩" : "👎"}
              </button>
              <button className="pill" onClick={() => void ingest(d.id)}>
                入库
              </button>
            </div>
            <div className="faint" style={{ fontSize: 11.5, marginTop: 8 }}>
              推荐理由：{d.reason}
            </div>
          </div>
        ))}

        {items.length === 0 && !busy && !note && <div className="empty">暂无推荐</div>}
      </main>
    </div>
  );
}
