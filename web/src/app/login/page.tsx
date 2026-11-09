import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = { title: "Sign in | Lumen & Pine Support" };

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <div className="mx-auto mt-16 w-full max-w-sm px-4 md:mt-24">
      <div className="rounded-xl border border-line bg-surface p-6 shadow-card">
        <h1 className="text-xl font-semibold tracking-tight">Demo access</h1>
        <p className="mt-1 text-sm text-muted">This demo makes real AI calls, so it&apos;s behind a password.</p>
        <form action="/api/login" method="post" className="mt-5 flex flex-col gap-3">
          <input type="password" name="password" required autoFocus placeholder="Password" aria-label="Password" className="field" />
          {/* The page itself is static; only this note depends on the URL. */}
          <Suspense fallback={null}>
            <WrongPassword searchParams={searchParams} />
          </Suspense>
          <button type="submit" className="btn btn-primary">
            Sign in
          </button>
        </form>
      </div>
    </div>
  );
}

async function WrongPassword({ searchParams }: Pick<PageProps<"/login">, "searchParams">) {
  const { error } = await searchParams;
  return error ? <p className="text-sm text-danger">That password isn&apos;t right.</p> : null;
}
