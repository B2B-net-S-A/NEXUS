"use client";

/**
 * Formularz kontraktora: pobierz PDF → podpisz kwalifikowanym → wgraj.
 * Zwykły `fetch` do publicznego API (nigdy instancja axios z logowaniem).
 *
 * 21.10.2026 (etap 1b, makieta 17): krok 2 ma zakładki per narzędzie i wyraźne
 * „podpis w pliku PDF” — osobny plik z podpisem (XAdES, .sig) serwer odrzuca.
 *
 * 27.10.2026: po terminie strona mówi, kiedy minął, i daje „Poproś o nowy
 * link”. Nowy link prowadzi do tego samego PDF-a, więc podpisany plik przejdzie.
 *
 * 13.11.2026 (paczka, 0687): obok umowy mogą być dokumenty do startu (NDA,
 * oświadczenie). Każdy plik pobiera się i wgrywa osobno na tej samej stronie;
 * umowa idzie do B2B Network po ostatnim podpisanym pliku.
 */

import { useState } from "react";
import { CheckCircle2, Download, Loader2, Send, Upload } from "lucide-react";

import { SignedPdfField } from "@/components/v2/b2b-generator/esign/SignedPdfField";
import { parseDispositionFilename } from "@/lib/cv-generator";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  signedPdfProblem,
  type PublicSignDocument,
  type PublicSignState,
  type PublicSignView,
} from "@/lib/api/b2bEsign";

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

function base(token: string): string {
  return `${apiBase()}/api/public/b2b-sign/${encodeURIComponent(token)}`;
}

/** Pobierz PDF z trasy publicznej; nazwę pliku układa serwer. Zwraca błąd albo null. */
async function savePdf(url: string, fallbackName: string): Promise<string | null> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) return errorText(res);
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = parseDispositionFilename(res.headers.get("content-disposition") ?? "", fallbackName);
  a.click();
  URL.revokeObjectURL(href);
  return null;
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
    title: "mObywatel: za darmo, e-dowód i telefon z NFC",
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
    title: "SimplySign (Certum): podpis w chmurze",
    steps: [
      "Otwórz program do podpisu Certum (np. proSigner) i połącz się z SimplySign na telefonie.",
      "Wybierz pobrany PDF.",
      "Jako format wybierz PAdES (podpis w pliku PDF).",
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
      "Jako format wybierz PAdES (podpis w pliku PDF).",
      "Zapisz podpisany PDF i wgraj go w kroku 3.",
    ],
  },
  {
    id: "other",
    label: "Inny",
    title: "Inne narzędzie z podpisem kwalifikowanym",
    steps: [
      "Sigillum, EuroCert, mSzafir i inne: każdy podpis kwalifikowany z UE się liczy.",
      "Podpisz pobrany PDF bez zmian w treści.",
      "Jako format wybierz PAdES (podpis w pliku PDF).",
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
        z podpisem (.xades, .sig) zostanie odrzucony, bo umową ma zostać ten sam PDF.
      </p>
      <p className="text-sm text-muted-foreground">
        Nie masz podpisu kwalifikowanego? Najszybciej mObywatel z e-dowodem (za darmo) albo
        jednorazowy podpis mSzafir przez bank (ok. 15 zł). Wolisz podpisać ręcznie? Napisz do
        osoby, która wysłała link. Wyśle umowę mailem jak dotąd.
      </p>
    </div>
  );
}

interface PackageEntry {
  key: string;
  title: string;
  signed: boolean;
  pdfUrl: string;
  submitUrl: string;
  fallbackName: string;
}

function packageEntries(
  token: string,
  contractNumber: string,
  contractSigned: boolean,
  documents: PublicSignDocument[],
): PackageEntry[] {
  return [
    {
      key: "contract",
      title: `Umowa B2B nr ${contractNumber}`,
      signed: contractSigned,
      pdfUrl: `${base(token)}/pdf`,
      submitUrl: base(token),
      fallbackName: "Umowa B2B.pdf",
    },
    ...documents.map((d) => ({
      key: `document-${d.id}`,
      title: d.title,
      signed: d.signed,
      pdfUrl: `${base(token)}/documents/${d.id}/pdf`,
      submitUrl: `${base(token)}/documents/${d.id}`,
      fallbackName: `${d.title}.pdf`,
    })),
  ];
}

function UploadRow({
  entry,
  onView,
  onExpired,
}: {
  entry: PackageEntry;
  onView: (view: PublicSignView) => void;
  onExpired: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = file ? signedPdfProblem(file) : null;

  if (entry.signed) {
    return (
      <li className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />
        <span className="font-medium text-foreground">{entry.title}</span>
        <span className="ml-auto text-muted-foreground">podpis przyjęty</span>
      </li>
    );
  }

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(entry.submitUrl, { method: "POST", body: form });
      if (res.status === 410) {
        onExpired();
        return;
      }
      if (!res.ok) {
        setError(await errorText(res));
        return;
      }
      onView((await res.json()) as PublicSignView);
    } catch {
      setError("Brak połączenia z serwerem. Spróbuj ponownie.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="space-y-3 rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-sm font-medium text-foreground">{entry.title}</p>
      <SignedPdfField
        id={`b2b-sign-file-${entry.key}`}
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
        {busy ? "Sprawdzam podpis…" : "Wyślij podpisany plik"}
      </Button>
    </li>
  );
}

function PackageSteps({
  token,
  contractNumber,
  contractSigned,
  documents,
  onView,
  onExpired,
}: {
  token: string;
  contractNumber: string;
  contractSigned: boolean;
  documents: PublicSignDocument[];
  onView: (view: PublicSignView) => void;
  onExpired: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const entries = packageEntries(token, contractNumber, contractSigned, documents);
  const done = entries.filter((e) => e.signed).length;
  return (
    <ol className="space-y-6">
      <li className="space-y-2">
        <p className="font-semibold">1. Pobierz dokumenty ({entries.length})</p>
        <p className="text-sm text-muted-foreground">
          Przeczytaj każdy PDF. Nie zmieniaj w nich niczego, NEXUS porówna pliki z wysłanymi.
        </p>
        <ul className="space-y-2">
          {entries.map((entry) => (
            <li
              key={entry.key}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-4 py-2 text-sm"
            >
              <span className="font-medium text-foreground">{entry.title}</span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="ml-auto"
                disabled={entry.signed}
                onClick={async () => {
                  setError(null);
                  setError(await savePdf(entry.pdfUrl, entry.fallbackName));
                }}
              >
                <Download className="h-4 w-4" aria-hidden /> Pobierz PDF
              </Button>
            </li>
          ))}
        </ul>
        {error ? <Alert variant="error" title="Nie udało się pobrać pliku" description={error} /> : null}
      </li>
      <li className="space-y-2">
        <p className="font-semibold">2. Podpisz każdy plik podpisem kwalifikowanym: wybierz, czym podpisujesz</p>
        <ToolGuide />
      </li>
      <li className="space-y-3">
        <p className="font-semibold">
          3. Wgraj podpisane pliki · podpisane {done} z {entries.length}
        </p>
        <ul className="space-y-3">
          {entries.map((entry) => (
            <UploadRow key={entry.key} entry={entry} onView={onView} onExpired={onExpired} />
          ))}
        </ul>
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          <CheckCircle2 className="h-3 w-3" aria-hidden /> Sprawdzenie podpisu może potrwać do
          pół minuty na plik. Umowa trafi do B2B Network po ostatnim podpisanym pliku.
        </p>
      </li>
    </ol>
  );
}

export default function B2BSignForm({
  token,
  initialState,
  signedPdfUntil = null,
  expiredOn = null,
  renewalRequestedOn = null,
  contractNumber = "",
  contractSigned = false,
  documents = [],
}: {
  token: string;
  initialState: PublicSignState;
  /** Numer umowy do listy paczki. */
  contractNumber?: string;
  /** Paczka (0687): umowa już podpisana przez kontraktora. */
  contractSigned?: boolean;
  /** Paczka (0687): dokumenty obok umowy; pusta lista = sama umowa jak dotąd. */
  documents?: PublicSignDocument[];
  /** Data (dd.mm.rrrr), do której link daje pobrać kopię; null = kopii w linku nie ma. */
  signedPdfUntil?: string | null;
  /** Data (dd.mm.rrrr) końca terminu, gdy link wygasł. */
  expiredOn?: string | null;
  /** Kontraktor już poprosił o nowy link: dzień (dd.mm.rrrr). */
  renewalRequestedOn?: string | null;
}) {
  const [state, setState] = useState<PublicSignState>(initialState);
  const [packageView, setPackageView] = useState({ contractSigned, documents });
  const [requestedOn, setRequestedOn] = useState<string | null>(renewalRequestedOn);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (state === "completed") {
    // 26.10.2026: kopia z linku przez 30 dni i mailem (wcześniej nie wychodziła).
    return (
      <div className="space-y-3">
        <Alert
          variant="success"
          title="Umowa podpisana przez obie strony"
          description={
            signedPdfUntil
              ? "Oba podpisy kwalifikowane sprawdzone. Pobierz swoją kopię, wysłaliśmy ją też mailem."
              : "Kopię podpisaną przez obie strony dostaniesz od osoby z B2B Network."
          }
        />
        {signedPdfUntil ? (
          <>
            <Button
              type="button"
              onClick={async () => {
                setError(null);
                setError(await savePdf(`${base(token)}/signed-pdf`, "Umowa B2B podpisana.pdf"));
              }}
            >
              <Download className="h-4 w-4" aria-hidden /> Pobierz umowę podpisaną przez obie strony
            </Button>
            <p className="text-sm text-muted-foreground">Link działa do {signedPdfUntil}.</p>
          </>
        ) : null}
        {error ? <Alert variant="error" title="Nie udało się pobrać pliku" description={error} /> : null}
      </div>
    );
  }
  if (state === "signed_by_you") {
    return (
      <Alert
        variant="success"
        title="Dziękujemy, podpis przyjęty"
        description={
          packageView.documents.length
            ? "Wszystkie podpisy kwalifikowane sprawdzone. Umowa trafia do podpisu B2B Network."
            : "Podpis kwalifikowany sprawdzony. Umowa trafia do podpisu B2B Network."
        }
      />
    );
  }
  if (state === "expired") {
    const askForLink = async () => {
      setBusy(true);
      setError(null);
      try {
        const res = await fetch(`${base(token)}/renewal`, { method: "POST" });
        if (!res.ok) {
          setError(await errorText(res));
          return;
        }
        const view = (await res.json()) as PublicSignView;
        setRequestedOn(
          view.renewal_requested_at
            ? new Date(view.renewal_requested_at).toLocaleDateString("pl-PL", {
                timeZone: "Europe/Warsaw",
              })
            : new Date().toLocaleDateString("pl-PL"),
        );
      } catch {
        setError("Brak połączenia z serwerem. Spróbuj ponownie.");
      } finally {
        setBusy(false);
      }
    };
    return (
      <div className="space-y-4">
        <Alert
          variant="warning"
          title={expiredOn ? `Termin na podpis minął ${expiredOn}` : "Termin na podpis minął"}
          description="Umowa jest ta sama i nadal czeka na Twój podpis. Poproś o nowy link."
        />
        {requestedOn ? (
          <Alert
            variant="success"
            title="Prośba wysłana"
            description={`Osoba z B2B Network, która wysłała umowę, dostała Twoją prośbę ${requestedOn}. Nowy link przyjdzie mailem.`}
          />
        ) : (
          <Button type="button" variant="primary" disabled={busy} onClick={() => void askForLink()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Send className="h-4 w-4" aria-hidden />}
            Poproś o nowy link
          </Button>
        )}
        <p className="text-sm text-muted-foreground">
          Masz już plik podpisany podpisem kwalifikowanym? Zachowaj go. Nowy link go przyjmie, bo umowa
          się nie zmieniła.
        </p>
        {error ? <Alert variant="error" title="Nie udało się wysłać prośby" description={error} /> : null}
      </div>
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

  if (packageView.documents.length) {
    return (
      <PackageSteps
        token={token}
        contractNumber={contractNumber}
        contractSigned={packageView.contractSigned}
        documents={packageView.documents}
        onView={(view) => {
          setPackageView({
            contractSigned: Boolean(view.contract_signed),
            documents: view.documents ?? [],
          });
          setState(view.status);
        }}
        onExpired={() => setState("expired")}
      />
    );
  }

  const download = async () => {
    setError(null);
    // Nazwę („Umowa B2B [nr] Nazwisko Imię”) układa serwer (26.10.2026).
    setError(await savePdf(`${base(token)}/pdf`, "Umowa B2B.pdf"));
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(base(token), { method: "POST", body: form });
      if (res.status === 410) {
        // Termin minął w trakcie: strona przechodzi na „Poproś o nowy link”.
        setState("expired");
        return;
      }
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
          Przeczytaj PDF. Nie zmieniaj w nim niczego, NEXUS porówna plik z wysłanym.
        </p>
        <Button type="button" variant="outline" onClick={() => void download()}>
          <Download className="h-4 w-4" aria-hidden /> Pobierz PDF
        </Button>
      </li>
      <li className="space-y-2">
        <p className="font-semibold">2. Podpisz podpisem kwalifikowanym: wybierz, czym podpisujesz</p>
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
