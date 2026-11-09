import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import { PineMark } from "@/components/icons";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Lumen & Pine Support",
  description: "AI customer-support agent with human approval for refunds and emails",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex h-full flex-col">
        <header className="shrink-0 border-b border-line bg-surface">
          <div className="flex flex-col px-4 md:h-14 md:flex-row md:items-center md:px-6">
            <Link href="/" className="flex h-12 items-center gap-2 self-start font-semibold tracking-tight md:h-auto md:self-center">
              <PineMark className="text-accent" />
              <span>
                Lumen &amp; Pine <span className="font-normal text-muted">Support</span>
              </span>
            </Link>
            <SiteNav />
          </div>
        </header>
        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
