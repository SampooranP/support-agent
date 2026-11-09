import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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
        <header className="border-b border-line bg-surface">
          <nav className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
            <Link href="/" className="font-semibold tracking-tight">
              Lumen &amp; Pine <span className="font-normal text-muted">Support</span>
            </Link>
            <div className="ml-auto flex gap-4 text-sm">
              <Link href="/" className="text-muted hover:text-foreground">
                Chat
              </Link>
              <Link href="/approvals" className="text-muted hover:text-foreground">
                Approvals
              </Link>
              <Link href="/tickets" className="text-muted hover:text-foreground">
                Tickets
              </Link>
            </div>
          </nav>
        </header>
        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
