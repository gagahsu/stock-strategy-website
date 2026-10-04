import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "選股研究室 · 台股策略",
  description: "日K診斷、選股掃描、策略回測與持股紀律",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
