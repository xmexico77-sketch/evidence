"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Sidebar } from "@/components/Nav";
import { api } from "@/lib/api";
import type { Anchor, AskResponse, Health, Paper } from "@/lib/types";

type CompareResult = {
  answer: string;
  grounded: boolean;
  citations: { marker: string; anchor: Anchor }[];
  invalid_markers: number[];
};

/** 把模型返回的 Markdown 表格渲染成真正的表格；非表格行按段落排出。 */
function AnswerBlocks({ text }: { text: string }) {
  const lines = text.split("\n").map((l) => l.trim());
  const out: React.ReactNode[] = [];
  let table: string[][] = [];

  const flushTable = () => {
    if (table.length === 0) return;
    const rows = table.filter((cells) => !cells.every((c) => /^:?-{2,}:?$/.test(c)));
    if (rows.length > 0) {
      const [head, ...body] = rows;
      out.push(
        <table className="md-table" key={`t${out.length}`}>
          <thead>
            <tr>
              {head.map((c, i) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
    }
    table = [];
  };

  for (const line of lines) {
    if (line.startsWith("|")) {
      const cells = line.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
      table.push(cells);
      continue;
    }
    flushTable();
    if (line) {
      out.push(
        <p key={`p${out.length}`} style={{ margin: "6px 0", fontSize: 13.5, lineHeight: 1.75 }}>
          {line}
        </p>,
      );
    }
  }
  flushTable();
  return <>{out}</>;
}

const DIMENSIONS = [
  "自注意力机制与预训练目标的关系",
  "模型规模的演化与计算成本",
  "训练数据与归纳偏置的差异",
];

const SAMPLES = [
  "训练用了多少块 GPU，什么型号？",
  "标签平滑的取值是多少？",
  "Transformer 的多头注意力有几个头？",
];

/** 首页空态的入口卡片：让第一次打开的人知道这套系统能做什么。 */
const CAPABILITIES = [
  { tag: "模块一", title: "版式保真阅读", desc: "双栏重建、标题树、图表定位，段落级坐标", href: "/paper/1706.03762v1" },
  { tag: "模块二", title: "抗幻觉问答", desc: "三道闸门，答不出就拒答，不编造", href: "/" },
  { tag: "模块五", title: "引用图谱", desc: "基石论文识别、社区划分、自动综述", href: "/graph" },
  { tag: "模块四", title: "论文发现", desc: "arXiv 检索与追踪，可复现性加权推荐", href: "/discover" },
  { tag: "模块六", title: "写作与图表", desc: "CSV 出学术图表，提纲与草稿带引用核验", href: "/write" },
  { tag: "模块三", title: "双语联动", desc: "原文与译文共享段落锚点，滚动对齐", href: "/paper/1706.03762v1" },
];

export default function Workbench() {
  const [health, setHealth] = useState<Health | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [offline, setOffline] = useState<string | null>(null);
  const [question, setQuestion] = useState(SAMPLES[0]);
  const [result, setResult] = useState<AskResponse | null>(null);
  // 限定论文：库里多篇论文都会谈"GPU 型号"这类事实，不限定就答成别篇
  const [scope, setScope] = useState("");
  // 跨篇对比（模块二"多篇论文跨文献对比"）
  const [mode, setMode] = useState<"ask" | "compare">("ask");
  const [pairA, setPairA] = useState("");
  const [pairB, setPairB] = useState("");
  const [compBusy, setCompBusy] = useState(false);
  const [comp, setComp] = useState<CompareResult | null>(null);
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
      setResult(await api.ask(q, 5, scope || undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [question, busy, scope]);

  const compare = useCallback(async () => {
    if (!pairA || !pairB || pairA === pairB) return;
    const dimension = question.trim();
    if (!dimension) return;
    setCompBusy(true);
    setError(null);
    try {
      setComp(await api.compare(dimension, [pairA, pairB]));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCompBusy(false);
    }
  }, [pairA, pairB, question]);

  return (
    <div className="shell">
      <Sidebar current="home">
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
      </Sidebar>

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

        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          {(
            [
              ["ask", "文献问答"],
              ["compare", "跨篇对比"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              className={`pill ${mode === key ? "ok" : ""}`}
              onClick={() => setMode(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="ask-box">
          {mode === "ask" ? (
            <select
              className="scope-select"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              title="限定在某篇论文内提问；不限定则跨全库检索"
            >
              <option value="">全部文献</option>
              {papers.map((p) => (
                <option key={p.id} value={p.id}>
                  {(p.title || p.id).slice(0, 42)}
                </option>
              ))}
            </select>
          ) : (
            <>
              <select
                className="scope-select"
                value={pairA}
                onChange={(e) => setPairA(e.target.value)}
                title="对比对象 A"
              >
                <option value="">选论文 A</option>
                {papers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {(p.title || p.id).slice(0, 36)}
                  </option>
                ))}
              </select>
              <select
                className="scope-select"
                value={pairB}
                onChange={(e) => setPairB(e.target.value)}
                title="对比对象 B"
              >
                <option value="">选论文 B</option>
                {papers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {(p.title || p.id).slice(0, 36)}
                  </option>
                ))}
              </select>
            </>
          )}
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                if (mode === "ask") void ask();
                else void compare();
              }
            }}
            placeholder={
              mode === "ask"
                ? "用中文提问，检索英文论文…"
                : "输入比较维度，例如：自注意力机制与预训练目标的关系"
            }
          />
          <button
            onClick={() => (mode === "ask" ? void ask() : void compare())}
            disabled={
              mode === "ask"
                ? busy || !question.trim()
                : compBusy || !question.trim() || !pairA || !pairB || pairA === pairB
            }
          >
            {mode === "ask" ? (busy ? "检索中…" : "提问") : compBusy ? "对比中…" : "对比"}
          </button>
        </div>

        {mode === "ask" && (
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
        )}

        {mode === "compare" && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>
            {DIMENSIONS.map((d) => (
              <button
                key={d}
                className="pill"
                style={{ background: "transparent" }}
                onClick={() => setQuestion(d)}
              >
                {d}
              </button>
            ))}
            {pairA && pairB && pairA === pairB && (
              <span className="pill warn">两篇不能相同</span>
            )}
          </div>
        )}

        {error && (
          <div className="card" style={{ borderColor: "#4d2424", color: "var(--bad)" }}>
            {error}
          </div>
        )}

        {mode === "compare" && comp && (
          <div className="card" style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
              <span className={`pill ${comp.grounded ? "ok" : "warn"}`}>
                {comp.grounded ? "有据" : comp.invalid_markers.length ? "标记非法" : "未通过校验"}
              </span>
              <span className="pill mono">引用 {comp.citations.length}</span>
              {comp.invalid_markers.length > 0 && (
                <span className="pill bad">非法标记 {comp.invalid_markers.join(",")}</span>
              )}
            </div>
            <AnswerBlocks text={comp.answer} />
            {comp.citations.length > 0 && (
              <div className="cite-list">
                {comp.citations.map((c) => (
                  <div className="cite" key={c.marker}>
                    <div className="top">
                      <strong style={{ color: "var(--accent)" }}>{c.marker}</strong>
                      <span>{c.anchor.label}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!result && !comp && !busy && !compBusy && (
          <>
            <p className="section-title" style={{ marginTop: 6 }}>
              六大模块 · 点进任一入口
            </p>
            <div className="cap-grid">
              {CAPABILITIES.map((c) => (
                <Link key={c.href} href={c.href} className="cap-card">
                  <span className="cap-tag mono">{c.tag}</span>
                  <strong>{c.title}</strong>
                  <span className="dim" style={{ fontSize: 12, lineHeight: 1.6 }}>
                    {c.desc}
                  </span>
                </Link>
              ))}
            </div>
            <p className="faint" style={{ fontSize: 11.5, marginTop: 14 }}>
              每个结论都带页级锚点：答案里的 [E1] 可点回原文具体段落，
              标记校验不通过的内容不会输出。
            </p>
          </>
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
