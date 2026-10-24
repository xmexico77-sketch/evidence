import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "证源 Evidence · 科研助手 Agent",
  description:
    "带段落级锚点溯源的科研助手：每个结论都能点回原文的页与坐标。",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
