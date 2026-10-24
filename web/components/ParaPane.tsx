"use client";

import { useCallback, useEffect, useRef } from "react";
import type { Paragraph } from "@/lib/types";

type Props = {
  paragraphs: Paragraph[];
  translations: Record<string, string>;
  translateEnabled: boolean;
  translatePending: number;
  /** 外部驱动的锚点滚动目标 */
  targetId?: string | null;
  /** 用户滚动时回报顶部段落 */
  onProgress?: (id: string) => void;
  onRequestTranslate?: () => void;
  highlightIds?: string[];
};

export default function ParaPane({
  paragraphs,
  translations,
  translateEnabled,
  translatePending,
  targetId = null,
  onProgress,
  onRequestTranslate,
  highlightIds = [],
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const itemEls = useRef<Map<string, HTMLDivElement>>(new Map());
  const rafRef = useRef<number | null>(null);

  const report = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = null;
      const c = scrollRef.current;
      if (!c || !onProgress) return;
      const top = c.getBoundingClientRect().top + 8;
      for (const p of paragraphs) {
        const el = itemEls.current.get(p.id);
        if (!el) continue;
        if (el.getBoundingClientRect().bottom > top) {
          onProgress(p.id);
          return;
        }
      }
    });
  }, [paragraphs, onProgress]);

  useEffect(() => {
    const c = scrollRef.current;
    if (!c) return;
    c.addEventListener("scroll", report, { passive: true });
    return () => c.removeEventListener("scroll", report);
  }, [report]);

  useEffect(() => {
    if (!targetId) return;
    const el = itemEls.current.get(targetId);
    const c = scrollRef.current;
    if (!el || !c) return;
    const delta =
      el.getBoundingClientRect().top - c.getBoundingClientRect().top - 12;
    c.scrollBy({ top: delta });
    el.classList.add("active");
    const t = window.setTimeout(() => el.classList.remove("active"), 1400);
    return () => window.clearTimeout(t);
  }, [targetId]);

  return (
    <div className="para-pane">
      <div className="para-head">
        <span>双语对照</span>
        {translateEnabled ? (
          <button className="pill" onClick={onRequestTranslate}>
            翻译本页{translateHint(translatePending)}
          </button>
        ) : (
          <span className="pill warn">未配置模型 · 仅显示原文</span>
        )}
      </div>

      <div className="para-scroll" ref={scrollRef}>
        {paragraphs.length === 0 && <div className="empty">暂无段落</div>}
        {paragraphs.map((p) => {
          const zh = translations[p.id];
          const isHit = highlightIds.includes(p.id);
          return (
            <div
              key={p.id}
              className={`para ${isHit ? "hit" : ""}`}
              ref={(el) => {
                if (el) itemEls.current.set(p.id, el);
                else itemEls.current.delete(p.id);
              }}
            >
              <div className="para-meta mono">
                p{p.page}
                {p.section ? ` · ${p.section.split(" > ").pop()}` : ""}
              </div>
              <div className="para-src">{p.text}</div>
              {zh ? (
                <div className="para-zh">{zh}</div>
              ) : translateEnabled ? (
                <div className="para-zh faint">（待翻译）</div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function translateHint(pending: number): string {
  return pending > 0 ? `（剩 ${pending}）` : "";
}
