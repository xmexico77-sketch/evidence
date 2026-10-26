"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import { ensureModernJsPolyfills } from "@/lib/polyfill";

export type HighlightBox = { page: number; bbox: number[] };
export type ScrollProgress = { page: number; ratio: number };

type Props = {
  paperId: string;
  highlights?: HighlightBox[];
  focusPage?: number | null;
  /** 由外部（双语侧栏）驱动的滚动目标 */
  scrollTarget?: ScrollProgress | null;
  /** 用户滚动 PDF 时回报阅读位置 */
  onProgress?: (p: ScrollProgress) => void;
  onPageChange?: (page: number) => void;
};

/** PDF 点坐标（PyMuPDF 左上原点、y 向下）→ PDF 用户空间（左下原点、y 向上）。 */
function toPdfSpace(bbox: number[], pageHeight: number): number[] {
  const [x0, y0, x1, y1] = bbox;
  return [x0, pageHeight - y1, x1, pageHeight - y0];
}

export default function PdfViewer({
  paperId,
  highlights = [],
  focusPage = null,
  scrollTarget = null,
  onProgress,
  onPageChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const pageEls = useRef<Map<number, HTMLDivElement>>(new Map());
  const rendered = useRef<Set<number>>(new Set());
  const rafRef = useRef<number | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  // ---------- 渲染单页 ----------
  const renderPage = useCallback(
    async (pdf: PDFDocumentProxy, pageNo: number, host: HTMLDivElement) => {
      if (rendered.current.has(pageNo)) return;
      rendered.current.add(pageNo);
      const page: PDFPageProxy = await pdf.getPage(pageNo);
      const unscaled = page.getViewport({ scale: 1 });
      const width = host.clientWidth || 720;
      const scale = width / unscaled.width;
      const viewport = page.getViewport({ scale });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);

      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      canvas.style.display = "block";
      host.style.height = `${viewport.height}px`;
      host.prepend(canvas);

      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("无法获取 canvas 上下文");
      await page.render({
        canvasContext: ctx,
        viewport,
        transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
      }).promise;

      for (const box of highlights.filter((h) => h.page === pageNo)) {
        const rect = viewport.convertToViewportRectangle(
          toPdfSpace(box.bbox, unscaled.height) as [number, number, number, number],
        );
        const el = document.createElement("div");
        el.className = "hl";
        el.style.left = `${Math.min(rect[0], rect[2])}px`;
        el.style.top = `${Math.min(rect[1], rect[3])}px`;
        el.style.width = `${Math.abs(rect[2] - rect[0])}px`;
        el.style.height = `${Math.abs(rect[3] - rect[1])}px`;
        host.appendChild(el);
      }
    },
    [highlights],
  );

  // ---------- 加载文档 ----------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setStatus("loading");
      try {
        // 必须在加载 pdfjs 之前补原语：pdfjs-dist 4.x 用了
        // Promise.withResolvers（Edge/Chrome 119+），旧浏览器会直接报错、画布空白
        ensureModernJsPolyfills();
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        const pdf = await pdfjs.getDocument(`/api/papers/${paperId}/file`).promise;
        if (cancelled) return;
        docRef.current = pdf;
        setTotal(pdf.numPages);
        setStatus("ready");
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [paperId]);

  // ---------- 首次渲染 ----------
  useEffect(() => {
    if (status !== "ready" || !docRef.current) return;
    const pdf = docRef.current;
    (async () => {
      for (let p = 1; p <= pdf.numPages; p += 1) {
        const host = pageEls.current.get(p);
        if (host) await renderPage(pdf, p, host);
      }
    })();
  }, [status, renderPage]);

  // ---------- 滚动回报 ----------
  useEffect(() => {
    const c = containerRef.current;
    if (!c || !onProgress) return;
    const handler = () => {
      if (rafRef.current !== null) return;
      rafRef.current = window.requestAnimationFrame(() => {
        rafRef.current = null;
        const cRect = c.getBoundingClientRect();
        let best: ScrollProgress | null = null;
        for (const [p, el] of [...pageEls.current.entries()].sort((a, b) => a[0] - b[0])) {
          const r = el.getBoundingClientRect();
          if (r.height === 0) continue;
          if (r.bottom > cRect.top + 40) {
            const ratio = Math.min(Math.max((cRect.top - r.top) / r.height, 0), 1);
            best = { page: p, ratio };
            break;
          }
        }
        if (best) onProgress(best);
      });
    };
    c.addEventListener("scroll", handler, { passive: true });
    return () => c.removeEventListener("scroll", handler);
  }, [onProgress, status]);

  // ---------- 外部驱动的滚动 ----------
  useEffect(() => {
    const c = containerRef.current;
    if (!c || !scrollTarget) return;
    const el = pageEls.current.get(scrollTarget.page);
    if (!el) return;
    const delta =
      el.getBoundingClientRect().top -
      c.getBoundingClientRect().top -
      scrollTarget.ratio * el.clientHeight;
    c.scrollBy({ top: delta });
    onPageChange?.(scrollTarget.page);
  }, [scrollTarget, onPageChange]);

  // ---------- 跳转高亮 ----------
  useEffect(() => {
    if (!focusPage) return;
    const el = pageEls.current.get(focusPage);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.add("flash");
    const timer = window.setTimeout(() => el.classList.remove("flash"), 1200);
    onPageChange?.(focusPage);
    return () => window.clearTimeout(timer);
  }, [focusPage, onPageChange]);

  if (status === "error") {
    return (
      <div className="card" style={{ borderColor: "#4d2424", color: "var(--bad)" }}>
        PDF 渲染失败：{error}
      </div>
    );
  }

  return (
    <div className="pdf-scroll" ref={containerRef}>
      {status === "loading" && <div className="empty">正在加载 PDF…</div>}
      {Array.from({ length: total }, (_, i) => i + 1).map((p) => (
        <div
          key={p}
          className="pdf-page"
          ref={(el) => {
            if (el) pageEls.current.set(p, el);
            else pageEls.current.delete(p);
          }}
        >
          <span className="pdf-page-no">{p}</span>
        </div>
      ))}
    </div>
  );
}
