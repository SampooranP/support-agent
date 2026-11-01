import { jsonInit, proxy } from "@/lib/agent-api";

export async function POST(req: Request, ctx: RouteContext<"/api/approvals/[id]/decision">) {
  const { id } = await ctx.params;
  const { approved, reviewer, note } = (await req.json()) as { approved: boolean; reviewer: string; note?: string };
  return proxy(`/approvals/${encodeURIComponent(id)}/decision`, jsonInit("POST", { approved, reviewer, note: note || null }));
}
