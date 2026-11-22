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
 *
 * 22.11.2026 (0754): kwalifikowany wymagany tylko przy umowie, która przenosi
 * prawa autorskie. Dokument z wymogiem „dowolny podpis” kontraktor akceptuje
 * kodem z maila albo wgrywa podpisany kwalifikowanym, jak dotąd.
 */

import { useState } from "react";
import { CheckCircle2, Download, KeyRound, Loader2, Mail, Send, Upload } from "lucide-react";

import { SignedPdfField } from "@/components/v2/b2b-generator/esign/SignedPdfField";
import { parseDispositionFilename } from "@/lib/cv-generator";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  signedPdfProblem,
  type DocumentRequirement,
  type DocumentSignedVia,
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

interface ToolTab {
  id: Tool;
  label: string;
  title: string;
  /** Akapit przed krokami: czego to narzędzie nie da. */
  note?: string;
  steps: string[];
}

// 22.11.2026: podpis z e-dowodu w mObywatelu (PIN2) to podpis osobisty
// (MSWiA, bez QcStatements), którego walidator nie przyjmie, a darmowy
// kwalifikowany z mObywatela jest tylko do spraw prywatnych. Zakładka zostaje,
// bo kontraktorzy jej szukają, ale nie obiecuje podpisu kwalifikowanego.
const TOOLS: ToolTab[] = [
  {
    id: "mobywatel",
    label: "mObywatel",
    title: "mObywatel: podpis osobisty tu nie wystarczy",
    note:
      "Podpis w mObywatelu z kodem PIN2 z e-dowodu to podpis osobisty, nie kwalifikowany. " +
      "NEXUS go nie przyjmie. Darmowe podpisy kwalifikowane w mObywatelu są według zasad " +
      "usługi tylko do spraw prywatnych, a umowa B2B dotyczy Twojej firmy.",
    steps: [
      "Kup jednorazowy podpis kwalifikowany, np. mSzafir przez bank (ok. 15 zł).",
      "Podpisz pobrany PDF bez zmian w treści.",
      "Jako format wybierz PAdES (podpis w pliku PDF).",
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
        {current.note ? <p className="mt-1 text-foreground">{current.note}</p> : null}
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
        Nie masz podpisu kwalifikowanego? Najszybciej jednorazowy podpis mSzafir przez bank
        (ok. 15 zł). Podpis osobisty z e-dowodu i profil zaufany nie wystarczą. Wolisz podpisać
        ręcznie? Napisz do osoby, która wysłała link. Wyśle umowę mailem jak dotąd.
      </p>
    </div>
  );
}

interface PackageEntry {
  key: string;
  /** Id dokumentu paczki; `null` = umowa. */
  documentId: number | null;
  title: string;
  signed: boolean;
  requirement: DocumentRequirement;
  signedVia: DocumentSignedVia | null;
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
      documentId: null,
      title: `Umowa B2B nr ${contractNumber}`,
      signed: contractSigned,
      requirement: "qualified" as const,
      signedVia: contractSigned ? ("qualified" as const) : null,
      pdfUrl: `${base(token)}/pdf`,
      submitUrl: base(token),
      fallbackName: "Umowa B2B.pdf",
    },
    ...documents.map((d) => ({
      key: `document-${d.id}`,
      documentId: d.id,
      title: d.title,
      signed: d.signed,
      requirement: d.requirement ?? ("qualified" as const),
      signedVia: d.signed_via ?? null,
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
        <span className="ml-auto text-muted-foreground">
          {entry.signedVia === "email_code" ? "zaakceptowane kodem" : "podpis przyjęty"}
        </span>
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

/**
 * Dokumenty bez wymogu kwalifikowanego (0754): kod z maila na adres z wysyłki.
 * Kod działa 15 minut i raz; nowy najwcześniej po minucie.
 */
function AcceptByCode({
  token,
  entries,
  email,
  onView,
  onExpired,
}: {
  token: string;
  entries: PackageEntry[];
  email: string | null;
  onView: (view: PublicSignView) => void;
  onExpired: () => void;
}) {
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ids = entries.map((e) => e.documentId).filter((id): id is number => id !== null);
  const digits = code.replace(/\D/g, "");

  const call = async (path: string, body?: unknown): Promise<PublicSignView | null> => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${base(token)}/${path}`, {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (res.status === 410) {
        onExpired();
        return null;
      }
      if (!res.ok) {
        setError(await errorText(res));
        return null;
      }
      return (await res.json()) as PublicSignView;
    } catch {
      setError("Brak połączenia z serwerem. Spróbuj ponownie.");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const requestCode = async () => {
    const view = await call("accept-code");
    if (view) setSent(true);
  };
  const accept = async () => {
    const view = await call("accept", { code: digits, document_ids: ids });
    if (view) onView(view);
  };

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-sm text-foreground">
        {entries.map((e) => e.title).join(", ")}: te dokumenty nie wymagają podpisu
        kwalifikowanego. Zaakceptuj je kodem z maila.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" disabled={busy} onClick={() => void requestCode()}>
          {busy && !sent ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Mail className="h-4 w-4" aria-hidden />
          )}
          {sent ? "Wyślij kod jeszcze raz" : "Wyślij kod"}
        </Button>
        {email ? <span className="text-sm text-muted-foreground">na adres {email}</span> : null}
      </div>
      {sent ? (
        <div className="space-y-1">
          <label htmlFor="b2b-accept-code" className="block text-sm text-muted-foreground">
            Kod z maila (6 cyfr, działa 15 minut)
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              id="b2b-accept-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={7}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="h-10 w-36 rounded-lg border border-border bg-background px-3 font-mono tracking-widest text-foreground"
            />
            <Button
              type="button"
              disabled={busy || digits.length !== 6}
              onClick={() => void accept()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <KeyRound className="h-4 w-4" aria-hidden />
              )}
              Akceptuję {entries.length === 1 ? "dokument" : `dokumenty (${entries.length})`}
            </Button>
          </div>
        </div>
      ) : null}
      {error ? <Alert variant="error" title="Nie udało się" description={error} /> : null}
      <p className="text-xs text-muted-foreground">
        NEXUS zapisze, kto, kiedy i który plik zaakceptował.
      </p>
    </div>
  );
}

function PackageSteps({
  token,
  contractNumber,
  contractSigned,
  documents,
  acceptEmail,
  onView,
  onExpired,
}: {
  token: string;
  contractNumber: string;
  contractSigned: boolean;
  documents: PublicSignDocument[];
  acceptEmail: string | null;
  onView: (view: PublicSignView) => void;
  onExpired: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [uploadAny, setUploadAny] = useState(false);
  const entries = packageEntries(token, contractNumber, contractSigned, documents);
  const done = entries.filter((e) => e.signed).length;
  const qualified = entries.filter((e) => e.requirement === "qualified");
  const anyDocs = entries.filter((e) => e.requirement === "any");
  const anyOpen = anyDocs.filter((e) => !e.signed);
  const qualifiedTitles = qualified.length === 1 ? "umowę" : "umowę i dokumenty oznaczone „kwalifikowany”";
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
              <span
                className={
                  entry.requirement === "qualified"
                    ? "rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                    : "rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
                }
              >
                {entry.requirement === "qualified" ? "podpis kwalifikowany" : "dowolny podpis"}
              </span>
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
        <p className="font-semibold">
          {anyDocs.length
            ? `2. Podpisz ${qualifiedTitles} podpisem kwalifikowanym: wybierz, czym podpisujesz`
            : "2. Podpisz każdy plik podpisem kwalifikowanym: wybierz, czym podpisujesz"}
        </p>
        <ToolGuide />
      </li>
      <li className="space-y-3">
        <p className="font-semibold">
          3. Wgraj podpisane pliki · gotowe {done} z {entries.length}
        </p>
        <ul className="space-y-3">
          {(uploadAny ? entries : qualified.concat(anyDocs.filter((e) => e.signed))).map((entry) => (
            <UploadRow key={entry.key} entry={entry} onView={onView} onExpired={onExpired} />
          ))}
        </ul>
        {anyOpen.length && !uploadAny ? (
          <AcceptByCode
            token={token}
            entries={anyOpen}
            email={acceptEmail}
            onView={onView}
            onExpired={onExpired}
          />
        ) : null}
        {anyOpen.length ? (
          <button
            type="button"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
            onClick={() => setUploadAny((v) => !v)}
          >
            {uploadAny
              ? "Wolę zaakceptować pozostałe dokumenty kodem z maila"
              : "Wolę wgrać pozostałe dokumenty podpisane kwalifikowanym"}
          </button>
        ) : null}
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          <CheckCircle2 className="h-3 w-3" aria-hidden /> Sprawdzenie podpisu może potrwać do
          pół minuty na plik. Umowa trafi do B2Bnetwork po ostatnim gotowym dokumencie.
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
  acceptEmail = null,
}: {
  token: string;
  initialState: PublicSignState;
  /** 0754: zamaskowany adres, na który idzie kod; null = nie ma czego akceptować kodem. */
  acceptEmail?: string | null;
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
  const [packageView, setPackageView] = useState({ contractSigned, documents, acceptEmail });
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
              : "Kopię podpisaną przez obie strony dostaniesz od osoby z B2Bnetwork."
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
          packageView.documents.some((d) => d.signed_via === "email_code")
            ? "Podpis umowy sprawdzony, pozostałe dokumenty zaakceptowane. Umowa trafia do podpisu B2Bnetwork."
            : packageView.documents.length
            ? "Wszystkie podpisy kwalifikowane sprawdzone. Umowa trafia do podpisu B2Bnetwork."
            : "Podpis kwalifikowany sprawdzony. Umowa trafia do podpisu B2Bnetwork."
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
            description={`Osoba z B2Bnetwork, która wysłała umowę, dostała Twoją prośbę ${requestedOn}. Nowy link przyjdzie mailem.`}
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
        description="Link wygasł albo wysyłka została wycofana. Skontaktuj się z osobą z B2Bnetwork."
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
        acceptEmail={packageView.acceptEmail}
        onView={(view) => {
          setPackageView({
            contractSigned: Boolean(view.contract_signed),
            documents: view.documents ?? [],
            acceptEmail: view.accept_code_email ?? null,
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
