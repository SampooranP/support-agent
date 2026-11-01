import { proxy } from "@/lib/agent-api";

export async function GET(req: Request) {
  // status=pending (default), a specific status, or empty for all.
  const status = new URL(req.url).searchParams.get("status") ?? "pending";
  return proxy(`/approvals?status=${encodeURIComponent(status)}`);
}
