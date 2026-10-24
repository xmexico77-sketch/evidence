"use client";

import type { ReactNode } from "react";

/** 统一的状态基元：空态、加载态、错误态、标签。
 *  这些在五个页面里原本各写各的，字号与配色都不一致。 */

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Loading({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="loading">
      <span className="dot" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorCard({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="card error-card">
      <strong>{title}</strong>
      {detail && <pre className="error-detail">{detail}</pre>}
    </div>
  );
}

export function Pill({
  tone = "default",
  mono = false,
  children,
  onClick,
  title,
}: {
  tone?: "default" | "ok" | "warn" | "bad";
  mono?: boolean;
  children: ReactNode;
  onClick?: () => void;
  title?: string;
}) {
  const cls = ["pill", tone !== "default" ? tone : "", mono ? "mono" : ""]
    .filter(Boolean)
    .join(" ");
  if (onClick) {
    return (
      <button className={cls} onClick={onClick} title={title}>
        {children}
      </button>
    );
  }
  return (
    <span className={cls} title={title}>
      {children}
    </span>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <p className="section-title">{children}</p>;
}
