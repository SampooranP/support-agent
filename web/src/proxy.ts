import { NextResponse, type NextRequest } from "next/server";

import { DEMO_PASSWORD, SESSION_COOKIE, safeEqual, sessionToken } from "@/lib/demo-auth";

/** Every page and API route needs the demo session cookie, when a demo password is set. */
export async function proxy(request: NextRequest) {
  if (!DEMO_PASSWORD) return NextResponse.next();
  const cookie = request.cookies.get(SESSION_COOKIE)?.value ?? "";
  if (safeEqual(cookie, await sessionToken(DEMO_PASSWORD))) return NextResponse.next();

  if (request.nextUrl.pathname.startsWith("/api/")) {
    return Response.json({ detail: "Sign in to the demo first" }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  // Everything except the login page and its endpoint, Next.js assets and the favicon.
  matcher: ["/((?!login|api/login|_next/static|_next/image|favicon.ico).*)"],
};
