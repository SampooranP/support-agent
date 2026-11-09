import { proxy } from "@/lib/agent-api";

export async function GET() {
  return proxy("/tickets");
}
