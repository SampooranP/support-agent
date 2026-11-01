import { proxy } from "@/lib/agent-api";

export async function GET(req: Request) {
  // status: one or more comma-separated statuses (default "pending"), or empty for all. limit: max rows.
  const params = new URL(req.url).searchParams;
  const query = new URLSearchParams({ status: params.get("status") ?? "pending" });
  const limit = params.get("limit");
  if (limit) query.set("limit", limit);
  return proxy(`/approvals?${query}`);
}
