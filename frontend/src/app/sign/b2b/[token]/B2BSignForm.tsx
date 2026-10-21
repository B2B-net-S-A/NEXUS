"use client";

/**
 * Formularz kontraktora: pobierz PDF → podpisz kwalifikowanym → wgraj.
 * Zwykły `fetch` do publicznego API (nigdy instancja axios z logowaniem).
 */

import { useState } from "react";
import { CheckCircle2, Download, Loader2, Upload } from "lucide-react";

import { SignedPdfField } from "@/components/v2/b2b-generator/esign/SignedPdfField";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  signedPdfProblem,
  type PublicSignState,
  type PublicSignView,
} from "@/lib/api/b2bEsign";

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

function base(token: string): string {
  return `${apiBase()}/api/public/b2b-sign/${encodeURIComponent(token)}`;
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // treść nie jest JSON-em
  }
  return "Nie udało się przyjąć pliku. Spróbuj ponownie za chwilę.";
}

export default function B2BSignForm({
  token,
  initialState,
}: {
  token: string;
  initialState: PublicSignState;
}) {
  const [state, setState] = useState<PublicSignState>(initialState);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (state === "signed_by_you" || state === "completed") {
    return (
      <Alert
        variant="success"
        title={state === "completed" ? "Umowa podpisana przez obie strony" : "Dziękujemy — podpis przyjęty"}
        description={
          state === "completed"
            ? "Kopię podpisaną przez obie strony dostaniesz od osoby z B2B Network."
            : "Podpis kwalifikowany sprawdzony. Umowa trafia do podpisu B2B Network."
        }
      />
    );
  }
  if (state === "closed") {
    return (
      <Alert
        variant="warning"
        title="Ta umowa nie czeka już na podpis"
        description="Link wygasł albo wysyłka została wycofana. Skontaktuj się z osobą z B2B Network."
      />
    );
  }

  const download = async () => {
    setError(null);
    const res = await fetch(`${base(token)}/pdf`, { cache: "no-store" });
    if (!res.ok) {
      setError(await errorText(res));
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "umowa_do_podpisu.pdf";
    a.click();
    URL.revokeObjectURL(url);
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(base(token), { method: "POST", body: form });
      if (!res.ok) {
        setError(await errorText(res));
        return;
      }
      const view = (await res.json()) as PublicSignView;
      setState(view.status);
    } catch {
      setError("Brak połączenia z serwerem. Spróbuj ponownie.");
    } finally {
      setBusy(false);
    }
  };

  const problem = file ? signedPdfProblem(file) : null;
  return (
    <ol className="space-y-6">
      <li className="space-y-2">
        <p className="font-semibold">1. Pobierz umowę</p>
        <p className="text-sm text-muted-foreground">
          Przeczytaj PDF. Nie zmieniaj w nim niczego — NEXUS porówna plik z wysłanym.
        </p>
        <Button type="button" variant="outline" onClick={() => void download()}>
          <Download className="h-4 w-4" aria-hidden /> Pobierz PDF
        </Button>
      </li>
      <li className="space-y-2">
        <p className="font-semibold">2. Podpisz podpisem kwalifikowanym</p>
        <p className="text-sm text-muted-foreground">
          Swoim narzędziem: SimplySign, Szafir, mSzafir, Sigillum albo e-dowód z certyfikatem
          kwalifikowanym. Nie masz podpisu? Jednorazowy podpis kwalifikowany mSzafir (KIR,
          przez bank albo mObywatel) kosztuje ok. 15 zł.
        </p>
      </li>
      <li className="space-y-3">
        <p className="font-semibold">3. Wgraj podpisany plik</p>
        <SignedPdfField
          id="b2b-sign-file"
          label="Podpisany PDF"
          file={file}
          onFile={setFile}
          disabled={busy}
        />
        {error ? <Alert variant="error" title="Podpis nie został przyjęty" description={error} /> : null}
        <Button type="button" disabled={!file || Boolean(problem) || busy} onClick={() => void submit()}>
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Upload className="h-4 w-4" aria-hidden />
          )}
          {busy ? "Sprawdzam podpis…" : "Wyślij podpisaną umowę"}
        </Button>
        {busy ? (
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <CheckCircle2 className="h-3 w-3" aria-hidden /> Sprawdzenie podpisu może potrwać do
            pół minuty.
          </p>
        ) : null}
      </li>
    </ol>
  );
}
