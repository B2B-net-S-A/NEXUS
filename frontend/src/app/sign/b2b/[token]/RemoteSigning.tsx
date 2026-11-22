"use client";

/**
 * „Podpisz w NEXUSIE” na stronie kontraktora (kierunek K1, makieta wariant C,
 * 22.11.2026). Kontraktor nie pobiera i nie wgrywa plików: NEXUS przekierowuje
 * do dostawcy podpisu w chmurze, kontraktor zatwierdza komplet w aplikacji
 * i wraca na `/sign/b2b/{token}?remote={session_id}`.
 *
 * Podpis kwalifikowany jest wymagany tylko przy umowie (i dokumentach, przy
 * których wymaga go klient). Dokumenty „dowolny podpis” kontraktor podpisuje
 * razem z umową tym samym zatwierdzeniem albo akceptuje kodem z maila (0754).
 * Strona pokazuje tę drogę tylko, gdy serwer zwróci `remote_signing.available`.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  CheckCircle2,
  Download,
  Fingerprint,
  IdCard,
  Landmark,
  Loader2,
  Lock,
  Smartphone,
  Video,
} from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type {
  PublicRemoteSession,
  PublicSignDocument,
  PublicSignView,
  RemoteSigningMethod,
} from "@/lib/api/b2bEsign";
import { pluralPl } from "@/lib/plural-pl";
import {
  RemotePollError,
  REMOTE_POLL_FAILED,
  leaveForProvider,
  useRemoteSigningPoll,
} from "@/lib/remote-signing";

import { base, errorText, savePdf } from "./public-sign-api";

function documentsLabel(count: number): string {
  return count === 1 ? "umowę" : `${count} ${pluralPl(count, "dokument", "dokumenty", "dokumentów")}`;
}

function requirementOf(doc: PublicSignDocument): "qualified" | "any" {
  // Wiersze sprzed 0754 nie mają pola i zostają przy kwalifikowanym.
  return doc.requirement ?? "qualified";
}

function RequirementBadge({ qualified }: { qualified: boolean }) {
  return qualified ? (
    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
      wymagany podpis kwalifikowany
    </span>
  ) : (
    <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
      dowolny podpis
    </span>
  );
}

function ChoiceCard({
  name,
  checked,
  onChange,
  title,
  text,
  icon,
  large = false,
}: {
  name: string;
  checked: boolean;
  onChange: () => void;
  title: string;
  text: string;
  icon?: ReactNode;
  large?: boolean;
}) {
  const frame = large ? "rounded-xl p-4" : "rounded-lg p-3";
  return (
    <label
      className={
        checked
          ? `flex cursor-pointer items-start gap-3 border-2 border-primary bg-primary/5 ${frame}`
          : `flex cursor-pointer items-start gap-3 border border-border bg-card hover:bg-muted/50 ${frame}`
      }
    >
      <input
        type="radio"
        name={name}
        className="mt-1 accent-primary"
        checked={checked}
        onChange={onChange}
      />
      {icon}
      <span className="space-y-0.5">
        <span className={large ? "block font-semibold text-foreground" : "block text-sm font-medium text-foreground"}>
          {title}
        </span>
        <span className={large ? "block text-sm text-muted-foreground" : "block text-xs text-muted-foreground"}>
          {text}
        </span>
      </span>
    </label>
  );
}

/** „Nie mam podpisu kwalifikowanego”: co czeka u dostawcy, zanim podpisze. */
function IdentityNote() {
  const methods = [
    { icon: Landmark, title: "Bankowość elektroniczna", note: "Najszybciej, ok. 2 minuty" },
    { icon: IdCard, title: "e-dowód w telefonie", note: "Telefon z NFC i kod CAN z dowodu" },
    { icon: Video, title: "Rozmowa wideo", note: "Ok. 5 do 10 minut, z dowodem w ręku" },
  ];
  return (
    <section className="space-y-3 rounded-xl border border-primary/30 bg-card p-4">
      <div>
        <h3 className="font-semibold text-foreground">Najpierw potwierdzisz, że to Ty</h3>
        <p className="text-sm text-muted-foreground">
          Raz, przed podpisem. Potem od razu podpiszesz cały komplet. Jednorazowy podpis
          kwalifikowany wystawia dostawca usług zaufania, płaci za niego B2Bnetwork.
        </p>
      </div>
      <ul className="space-y-2">
        {methods.map((m) => (
          <li key={m.title} className="flex items-center gap-3 rounded-lg border border-border px-4 py-2.5">
            <m.icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
            <span>
              <span className="block text-sm font-medium text-foreground">{m.title}</span>
              <span className="block text-xs text-muted-foreground">{m.note}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Sposób wybierzesz na stronie dostawcy. Po weryfikacji wrócisz tutaj.
      </p>
    </section>
  );
}

export function RemoteChoice({
  token,
  contractNumber,
  documents,
  providerLabel,
  codeBlock,
  onExpired,
  onOwnTool,
}: {
  token: string;
  contractNumber: string;
  documents: PublicSignDocument[];
  providerLabel: string | null;
  /** Akceptacja kodem dla otwartych dokumentów „dowolny podpis” (ten sam blok co dotąd). */
  codeBlock: ReactNode;
  onExpired: () => void;
  /** „Wolę podpisać u siebie i wgrać pliki”: dzisiejsza droga. */
  onOwnTool: () => void;
}) {
  const [method, setMethod] = useState<RemoteSigningMethod>("own_certificate");
  const [other, setOther] = useState<"together" | "code">("together");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = documents.filter((d) => !d.signed);
  const clientQualified = open.filter((d) => requirementOf(d) === "qualified");
  const anyOpen = open.filter((d) => requirementOf(d) === "any");
  const anyInPackage = documents.some((d) => requirementOf(d) === "any");
  const included = clientQualified.concat(other === "together" ? anyOpen : []);
  const count = 1 + included.length;
  const allTogether = 1 + clientQualified.length + anyOpen.length;
  const names = anyOpen.map((d) => d.title).join(" i ");

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${base(token)}/remote/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_document_ids: included.map((d) => d.id), method }),
      });
      if (res.status === 410) {
        onExpired();
        return;
      }
      if (!res.ok) {
        setError(await errorText(res, "Nie udało się rozpocząć podpisu. Spróbuj ponownie za chwilę."));
        setBusy(false);
        return;
      }
      const started = (await res.json()) as { redirect_url: string };
      // Przycisk zostaje zablokowany: strona za chwilę przechodzi do dostawcy.
      leaveForProvider(started.redirect_url);
    } catch {
      setError("Nie udało się rozpocząć podpisu. Sprawdź połączenie i spróbuj ponownie.");
      setBusy(false);
    }
  };

  const download = async (url: string, fallbackName: string) => {
    setError(null);
    setError(await savePdf(url, fallbackName));
  };

  return (
    <div className="space-y-5">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <h2 className="border-b border-border px-4 py-2.5 text-sm font-semibold text-foreground">
          Dokumenty ({1 + documents.length})
        </h2>
        <ul>
          <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
            <span className="text-sm font-medium text-foreground">Umowa B2B nr {contractNumber}</span>
            <RequirementBadge qualified />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto"
              aria-label={`Pobierz PDF: Umowa B2B nr ${contractNumber}`}
              onClick={() => void download(`${base(token)}/pdf`, "Umowa B2B.pdf")}
            >
              <Download className="h-4 w-4" aria-hidden /> Pobierz PDF
            </Button>
          </li>
          {documents.map((d) => (
            <li
              key={d.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-4 py-2.5"
            >
              <span className="text-sm font-medium text-foreground">{d.title}</span>
              {d.signed ? (
                <span className="ml-auto flex items-center gap-1 text-sm text-muted-foreground">
                  <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
                  {d.signed_via === "email_code" ? "zaakceptowane kodem" : "podpis przyjęty"}
                </span>
              ) : (
                <>
                  <RequirementBadge qualified={requirementOf(d) === "qualified"} />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    aria-label={`Pobierz PDF: ${d.title}`}
                    onClick={() =>
                      void download(`${base(token)}/documents/${d.id}/pdf`, `${d.title}.pdf`)
                    }
                  >
                    <Download className="h-4 w-4" aria-hidden /> Pobierz PDF
                  </Button>
                </>
              )}
            </li>
          ))}
        </ul>
        {anyInPackage && clientQualified.length === 0 ? (
          <p className="border-t border-border bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
            Umowa przenosi autorskie prawa majątkowe, dlatego tylko ona wymaga podpisu kwalifikowanego.
          </p>
        ) : null}
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold text-foreground">1. Jak podpiszesz umowę?</h2>
        <div className="space-y-3" role="radiogroup" aria-label="Jak podpiszesz umowę">
          <ChoiceCard
            name="b2b-remote-method"
            large
            checked={method === "own_certificate"}
            onChange={() => setMethod("own_certificate")}
            icon={<Smartphone className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />}
            title="Mam podpis kwalifikowany w telefonie"
            text={`SimplySign, mSzafir albo inny podpis w chmurze. Zatwierdzisz ${documentsLabel(count)} jednym potwierdzeniem w aplikacji.`}
          />
          <ChoiceCard
            name="b2b-remote-method"
            large
            checked={method === "one_time"}
            onChange={() => setMethod("one_time")}
            icon={<Fingerprint className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />}
            title="Nie mam podpisu kwalifikowanego"
            text="Potwierdzisz tożsamość przez bank, e-dowód albo rozmowę wideo i dostaniesz jednorazowy podpis. Koszt pokrywa B2Bnetwork."
          />
        </div>
        {method === "one_time" ? <IdentityNote /> : null}
      </section>

      {anyOpen.length ? (
        <section className="space-y-3">
          <h2 className="font-semibold text-foreground">2. {names}: wybierz sposób</h2>
          <div className="space-y-2" role="radiogroup" aria-label="Jak podpiszesz pozostałe dokumenty">
            <ChoiceCard
              name="b2b-remote-other"
              checked={other === "together"}
              onChange={() => setOther("together")}
              title="Razem z umową, tym samym podpisem kwalifikowanym"
              text={`Jedno zatwierdzenie w aplikacji na ${documentsLabel(allTogether)}. Nic więcej nie robisz.`}
            />
            <ChoiceCard
              name="b2b-remote-other"
              checked={other === "code"}
              onChange={() => setOther("code")}
              title="Kodem z maila"
              text={
                clientQualified.length
                  ? "Akceptujesz te dokumenty kodem wysłanym na Twój adres z umowy. Kwalifikowanym podpiszesz umowę i dokumenty, przy których wymaga go klient."
                  : "Akceptujesz dokumenty kodem wysłanym na Twój adres z umowy. Kwalifikowanym podpiszesz tylko umowę."
              }
            />
          </div>
          {other === "code" ? codeBlock : null}
        </section>
      ) : null}

      <div className="space-y-2">
        {error ? <Alert variant="error" title="Nie udało się" description={error} /> : null}
        <Button
          type="button"
          size="lg"
          className="w-full sm:w-auto"
          disabled={busy}
          onClick={() => void start()}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {method === "one_time"
            ? "Potwierdź tożsamość i podpisz"
            : `Podpisz ${documentsLabel(count)} w NEXUSIE`}
        </Button>
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Dokumenty zostają w NEXUSIE. Dostawca podpisu{providerLabel ? ` (${providerLabel})` : ""} dostaje
          tylko skrót pliku i potwierdza, że to Ty.
        </p>
      </div>

      <div className="rounded-xl border border-dashed border-border px-4 py-3">
        <button
          type="button"
          className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
          onClick={onOwnTool}
        >
          Wolę podpisać u siebie i wgrać pliki
        </button>
        <p className="mt-1 text-xs text-muted-foreground">
          Pobierzesz PDF, podpiszesz go swoim programem (PAdES, podpis w pliku) i wgrasz z powrotem.
        </p>
      </div>
    </div>
  );
}

/**
 * Po powrocie od dostawcy: czekamy na zatwierdzenie w aplikacji, potem na
 * wklejenie podpisu. `onDone` dostaje świeży widok strony (albo null).
 */
export function RemoteSessionPanel({
  token,
  sessionId,
  providerLabel,
  onDone,
  onExpired,
  onRestart,
}: {
  token: string;
  sessionId: string;
  providerLabel: string | null;
  onDone: (view: PublicSignView | null) => void;
  onExpired: () => void;
  onRestart: () => void;
}) {
  const { status, retry } = useRemoteSigningPoll<PublicRemoteSession>(sessionId, async (id) => {
    const res = await fetch(`${base(token)}/remote/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (res.status === 410) {
      onExpired();
      throw new RemotePollError("Termin na podpis minął.", true);
    }
    if (!res.ok) {
      throw new RemotePollError(await errorText(res, REMOTE_POLL_FAILED), res.status < 500);
    }
    return (await res.json()) as PublicRemoteSession;
  });

  const done = status.phase === "finished" && status.result.state === "done" ? status.result : null;
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });
  // Raz na stan końcowy: `done` to ten sam obiekt, dopóki sesja nie ruszy od nowa.
  useEffect(() => {
    if (done) onDoneRef.current(done.view);
  }, [done]);

  const restart = (
    <Button type="button" variant="outline" onClick={onRestart}>
      Zacznij od nowa
    </Button>
  );

  if (status.phase === "finished") {
    const { state, message } = status.result;
    if (state === "done") {
      return (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytuję podpisane dokumenty…
        </p>
      );
    }
    return (
      <div className="space-y-3">
        <Alert
          variant={state === "failed" ? "error" : "warning"}
          title={state === "failed" ? "Podpis nie został złożony" : "Podpis anulowany"}
          description={
            message ??
            (state === "failed"
              ? "Dostawca podpisu zgłosił błąd. Spróbuj ponownie albo podpisz u siebie i wgraj plik."
              : "Prośba o podpis została anulowana w aplikacji albo wygasła. Możesz zacząć od nowa.")
          }
        />
        <Button type="button" onClick={onRestart}>
          Spróbuj ponownie
        </Button>
      </div>
    );
  }
  if (status.phase === "timeout" || status.phase === "error") {
    return (
      <div className="space-y-3">
        <Alert
          variant={status.phase === "error" ? "error" : "warning"}
          title={
            status.phase === "error"
              ? "Nie udało się sprawdzić stanu podpisu"
              : "Nie mamy jeszcze odpowiedzi od dostawcy podpisu"
          }
          description={
            status.phase === "error"
              ? status.message
              : "Minęły 3 minuty bez potwierdzenia. Jeśli podpis jest już zatwierdzony w aplikacji, sprawdź jeszcze raz za chwilę."
          }
        />
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={retry}>
            Sprawdź jeszcze raz
          </Button>
          {restart}
        </div>
      </div>
    );
  }

  const signing = status.result?.state === "signing";
  const app = providerLabel ? `w aplikacji ${providerLabel}` : "w aplikacji dostawcy podpisu";
  return (
    <section
      className="space-y-4 rounded-xl border border-primary/30 bg-card p-5"
      aria-live="polite"
      aria-label="Podpis u dostawcy"
    >
      <div className="flex items-start gap-3">
        <Smartphone className="h-6 w-6 shrink-0 text-primary" aria-hidden />
        <div>
          <h2 className="font-semibold text-foreground">
            {signing ? "Podpis zatwierdzony, kończymy" : `Zatwierdź podpis ${app}`}
          </h2>
          <p className="text-sm text-muted-foreground">
            {signing
              ? "NEXUS dołącza podpis do dokumentów i sprawdza go na unijnej liście zaufanych. To potrwa chwilę."
              : "Na telefonie czeka prośba o podpis. Gdy ją zatwierdzisz, ta strona sama pokaże wynik."}
          </p>
          {status.result?.message ? (
            <p className="mt-1 text-sm text-foreground">{status.result.message}</p>
          ) : null}
        </div>
      </div>
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {signing ? "Dołączam podpis…" : "Czekam na zatwierdzenie…"}
      </p>
    </section>
  );
}

/** Wynik po podpisie w NEXUSIE: lista kompletu z tym, jak podpisano każdy plik. */
export function RemoteDone({ view }: { view: PublicSignView }) {
  const docs = view.documents ?? [];
  const total = 1 + docs.length;
  const ready = (view.contract_signed || view.status !== "waiting" ? 1 : 0) + docs.filter((d) => d.signed).length;
  const byCode = docs.some((d) => d.signed_via === "email_code");
  return (
    <div className="space-y-4">
      <Alert
        variant="success"
        title={`Gotowe: ${ready} z ${total}`}
        description={
          byCode
            ? "Podpis umowy sprawdzony na unijnej liście zaufanych, pozostałe dokumenty zaakceptowane. Umowa trafia do podpisu B2Bnetwork, a kopię z oboma podpisami dostaniesz mailem."
            : "Podpisy sprawdzone na unijnej liście zaufanych. Umowa trafia do podpisu B2Bnetwork, a kopię z oboma podpisami dostaniesz mailem."
        }
      />
      <ul className="overflow-hidden rounded-xl border border-border bg-card">
        <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />
          <span className="font-medium text-foreground">Umowa B2B nr {view.contract_number}</span>
          <span className="ml-auto text-muted-foreground">
            podpis kwalifikowany: {view.contractor_name}
          </span>
        </li>
        {docs.map((d) => (
          <li
            key={d.id}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-4 py-2.5 text-sm"
          >
            {d.signed ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />
            ) : (
              <Loader2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
            <span className="font-medium text-foreground">{d.title}</span>
            <span className="ml-auto text-muted-foreground">
              {!d.signed
                ? "czeka"
                : d.signed_via === "email_code"
                  ? "zaakceptowane kodem"
                  : `podpis kwalifikowany: ${view.contractor_name}`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
