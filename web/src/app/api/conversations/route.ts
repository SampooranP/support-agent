import { jsonInit, proxy } from "@/lib/agent-api";

export async function POST(req: Request) {
  const { customer_email } = (await req.json()) as { customer_email?: string };
  return proxy("/conversations", jsonInit("POST", { customer_email }));
}
