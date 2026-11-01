import type { Metadata } from "next";

import { Approvals } from "@/components/approvals";

export const metadata: Metadata = { title: "Approvals | Lumen & Pine Support" };

export default function ApprovalsPage() {
  return <Approvals />;
}
