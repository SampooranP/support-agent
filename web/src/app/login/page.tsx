import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = { title: "Sign in | Lumen & Pine Support" };

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <div className="mx-auto mt-24 w-full max-w-sm px-4">
      <h1 className="text-lg font-semibold tracking-tight">Demo access</h1>
      <p className="mt-1 text-sm text-muted">This demo makes real AI calls, so it&apos;s behind a password.</p>
      <form action="/api/login" method="post" className="mt-6 flex flex-col gap-3">
        <input
          type="password"
          name="password"
          required
          autoFocus
          placeholder="Password"
          aria-label="Password"
          className="rounded-lg border border-line bg-surface px-3 py-2 outline-none focus:border-accent"
        />
        {/* The page itself is static; only this note depends on the URL. */}
        <Suspense fallback={null}>
          <WrongPassword searchParams={searchParams} />
        </Suspense>
        <button type="submit" className="rounded-lg bg-accent px-4 py-2 text-white hover:opacity-90">
          Sign in
        </button>
      </form>
    </div>
  );
}

async function WrongPassword({ searchParams }: Pick<PageProps<"/login">, "searchParams">) {
  const { error } = await searchParams;
  return error ? <p className="text-sm text-danger">That password isn&apos;t right.</p> : null;
}
