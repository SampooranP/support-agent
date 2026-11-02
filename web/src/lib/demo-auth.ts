// Password gate for the public demo. With DEMO_PASSWORD unset (local development) there's no gate.
// Signing in sets a cookie holding an HMAC of a fixed label keyed by the password, so changing the
// password signs everyone out, and the cookie can't be forged without knowing it.

export const DEMO_PASSWORD = process.env.DEMO_PASSWORD ?? "";
export const SESSION_COOKIE = "demo_session";
export const SESSION_MAX_AGE_S = 7 * 24 * 3600;

export async function sessionToken(password: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
  ]);
  const mac = await crypto.subtle.sign("HMAC", key, encoder.encode("lumen-pine-demo-session"));
  return Array.from(new Uint8Array(mac), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Compare two strings in time that doesn't depend on where they first differ. */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
