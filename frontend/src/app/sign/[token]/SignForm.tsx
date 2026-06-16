"use client";

/**
 * Client signing form for /sign/{token}.
 *
 * Three steps for the consultant:
 *  1. Download the contract PDF.
 *  2. Sign it offline with their own qualified-signature tool (Szafir end-user
 *     app, mObywatel, SimplySign, …) → produces a signed PAdES.
 *  3. Upload the signed PDF here → backend validates (pyHanko + EU DSS).
 *
 * Hits the public API with raw fetch (never the authed axios instance).
 */
import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Loader2,
  ShieldCheck,
  Upload,
  XCircle,
} from "lucide-react";

interface Verdict {
  status: string;
  is_qes: boolean;
  signature_level: string | null;
  signed_by: string | null;
  indication: string | null;
  dss_verified: boolean;
}

function browserApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

export default function SignForm({
  token,
  alreadySigned,
}: {
  token: string;
  alreadySigned: boolean;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(alreadySigned);

  const pdfUrl = `${browserApiBase()}/api/public/sign/${token}/pdf`;

  async function handleSubmit() {
    if (!file) {
      setError("Wybierz podpisany plik PDF.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setVerdict(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(
        `${browserApiBase()}/api/public/sign/${token}/submit`,
        { method: "POST", body: fd },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail =
          typeof data?.detail === "string"
            ? data.detail
            : "Nie udało się zweryfikować podpisu.";
        setError(detail);
        return;
      }
      setVerdict(data as Verdict);
      setDone(true);
    } catch {
      setError("Błąd połączenia. Spróbuj ponownie.");
    } finally {
      setSubmitting(false);
    }
  }

  if (done && !verdict) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 flex items-start gap-3">
        <CheckCircle2 className="h-6 w-6 text-green-600 shrink-0" />
        <div>
          <p className="font-medium">Umowa została już podpisana.</p>
          <p className="text-sm text-muted-foreground">
            Dziękujemy — nie są wymagane żadne dalsze działania.
          </p>
        </div>
      </div>
    );
  }

  if (verdict) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 space-y-3">
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-6 w-6 text-green-600" />
          <p className="font-semibold text-lg">Dokument przyjęty</p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {verdict.is_qes ? (
            <ShieldCheck className="h-5 w-5 text-green-600" />
          ) : (
            <AlertCircle className="h-5 w-5 text-amber-500" />
          )}
          <span>
            Podpis kwalifikowany (QES):{" "}
            <strong>
              {verdict.is_qes
                ? "TAK"
                : verdict.dss_verified
                  ? "NIE"
                  : "weryfikacja w toku"}
            </strong>
          </span>
        </div>
        {verdict.signed_by && (
          <p className="text-sm text-muted-foreground">
            Podpisano przez: {verdict.signed_by}
          </p>
        )}
        {verdict.signature_level && (
          <p className="text-sm text-muted-foreground">
            Poziom PAdES: {verdict.signature_level}
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          Możesz zamknąć tę stronę.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <ol className="space-y-4">
        <li className="rounded-xl border border-border bg-card p-5">
          <p className="font-medium mb-1">1. Pobierz umowę</p>
          <p className="text-sm text-muted-foreground mb-3">
            Pobierz dokument PDF, który masz podpisać.
          </p>
          <a
            href={pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg bg-secondary px-4 py-2 text-sm font-medium hover:bg-secondary/80"
          >
            <Download className="h-4 w-4" /> Pobierz umowę (PDF)
          </a>
        </li>

        <li className="rounded-xl border border-border bg-card p-5">
          <p className="font-medium mb-1">2. Podpisz swoim podpisem kwalifikowanym</p>
          <p className="text-sm text-muted-foreground">
            Podpisz pobrany plik własnym narzędziem do podpisu kwalifikowanego
            (np. Szafir, mObywatel, SimplySign). Zapisz podpisany plik PDF.
          </p>
        </li>

        <li className="rounded-xl border border-border bg-card p-5">
          <p className="font-medium mb-1">3. Wgraj podpisany dokument</p>
          <p className="text-sm text-muted-foreground mb-3">
            Wgraj podpisany plik PDF — zweryfikujemy podpis.
          </p>
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setError(null);
            }}
            className="block w-full text-sm mb-3 file:mr-3 file:rounded-lg file:border-0 file:bg-secondary file:px-4 file:py-2 file:text-sm file:font-medium"
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || !file}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            Wyślij podpisany dokument
          </button>
        </li>
      </ol>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 flex items-start gap-2 text-sm text-destructive">
          <XCircle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
