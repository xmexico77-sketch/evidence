"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

type Section = {
  heading: string;
  purpose: string;
  draft: string;
  grounded: boolean;
  evidence: { marker: string; paper_id: string; page: number; section: string }[];
};

type Reference = {
  key: string;
  title: string;
  paper_id: string;
  year: number;
  arxiv_id: string;
  evidence_page: number;
  line: string;
};

type Framework = {
  idea: string;
  title: string;
  mode: string;
  sections: Section[];
  references: Reference[];
  warnings: string[];
  mermaid: string;
  markdown: string;
};

const SAMPLES = [
  "用稀疏注意力降低长文本推理的显存开销",
  "把位置编码从绝对改为相对以提升长度外推",
  "用低秩适配替代全参数微调以降低训练成本",
];

export default function WritePage() {
  const [idea, setIdea] = useState(SAMPLES[0]);
  const [fw, setFw] = useState<Framework | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = useCallback(async () => {
    if (!idea.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea: idea.trim(), use_llm: true }),
      });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      setFw((await res.json()) as Framework);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [idea, busy]);

  const copyMd = useCallback(async () => {
    if (!fw) return;
    try {
      await navigator.clipboard.writeText(fw.markdown);
    } catch {
      /* 剪贴板不可用时不打扰用户 */
    }
  }, [fw]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>证源</strong>
          <span>Write</span>
        </div>
        <Link href="/" className="pill" style={{ alignSelf: "flex-start" }}>
          ← 返回工作台
        </Link>
        <div>
          <p className="section-title">生成规则</p>
          <div className="dim" style={{ fontSize: 12, lineHeight: 1.8 }}>
            参考文献只取自库内已解析文献
            <br />
            生成后逐条核验，核验不通过即剔除
            <br />
            章节草稿引用非法标记时降级为要点式
          </div>
        </div>
        {fw && (
          <button className="pill" onClick={() => void copyMd()}>
            复制 Markdown
          </button>
        )}
      </aside>

      <main className="main">
        <h1 style={{ fontSize: 20, margin: "0 0 4px" }}>论文框架生成</h1>
        <p className="dim" style={{ margin: "0 0 18px", fontSize: 13 }}>
          给一个研究设想，得到提纲、章节草稿与<strong>可在库内核实的</strong>参考文献。
        </p>

        <div className="ask-box">
          <input
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void run();
            }}
            placeholder="一句话描述你的研究设想"
          />
          <button onClick={() => void run()} disabled={busy || !idea.trim()}>
            {busy ? "生成中…" : "生成框架"}
          </button>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>
          {SAMPLES.map((s) => (
            <button
              key={s}
              className="pill"
              style={{ background: "transparent" }}
              onClick={() => setIdea(s)}
            >
              {s}
            </button>
          ))}
        </div>

        {err && (
          <div className="card" style={{ borderColor: "#4d2424", color: "var(--bad)" }}>
            {err}
          </div>
        )}

        {fw && (
          <>
            <div className="card" style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                <span className={`pill ${fw.mode === "llm" ? "ok" : "warn"}`}>
                  {fw.mode === "llm" ? "模型生成" : "抽取式"}
                </span>
                <span className="pill mono">{fw.sections.length} 章节</span>
                <span className="pill mono">{fw.references.length} 条引用</span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{fw.title}</div>
              {fw.warnings.length > 0 && (
                <ul className="dim" style={{ fontSize: 12, margin: "8px 0 0", paddingLeft: 18 }}>
                  {fw.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </div>

            {fw.sections.map((s) => (
              <div className="card" key={s.heading} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <strong style={{ fontSize: 13.5 }}>{s.heading}</strong>
                  <span className={`pill mono ${s.grounded ? "ok" : ""}`}>
                    {s.grounded ? "有据" : "缺证据"}
                  </span>
                </div>
                <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>
                  {s.purpose}
                </div>
                <div className="answer" style={{ fontSize: 12.5, marginTop: 8, whiteSpace: "pre-wrap" }}>
                  {s.draft}
                </div>
              </div>
            ))}

            <div className="card" style={{ marginBottom: 10 }}>
              <p className="section-title" style={{ marginBottom: 8 }}>
                References（库内可核实）
              </p>
              {fw.references.map((r) => (
                <div key={r.key} className="mono" style={{ fontSize: 11.5, marginBottom: 4 }}>
                  {r.line}
                  <span className="faint"> · 证据 p{r.evidence_page}</span>
                </div>
              ))}
            </div>

            <div className="card">
              <p className="section-title" style={{ marginBottom: 8 }}>
                拓扑图源码（Mermaid）
              </p>
              <pre
                className="mono"
                style={{ fontSize: 11.5, margin: 0, whiteSpace: "pre-wrap", color: "var(--fg-dim)" }}
              >
                {fw.mermaid}
              </pre>
            </div>
          </>
        )}

        {!fw && !busy && !err && <div className="empty">输入设想或选一个示例</div>}
      </main>
    </div>
  );
}
