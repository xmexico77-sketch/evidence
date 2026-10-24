"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Sidebar } from "@/components/Nav";
import { ErrorCard, Loading } from "@/components/ui";
import type { GraphPayload, GraphStat, ReviewPayload } from "@/lib/types";

const COMMUNITY_COLORS = [
  "#4ea1ff",
  "#35c48a",
  "#e0a33e",
  "#cc79a7",
  "#56b4e9",
  "#d55e00",
  "#9d8cff",
  "#7fb800",
];

export default function GraphPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<unknown>(null);
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [selected, setSelected] = useState<GraphStat | null>(null);
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // ---------- 加载图数据 ----------
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/graph", { cache: "no-store" });
        if (!res.ok) throw new Error(`${res.status} ${res.text}`);
        setPayload((await res.json()) as GraphPayload);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  // ---------- 渲染 ----------
  useEffect(() => {
    if (!payload || !containerRef.current) return;
    let disposed = false;

    (async () => {
      try {
        const cytoscape = (await import("cytoscape")).default;
        if (disposed || !containerRef.current) return;

      const elements = [
        ...payload.nodes.map((n) => ({
          data: {
            ...n.data,
            color: COMMUNITY_COLORS[Math.max(n.data.community, 0) % COMMUNITY_COLORS.length],
          },
        })),
        ...payload.edges,
      ];

      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(color)",
              width: "data(size)",
              height: "data(size)",
              label: "data(label)",
              "font-size": 8,
              "font-family": "ui-monospace, monospace",
              color: "#c9d4e6",
              "text-valign": "bottom",
              "text-margin-y": 6,
              "text-max-width": "120px",
              "text-wrap": "ellipsis",
              "border-width": 1,
              "border-color": "#0b0e14",
              opacity: 0.92,
            },
          },
          {
            selector: "node[?is_foundational]",
            style: { "border-width": 3, "border-color": "#ffd040" },
          },
          {
            selector: "edge",
            style: {
              width: 1,
              "line-color": "#2a3550",
              "target-arrow-color": "#3a4a63",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              "arrow-scale": 0.7,
              opacity: 0.55,
            },
          },
          { selector: "node:selected", style: { "border-width": 4, "border-color": "#fff" } },
        ],
        layout: {
          name: "cose",
          animate: false,
          nodeRepulsion: () => 12000,
          idealEdgeLength: () => 110,
          nodeOverlap: 24,
          padding: 30,
        },
        wheelSensitivity: 0.25,
      });

      cy.on("tap", "node", (evt) => {
        const id = evt.target.id();
        const stat = payload.foundational.find((f) => f.key === id);
        if (stat) {
          setSelected(stat);
          return;
        }
        const data = evt.target.data() as Record<string, unknown>;
        setSelected({
          key: id,
          title: (data.label as string) ?? id,
          year: Number(data.year ?? 0),
          pagerank: Number(data.pagerank ?? 0),
          sustained: Number(data.sustained ?? 0),
          foundational: Number(data.foundational ?? 0),
          betweenness: Number(data.betweenness ?? 0),
          community: Number(data.community ?? -1),
          members: [id],
        });
      });

      cyRef.current = cy;
      } catch (e) {
        // 渲染失败必须显性报错，不能留一个空白画布让人以为"图是空的"
        setErr(`图谱渲染失败：${e instanceof Error ? e.message : String(e)}`);
      }
    })();

    return () => {
      disposed = true;
      const cy = cyRef.current as { destroy?: () => void } | null;
      cy?.destroy?.();
      cyRef.current = null;
    };
  }, [payload]);

  const loadReview = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/graph/review", { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      setReview((await res.json()) as ReviewPayload);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div className="shell" style={{ gridTemplateColumns: "300px minmax(0,1fr) 330px" }}>
      <Sidebar current="graph">
        {payload && (
          <>
            <div>
              <p className="section-title">图谱规模</p>
              <div className="pill mono">
                {payload.stats.nodes} 节点 · {payload.stats.edges} 边 · 密度 {payload.stats.density}
              </div>
              <div className="faint mono" style={{ fontSize: 11, marginTop: 6 }}>
                库内互引命中 {payload.stats.matched_refs}/{payload.stats.total_refs}
              </div>
            </div>

            <div>
              <p className="section-title">基石论文 Top 6</p>
              {payload.foundational.map((f, i) => (
                <button
                  key={f.key}
                  className="outline-item l1"
                  style={{ width: "100%" }}
                  onClick={() => setSelected(f)}
                >
                  <span className="num">{i + 1}</span>
                  <span className="txt">{f.title}</span>
                </button>
              ))}
            </div>

            <div>
              <p className="section-title">边缘衍生</p>
              {payload.derivative.slice(0, 3).map((f) => (
                <button
                  key={f.key}
                  className="outline-item l3"
                  style={{ width: "100%" }}
                  onClick={() => setSelected(f)}
                >
                  <span className="txt">{f.title}</span>
                </button>
              ))}
            </div>

            <button
              className="pill"
              style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
              onClick={() => void loadReview()}
              disabled={busy}
            >
              {busy ? "生成中…" : "生成综述 + Idea 考古"}
            </button>
          </>
        )}
      </Sidebar>

      <main className="reader-main" style={{ padding: "18px 20px 0" }}>
        <div className="reader-head">
          <h1>局域引用图谱</h1>
          {payload && (
            <span className="pill mono">
              {payload.communities.length} 个社区 · 滚轮缩放，点击节点看详情
            </span>
          )}
        </div>
        {err && <ErrorCard title="图谱渲染或加载失败" detail={err} />}
        <div
          ref={containerRef}
          style={{
            flex: 1,
            minHeight: 0,
            border: "1px solid var(--line)",
            borderRadius: 10,
            background: "var(--bg-raise)",
          }}
        />
      </main>

      <aside className="sidebar" style={{ borderLeft: "1px solid var(--line)", borderRight: "none" }}>
        {selected ? (
          <div>
            <p className="section-title">节点详情</p>
            <div style={{ fontSize: 13, lineHeight: 1.6 }}>{selected.title}</div>
            <div className="mono faint" style={{ fontSize: 11, margin: "6px 0 10px" }}>
              {selected.key} · {selected.year || "?"} · 社区 {selected.community}
            </div>
            <div className="keyvalue mono" style={{ fontSize: 11.5, lineHeight: 1.9 }}>
              <div>PageRank {selected.pagerank.toFixed(4)}</div>
              <div>跨代引用 {selected.sustained.toFixed(2)}</div>
              <div>基石分 {selected.foundational.toFixed(4)}</div>
              <div>桥接度 {selected.betweenness.toFixed(4)}</div>
            </div>
            {selected.members.length > 0 && (
              <Link
                className="pill"
                style={{ marginTop: 10, alignSelf: "flex-start" }}
                href={`/paper/${selected.members[0]}`}
              >
                打开阅读器 →
              </Link>
            )}
          </div>
        ) : (
          <div className="empty">点击左侧或图中节点查看指标</div>
        )}

        {review && (
          <div>
            <p className="section-title">自动综述</p>
            {review.reviews.map((r) => (
              <div key={r.community} className="card" style={{ marginBottom: 8 }}>
                <div className="mono faint" style={{ fontSize: 11 }}>
                  社区 {r.community} · {r.year_range} · {r.members.length} 篇 · {r.method}
                </div>
                <div style={{ fontSize: 12.5, marginTop: 4 }}>{r.theme}</div>
                <div className="dim" style={{ fontSize: 11.5, marginTop: 6, lineHeight: 1.6 }}>
                  {r.summary.slice(0, 220)}…
                </div>
              </div>
            ))}

            <p className="section-title">仍值得探索的 Idea（{review.total_ideas} 条中）</p>
            {review.open_ideas.length === 0 && <div className="empty">暂无</div>}
            {review.open_ideas.map((it) => (
              <div key={it.id} className="card" style={{ marginBottom: 8 }}>
                <div className="mono faint" style={{ fontSize: 10.5 }}>
                  {it.paper_id} p{it.page} · {it.year} · 同类 {it.mentions} 次
                </div>
                <div className="dim" style={{ fontSize: 11.5, marginTop: 4, lineHeight: 1.6 }}>
                  {it.text.slice(0, 150)}…
                </div>
                <div className="pill mono" style={{ marginTop: 6, fontSize: 10 }}>
                  {it.status}
                </div>
              </div>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}
