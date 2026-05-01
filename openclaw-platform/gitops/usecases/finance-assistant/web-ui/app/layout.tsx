import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "Finance Assistant — a thinking partner for money",
  description: "A hardware-isolated educational assistant that helps you reason clearly about budgeting, retirement, tax concepts, and home-buying tradeoffs. No account access. No specific picks. No guaranteed returns.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#020617",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
