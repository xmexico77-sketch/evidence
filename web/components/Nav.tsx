"use client";

import Link from "next/link";
import type { ReactNode } from "react";

const LINKS = [
  { href: "/", label: "工作台", key: "home" },
  { href: "/discover", label: "论文发现", key: "discover" },
  { href: "/graph", label: "引用图谱", key: "graph" },
  { href: "/write", label: "论文框架", key: "write" },
];

export function Brand({ sub }: { sub?: string }) {
  return (
    <div className="brand">
      <strong>证源</strong>
      <span>{sub ?? "Evidence"}</span>
    </div>
  );
}

/** 全站统一导航。一处定义，避免每个页面各写一套。 */
export function Nav({ current }: { current: string }) {
  return (
    <nav className="nav">
      {LINKS.map((l) => (
        <Link
          key={l.key}
          href={l.href}
          className={`nav-item ${current === l.key ? "active" : ""}`}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

export function Sidebar({
  sub,
  current,
  children,
}: {
  sub?: string;
  current: string;
  children?: ReactNode;
}) {
  return (
    <aside className="sidebar">
      <Brand sub={sub} />
      <Nav current={current} />
      {children}
    </aside>
  );
}
