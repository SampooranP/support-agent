/** A readable message from an API error body (FastAPI sends a string, or a list for validation errors). */
export function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((d) => (d as { msg?: string })?.msg).filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}
