"use client";

/**
 * Formularz kontraktora: pobierz PDF → podpisz kwalifikowanym → wgraj.
 * Zwykły `fetch` do publicznego API (nigdy instancja axios z logowaniem).
 *
 * 21.10.2026 (etap 1b, makieta 17): krok 2 ma zakładki per narzędzie i wyraźne
 * „podpis w pliku PDF” — osobny plik z podpisem (XAdES, .sig) serwer odrzuca.
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

type Tool = "mobywatel" | "simplysign" | "szafir" | "other";

const TOOLS: { id: Tool; label: string; title: string; steps: string[] }[] = [
  {
    id: "mobywatel",
    label: "mObywatel",
    title: "mObywatel — za darmo, e-dowód i telefon z NFC",
    steps: [
      "Prześlij sobie pobrany PDF na telefon.",
      "W aplikacji mObywatel wybierz podpis kwalifikowany i wskaż ten plik.",
      "Wpisz numer CAN z dowodu i przyłóż dowód do telefonu.",
      "Zapisz podpisany PDF i wgraj go w kroku 3.",
    ],
  },
  {
    id: "simplysign",
    label: "SimplySign",
    title: "SimplySign (Certum) — podpis w chmurze",
    steps: [
      "Otwórz program do podpisu Certum (np. proSigner) i połącz się z SimplySign na telefonie.",
      "Wybierz pobrany PDF.",
      "Jako format wybierz PAdES — podpis w pliku PDF.",
      "Zapisz podpisany PDF i wgraj go w kroku 3.",
    ],
  },
  {
    id: "szafir",
    label: "Szafir / karta",
    title: "Szafir (KIR) albo inny program z kartą w czytniku",
    steps: [
      "Włóż kartę do czytnika i otwórz program do podpisu.",
      "Wybierz „Podpisz plik” i wskaż pobrany PDF.",
      "Jako format wybierz PAdES — podpis w pliku PDF.",
      "Zapisz podpisany PDF i wgraj go w kroku 3.",
    ],
  },
  {
    id: "other",
    label: "Inny",
    title: "Inne narzędzie z podpisem kwalifikowanym",
    steps: [
      "Sigillum, EuroCert, mSzafir i inne — każdy podpis kwalifikowany z UE się liczy.",
      "Podpisz pobrany PDF bez zmian w treści.",
      "Jako format wybierz PAdES — podpis w pliku PDF.",
    ],
  },
];

function ToolGuide() {
  const [tool, setTool] = useState<Tool>("mobywatel");
  const current = TOOLS.find((t) => t.id === tool) ?? TOOLS[0];
  return (
    <div className="space-y-3">
      <div role="tablist" aria-label="Czym podpisujesz" className="flex flex-wrap gap-1.5">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`b2b-sign-tab-${t.id}`}
            aria-selected={t.id === tool}
            aria-controls="b2b-sign-tool-panel"
            onClick={() => setTool(t.id)}
            className={
              t.id === tool
                ? "rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
                : "rounded-full border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-accent"
            }
          >
            {t.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="b2b-sign-tool-panel"
        aria-labelledby={`b2b-sign-tab-${current.id}`}
        className="rounded-lg bg-muted/60 px-4 py-3 text-sm"
      >
        <p className="font-medium text-foreground">{current.title}</p>
        <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-foreground">
          {current.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
      <p className="rounded-lg border border-warning/40 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
        <strong>Ważne:</strong> wybierz podpis <strong>w pliku PDF</strong> (PAdES). Osobny plik
        z podpisem (.xades, .sig) zostanie odrzucony — ten sam PDF ma zostać umową.
      </p>
      <p className="text-sm text-muted-foreground">
        Nie masz podpisu kwalifikowanego? Najszybciej mObywatel z e-dowodem (za darmo) albo
        jednorazowy podpis mSzafir przez bank (ok. 15 zł). Wolisz podpisać ręcznie? Napisz do
        osoby, która wysłała link — wyśle umowę mailem jak dotąd.
      </p>
    </div>
  );
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
        <p className="font-semibold">2. Podpisz podpisem kwalifikowanym — wybierz, czym podpisujesz</p>
        <ToolGuide />
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
