"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import PdfViewer from "@/components/PdfViewer";
import type { OutlineItem } from "@/lib/types";

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
  const [focusPage, setFocusPage] = useState<number | null>(initialPage ?? null);
  const [current, setCurrent] = useState(initialPage ?? 1);
  const [err, setErr] = useState<string | null>(null);

  const highlights =
    initialPage && initialBox ? [{ page: initialPage, bbox: initialBox }] : [];

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`/api/papers/${paperId}/outline`, { cache: "no-store" });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data = (await res.json()) as { outline: OutlineItem[] };
        setOutline(data.outline);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [paperId]);

  return (
    <div className="shell reader-shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>证源</strong>
          <span>Reader</span>
        </div>
        <Link href="/" className="pill" style={{ alignSelf: "flex-start" }}>
          ← 返回工作台
        </Link>
        <div>
          <p className="section-title">
            标题树 {current > 0 && <span className="faint">· 当前 p{current}</span>}
          </p>
          {err && <div className="empty">大纲加载失败：{err}</div>}
          {outline.length === 0 && !err && <div className="empty">暂无大纲</div>}
          <div className="outline">
            {outline.map((h, i) => (
              <button
                key={`${h.block_id}-${i}`}
                className={`outline-item l${h.level}`}
                onClick={() => setFocusPage(h.page)}
                title={`p${h.page}`}
              >
                {h.number ? <span className="num">{h.number}</span> : null}
                <span className="txt">{h.text}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="reader-main">
        <div className="reader-head">
          <h1>{paperId}</h1>
          <span className="pill mono">
            {outline.length} 个标题 · 当前 p{current}
          </span>
        </div>
        <PdfViewer
          paperId={paperId}
          focusPage={focusPage}
          highlights={highlights}
          onPageChange={setCurrent}
        />
      </main>
    </div>
  );
}
