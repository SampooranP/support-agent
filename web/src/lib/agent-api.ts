import "server-only";

// The Python agent API. Only the Next.js server talks to it; the browser calls /api/* here.
const AGENT_API_URL = process.env.AGENT_API_URL ?? "http://localhost:8000";

export async function agentFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${AGENT_API_URL}${path}`, { ...init, cache: "no-store" });
  } catch {
    return Response.json(
      { detail: `Can't reach the agent API at ${AGENT_API_URL}. Is it running? (uvicorn agent.api:app --port 8000)` },
      { status: 502 },
    );
  }
}

/** Forward a request to the agent API and return its response unchanged. */
export async function proxy(path: string, init?: RequestInit): Promise<Response> {
  const res = await agentFetch(path, init);
  return new Response(res.body, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}

export function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

/** Parse a server-sent-events body into its JSON `data:` payloads. */
export async function* readEvents<T>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = raw
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (data) yield JSON.parse(data) as T;
    }
  }
}
