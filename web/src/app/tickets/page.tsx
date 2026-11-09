import type { Metadata } from "next";

import { Tickets } from "@/components/tickets";

export const metadata: Metadata = { title: "Tickets | Lumen & Pine Support" };

export default function TicketsPage() {
  return <Tickets />;
}
