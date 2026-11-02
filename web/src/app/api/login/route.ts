import { NextResponse } from "next/server";

import { DEMO_PASSWORD, SESSION_COOKIE, SESSION_MAX_AGE_S, safeEqual, sessionToken } from "@/lib/demo-auth";

/** The login form posts here. A right password sets the session cookie; a wrong one goes back to the form. */
export async function POST(req: Request) {
  const form = await req.formData();
  const password = String(form.get("password") ?? "");
  if (!DEMO_PASSWORD || !safeEqual(password, DEMO_PASSWORD)) {
    return NextResponse.redirect(new URL("/login?error=1", req.url), 303);
  }
  const res = NextResponse.redirect(new URL("/", req.url), 303);
  res.cookies.set(SESSION_COOKIE, await sessionToken(DEMO_PASSWORD), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_S,
  });
  return res;
}
