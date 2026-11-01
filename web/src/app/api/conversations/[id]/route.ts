import { proxy } from "@/lib/agent-api";

export async function GET(_req: Request, ctx: RouteContext<"/api/conversations/[id]">) {
  const { id } = await ctx.params;
  return proxy(`/conversations/${encodeURIComponent(id)}`);
}
