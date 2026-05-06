"use client";

/**
 * Public CV viewer — token-based link do brandowanego CV per rekrutacja.
 *
 * Phase: CV per rekrutacja (PR2 — Faza 4). Rekruter klika "Wyślij klientowi"
 * → finalizes brandowane CV → generuje token (POST /share-token) → kopiuje
 * link `/cv/{token}` → klient otwiera w przeglądarce bez logowania → widzi
 * CV w iframe.
 *
 * PII safety: response zawiera tylko first_name + job_title + cv_html +
 * expires_at. Email/phone/lastname NIE są ujawniane na top-level (mogą być
 * w cv_html jeśli rekruter wybrał template `standard`).
 */

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import axios from "axios";
import { Printer, AlertCircle, Sparkles } from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.dynaminds.pl";

interface PublicCVView {
  candidate_first_name: string | null;
  job_title: string | null;
  cv_html: string;
  expires_at: string | null;
}

function getErrorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response
    ?.data?.detail;
  return detail ?? "Nie udało się wczytać CV.";
}

export default function PublicCvPage() {
  const params = useParams();
  const token = String(params?.token ?? "");

  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<PublicCVView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await axios.get<PublicCVView>(
          `${API_BASE}/api/public/cv/${token}`,
        );
        setView(res.data);
      } catch (e) {
        setErrorStatus(
          (e as { response?: { status?: number } })?.response?.status ?? null,
        );
        setError(getErrorMessage(e));
      } finally {
        setLoading(false);
      }
    }
    if (token) load();
  }, [token]);

  if (loading) {
    return (
      <main className="max-w-4xl mx-auto p-6 pt-16">
        <div className="animate-pulse text-center text-sm text-muted-foreground">
          Ładowanie CV…
        </div>
      </main>
    );
  }

  if (error || !view) {
    const heading =
      errorStatus === 410 ? "Link wygasł" : "Link niedostępny";
    return (
      <main className="max-w-xl mx-auto p-6 pt-16">
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 dark:border-red-900 dark:bg-red-950 p-6 text-center">
          <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-3" />
          <h2 className="text-lg font-semibold mb-1">{heading}</h2>
          <p className="text-sm text-destructive dark:text-red-300">
            {error ?? "Skontaktuj się z osobą, która udostępniła Ci ten link."}
          </p>
        </div>
      </main>
    );
  }

  const expiresLabel = view.expires_at
    ? new Date(view.expires_at).toLocaleDateString("pl-PL", {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : null;

  return (
    <main className="max-w-5xl mx-auto p-4 sm:p-6 pt-6">
      {/* Header */}
      <div className="mb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
            CV kandydata
          </p>
          <h1 className="text-xl sm:text-2xl font-semibold">
            {view.candidate_first_name ?? "Kandydat"}
            {view.job_title ? (
              <span className="ml-2 text-base font-normal text-muted-foreground">
                — {view.job_title}
              </span>
            ) : null}
          </h1>
          {expiresLabel ? (
            <p className="text-xs text-muted-foreground mt-1">
              Link aktywny do {expiresLabel}
            </p>
          ) : null}
        </div>
        <button
          onClick={() => window.print()}
          className="inline-flex items-center justify-center gap-2 rounded-md bg-primary hover:bg-primary/90 text-white px-4 py-2 text-sm font-medium shadow-sm"
        >
          <Printer className="h-4 w-4" />
          Drukuj / Zapisz jako PDF
        </button>
      </div>

      {/* CV iframe — sandboxed, srcDoc-rendered */}
      <div className="rounded-lg border border-border dark:border-border bg-card shadow-sm overflow-hidden">
        <iframe
          title="CV"
          srcDoc={view.cv_html}
          sandbox="allow-same-origin"
          className="w-full"
          style={{ height: "calc(100vh - 220px)", minHeight: 600 }}
        />
      </div>

      {/* Footer brand */}
      <footer className="mt-6 flex items-center justify-center gap-2 text-xs text-muted-foreground">
        <Sparkles className="h-3.5 w-3.5" />
        <span>Nexus · B2B.net S.A.</span>
      </footer>
    </main>
  );
}
