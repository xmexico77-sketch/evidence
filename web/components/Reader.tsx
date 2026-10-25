"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ParaPane from "@/components/ParaPane";
import PdfViewer, { type ScrollProgress } from "@/components/PdfViewer";
import { Sidebar } from "@/components/Nav";
import { Empty, ErrorCard } from "@/components/ui";
import type { AnswerResult, OutlineItem, Paragraph } from "@/lib/types";

const SYNC_LOCK_MS = 700;

export default function Reader({
  paperId,
  initialPage,
  initialBox,
}: {
  paperId: string;
  initialPage?: number;
  initialBox?: number[];
}) {
  const [outline, setOutline] = useState<OutlineItem[]>([]);
  const [paragraphs, setParagraphs] = useState<Paragraph[]>([]);
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const [translateEnabled, setTranslateEnabled] = useState(false);
  const [pending, setPending] = useState(0);

  const [focusPage, setFocusPage] = useState<number | null>(initialPage ?? null);
  const [current, setCurrent] = useState(initialPage ?? 1);
  // 就本篇提问：API 已支持 paper_id 限定，这里把它接上界面。
  // 库里 22 篇时，"用了多少 GPU"有多个合理答案，限定范围才是用户真正想要的。
  const [askQ, setAskQ] = useState("");
  const [askBusy, setAskBusy] = useState(false);
  const [askResult, setAskResult] = useState<AnswerResult | null>(null);
  const [pdfTarget, setPdfTarget] = useState<ScrollProgress | null>(null);
  const [paraTarget, setParaTarget] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // 双向联动锁：避免 A 驱动 B、B 又回报 A 的死循环
  const lock = useRef<{ dir: "pdf" | "para"; until: number }>({ dir: "para", until: 0 });

  const byPage = useMemo(() => {
    const m = new Map<number, Paragraph[]>();
    for (const p of paragraphs) {
      const list = m.get(p.page) ?? [];
      list.push(p);
      m.set(p.page, list);
    }
    return m;
  }, [paragraphs]);

  const paraById = useMemo(
    () => new Map(paragraphs.map((p) => [p.id, p])),
    [paragraphs],
  );

  useEffect(() => {
    (async () => {
      try {
        const [o, p] = await Promise.all([
          fetch(`/api/papers/${paperId}/outline`, { cache: "no-store" }),
          fetch(`/api/papers/${paperId}/paragraphs`, { cache: "no-store" }),
        ]);
        if (!o.ok) throw new Error(`outline ${o.status}`);
        if (!p.ok) throw new Error(`paragraphs ${p.status}`);
        setOutline(((await o.json()) as { outline: OutlineItem[] }).outline);
        setParagraphs(((await p.json()) as { paragraphs: Paragraph[] }).paragraphs);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [paperId]);

  // PDF 滚动 → 驱动段落栏
  const onPdfProgress = useCallback(
    ({ page, ratio }: ScrollProgress) => {
      const now = Date.now();
      if (lock.current.dir === "para" && now < lock.current.until) return;
      const list = byPage.get(page);
      setCurrent(page);
      if (!list || list.length === 0) return;
      const idx = Math.min(list.length - 1, Math.max(0, Math.floor(ratio * list.length)));
      lock.current = { dir: "pdf", until: now + SYNC_LOCK_MS };
      setParaTarget(list[idx].id);
    },
    [byPage],
  );

  // 段落栏滚动 → 驱动 PDF
  const onParaProgress = useCallback(
    (id: string) => {
      const now = Date.now();
      if (lock.current.dir === "pdf" && now < lock.current.until) return;
      const para = paraById.get(id);
      if (!para) return;
      const list = byPage.get(para.page) ?? [];
      const idx = Math.max(0, list.findIndex((x) => x.id === id));
      const ratio = list.length ? idx / list.length : 0;
      lock.current = { dir: "para", until: now + SYNC_LOCK_MS };
      setPdfTarget({ page: para.page, ratio });
      setCurrent(para.page);
    },
    [byPage, paraById],
  );

  const translateVisible = useCallback(async () => {
    const list = byPage.get(current) ?? [];
    if (list.length === 0) return;
    try {
      const res = await fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paper_id: paperId,
          lang: "zh",
          block_ids: list.map((p) => p.id),
        }),
      });
      const data = (await res.json()) as {
        enabled: boolean;
        translations: Record<string, string>;
        pending?: number;
      };
      setTranslateEnabled(data.enabled);
      if (data.enabled) {
        setTranslations((prev) => ({ ...prev, ...data.translations }));
        setPending(data.pending ?? 0);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [byPage, current, paperId]);

  const askThisPaper = useCallback(async () => {
    const q = askQ.trim();
    if (!q || askBusy) return;
    setAskBusy(true);
    setAskResult(null);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, top_k: 5, paper_id: paperId }),
      });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      setAskResult((await res.json()) as AnswerResult);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAskBusy(false);
    }
  }, [askQ, askBusy, paperId]);

  const highlights =
    initialPage && initialBox ? [{ page: initialPage, bbox: initialBox }] : [];

  return (
    <div className="shell reader-shell">
      <Sidebar current="reader">
        <div>
          <p className="section-title">
            标题树 <span className="faint">· 当前 p{current}</span>
          </p>
          {err && <ErrorCard title="大纲加载失败" detail={err} />}
          {outline.length === 0 && !err && <Empty>暂无大纲</Empty>}
          <div className="outline">
            {outline.map((h, i) => (
              <button
                key={`${h.block_id}-${i}`}
                className={`outline-item l${h.level}`}
                onClick={() => {
                  setFocusPage(h.page);
                  setParaTarget(null);
                  setPdfTarget({ page: h.page, ratio: 0 });
                }}
                title={`p${h.page}`}
              >
                {h.number ? <span className="num">{h.number}</span> : null}
                <span className="txt">{h.text}</span>
              </button>
            ))}
          </div>
        </div>
      </Sidebar>

      <main className="reader-main">
        <div className="reader-head">
          <h1>{paperId}</h1>
          <span className="pill mono">{outline.length} 个标题 · 当前 p{current}</span>
          <span className="pill mono">{paragraphs.length} 段</span>
        </div>

        <div className="ask-box" style={{ marginBottom: 10 }}>
          <input
            value={askQ}
            onChange={(e) => setAskQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void askThisPaper();
            }}
            placeholder="就本篇提问，例如：训练用了多少块 GPU？"
          />
          <button onClick={() => void askThisPaper()} disabled={askBusy || !askQ.trim()}>
            {askBusy ? "检索中…" : "提问"}
          </button>
          {askResult && (
            <button
              onClick={() => setAskResult(null)}
              style={{ background: "transparent", color: "var(--fg-dim)", borderColor: "var(--line)" }}
            >
              收起
            </button>
          )}
        </div>

        {askResult && (
          <div className="card" style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
              <span className={`pill ${askResult.grounded ? "ok" : "warn"}`}>
                {askResult.grounded ? "有据" : askResult.insufficient ? "拒答" : "未通过校验"}
              </span>
              <span className="pill mono">置信度 {askResult.confidence.toFixed(2)}</span>
              <span className="pill mono">仅限本篇</span>
            </div>
            <div className="answer" style={{ fontSize: 13.5 }}>
              {askResult.answer}
            </div>
            {askResult.citations.length > 0 && (
              <div className="cite-list">
                {askResult.citations.map((c) => (
                  <div className="cite" key={c.marker}>
                    <div className="top">
                      <strong style={{ color: "var(--accent)" }}>{c.marker}</strong>
                      <span>{c.anchor.label}</span>
                      <button
                        className="pill"
                        style={{ marginLeft: "auto", background: "transparent" }}
                        onClick={() => {
                          setFocusPage(c.anchor.page);
                          setPdfTarget({ page: c.anchor.page, ratio: 0 });
                        }}
                      >
                        定位 →
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="reader-split">
          <PdfViewer
            paperId={paperId}
            focusPage={focusPage}
            highlights={highlights}
            scrollTarget={pdfTarget}
            onProgress={onPdfProgress}
            onPageChange={setCurrent}
          />
          <ParaPane
            paragraphs={paragraphs}
            translations={translations}
            translateEnabled={translateEnabled}
            translatePending={pending}
            targetId={paraTarget}
            onProgress={onParaProgress}
            onRequestTranslate={() => void translateVisible()}
          />
        </div>
      </main>
    </div>
  );
}
