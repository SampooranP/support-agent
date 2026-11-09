"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Chat" },
  { href: "/approvals", label: "Approvals" },
  { href: "/tickets", label: "Tickets" },
  { href: "/customers", label: "Customers" },
  { href: "/how-it-works", label: "How it works" },
];

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="-mx-1.5 flex overflow-x-auto md:ml-auto md:overflow-visible">
      {LINKS.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 shrink-0 items-center rounded-md px-1.5 text-sm transition-colors duration-150 md:min-h-9 md:px-2.5 ${
              active ? "font-medium text-foreground md:bg-surface-2" : "text-muted hover:text-foreground"
            }`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
