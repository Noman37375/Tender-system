"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email"));
    const password = String(f.get("password"));
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await api.login(email, password);
      else
        await api.register({
          org_name: String(f.get("org_name")),
          name: String(f.get("name")),
          email,
          password,
        });
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:outline-2 focus:outline-teal-700";

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-8 shadow-sm"
      >
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">TenderIQ</h1>
          <p className="text-sm text-slate-600">
            {mode === "login" ? "Sign in to your bid office" : "Create your organisation"}
          </p>
        </div>

        {mode === "register" && (
          <>
            <label className="block space-y-1 text-sm text-slate-700">
              <span>Organisation name</span>
              <input name="org_name" required className={input} />
            </label>
            <label className="block space-y-1 text-sm text-slate-700">
              <span>Your name</span>
              <input name="name" required autoComplete="name" className={input} />
            </label>
          </>
        )}
        <label className="block space-y-1 text-sm text-slate-700">
          <span>Email</span>
          <input name="email" type="email" required autoComplete="email" className={input} />
        </label>
        <label className="block space-y-1 text-sm text-slate-700">
          <span>Password</span>
          <input
            name="password"
            type="password"
            required
            minLength={mode === "register" ? 8 : undefined}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            className={input}
          />
        </label>

        {error && (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-teal-700 px-3 py-2 font-medium text-white hover:bg-teal-800 disabled:opacity-60"
        >
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
          className="w-full text-sm text-teal-800 underline"
        >
          {mode === "login" ? "New here? Create an organisation" : "Have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}
