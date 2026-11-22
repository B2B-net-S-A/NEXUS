"use client";

/**
 * Które ogłoszenie w strefie Pracuj.pl to ta rekrutacja (23.11.2026).
 *
 * Aplikacje z Pracuj.pl nie trafiały do rekrutacji ogłoszenia: strefa zna tylko
 * swój numer ogłoszenia, a tytuły się powtarzają (22.11 trzy aktywne „Tester
 * Manualny (k/m/x)”). Delivery Lead wybiera ogłoszenie z listy z importu,
 * NEXUS tylko podpowiada po tytule. Połączenie dociąga zaległe aplikacje do
 * „Nowi”. Reguły: `docs/claude/rekrutacja-tworzenie/aplikacje-z-pracuj-do-rekrutacji.md`.
 */

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jobAdApi,
  jobAdQueryKey,
  pracujUnpairedQueryKey,
  type PracujAd,
  type PracujAdsPanel,
  type PracujPairResult,
} from "@/lib/api/jobAd";
import { cn, formatDate } from "@/lib/utils";

export type PracujAdPairingApi = Pick<typeof jobAdApi, "pairPracujAd" | "unpairPracujAd">;

/** Ile ogłoszeń widać od razu; reszta po „Pokaż wszystkie”. */
const FIRST_OPTIONS = 3;

export interface PracujAdPairingProps {
  jobId: number;
  panel: PracujAdsPanel;
  /** DL rekrutacji, Head of Recruitment, admin — reszta widzi tylko stan. */
  canPair: boolean;
  jobClosed?: boolean;
  api?: PracujAdPairingApi;
}

export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const tens = n % 100;
  const units = n % 10;
  return units >= 2 && units <= 4 && (tens < 12 || tens > 14) ? few : many;
}

export function applicationsText(n: number): string {
  return `${n} ${plural(n, "aplikacja", "aplikacje", "aplikacji")}`;
}

export function pairedMessage(result: PracujPairResult): string {
  if (result.job_not_open) {
    return "Połączone. Rekrutacja jest zamknięta, więc nikt nie trafił do „Nowi”.";
  }
  const parts = [
    result.added
      ? `${result.added} ${plural(result.added, "osoba trafiła", "osoby trafiły", "osób trafiło")} do „Nowi”`
      : "nikt nowy nie trafił do „Nowi”",
  ];
  if (result.already) parts.push(`${result.already} już ${plural(result.already, "jest", "są", "jest")} w rekrutacji`);
  if (result.skipped) parts.push(`${result.skipped} zatrzymały bramki (np. czarna lista, konflikt klienta)`);
  return `Połączone: ${parts.join(", ")}.`;
}

function adMeta(ad: PracujAd): string {
  return [
    `nr ${ad.strefa_id}`,
    `od ${formatDate(ad.first_seen_at)}`,
    applicationsText(Math.max(ad.applications, ad.logged_applications)),
  ].join(" · ");
}

export function PracujAdPairing({
  jobId,
  panel,
  canPair,
  jobClosed = false,
  api = jobAdApi,
}: PracujAdPairingProps) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const suggested = panel.options.find((ad) => ad.suggested) ?? null;
  // Podpowiedź otwiera wybór od razu; bez niej wybór czeka na kliknięcie.
  const [open, setOpen] = useState(panel.paired.length === 0 && suggested !== null);
  const [picked, setPicked] = useState<string | null>(suggested?.strefa_id ?? null);
  const [showAll, setShowAll] = useState(false);
  const [search, setSearch] = useState("");

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: jobAdQueryKey(jobId) });
    void queryClient.invalidateQueries({ queryKey: pracujUnpairedQueryKey });
  };

  const pair = useMutation({
    mutationFn: (strefaId: string) => api.pairPracujAd(jobId, strefaId),
    onSuccess: (result) => {
      showSuccess(pairedMessage(result));
      setOpen(false);
      refresh();
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się połączyć ogłoszenia. Spróbuj ponownie.")),
  });

  const unpair = useMutation({
    mutationFn: (strefaId: string) => api.unpairPracujAd(jobId, strefaId),
    onSuccess: refresh,
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się odłączyć ogłoszenia. Spróbuj ponownie.")),
  });

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle) {
      return panel.options.filter(
        (ad) => ad.title.toLowerCase().includes(needle) || ad.strefa_id.includes(needle),
      );
    }
    return showAll ? panel.options : panel.options.slice(0, FIRST_OPTIONS);
  }, [panel.options, search, showAll]);

  const pickedAd = panel.options.find((ad) => ad.strefa_id === picked) ?? null;
  const busy = pair.isPending || unpair.isPending;

  const confirmUnpair = async (ad: PracujAd) => {
    const confirmed = await askConfirm({
      title: "Odłączyć ogłoszenie z Pracuj.pl?",
      description:
        "Nowe aplikacje z tego ogłoszenia przestaną trafiać do tej rekrutacji. Osoby, które już są w „Nowi”, zostają.",
      confirmLabel: "Odłącz",
    });
    if (confirmed) unpair.mutate(ad.strefa_id);
  };

  if (!canPair && panel.paired.length === 0) return null;

  return (
    <div className="flex flex-col gap-2" data-testid="pracuj-ad-pairing">
      {panel.paired.map((ad) => (
        <div
          key={ad.strefa_id}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs"
          data-testid="pracuj-ad-paired"
        >
          <span className="text-foreground">
            Aplikacje z ogłoszenia <span className="font-medium">{ad.title}</span> ({adMeta(ad)})
            trafiają do „Nowi”
          </span>
          {!ad.live ? <span className="text-muted-foreground">· zniknęło ze strefy</span> : null}
          {canPair ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-xs"
              disabled={busy}
              onClick={() => void confirmUnpair(ad)}
            >
              Odłącz
            </Button>
          ) : null}
        </div>
      ))}

      {canPair && !jobClosed && !open ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {panel.paired.length === 0 ? (
            <span>Aplikacje z Pracuj.pl nie trafiają do tej rekrutacji, dopóki nie wskażesz ogłoszenia.</span>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 px-2.5"
            disabled={busy}
            onClick={() => setOpen(true)}
            data-testid="pracuj-ad-pick-open"
            data-tour="job-ad.pracuj.pair"
          >
            {panel.paired.length ? "Dodaj kolejne ogłoszenie" : "Wskaż ogłoszenie na Pracuj.pl"}
          </Button>
        </div>
      ) : null}

      {canPair && !jobClosed && open ? (
        <fieldset
          className="flex flex-col gap-2 rounded-md border border-dashed border-primary/40 bg-primary/5 px-3 py-2"
          data-testid="pracuj-ad-picker"
          data-tour="job-ad.pracuj.pair"
        >
          <legend className="px-1 text-[13px] font-medium text-foreground">
            Które ogłoszenie w strefie Pracuj.pl to ta rekrutacja?
          </legend>
          <p className="text-xs text-muted-foreground">
            {panel.last_import_at
              ? `Lista z importu z ${formatDate(panel.last_import_at)}. Aplikacje z wybranego ogłoszenia trafią do „Nowi”.`
              : "Import z Pracuj.pl jeszcze nie przysłał listy ogłoszeń."}
          </p>
          {panel.options.length > FIRST_OPTIONS ? (
            <Input
              value={search}
              placeholder="Szukaj po tytule albo numerze"
              aria-label="Szukaj ogłoszenia"
              className="h-8 text-[13px]"
              onChange={(event) => setSearch(event.target.value)}
            />
          ) : null}
          {visible.length ? (
            <ul className="flex flex-col gap-1.5" role="radiogroup" aria-label="Ogłoszenia z Pracuj.pl">
              {visible.map((ad) => {
                const selected = ad.strefa_id === picked;
                return (
                  <li key={ad.strefa_id}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => setPicked(ad.strefa_id)}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-md border px-2.5 py-1.5 text-left",
                        selected ? "border-primary bg-card" : "border-border bg-card/60",
                      )}
                    >
                      <span
                        aria-hidden="true"
                        className={cn(
                          "mt-1 h-3 w-3 flex-none rounded-full border-2",
                          selected ? "border-primary bg-primary" : "border-muted-foreground",
                        )}
                      />
                      <span className="flex min-w-0 flex-col">
                        <span className="text-[13px] text-foreground">{ad.title}</span>
                        <span className="text-xs text-muted-foreground">
                          {adMeta(ad)}
                          {ad.suggested ? " · pasuje tytułem" : ""}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : panel.last_import_at ? (
            <p className="text-xs text-muted-foreground">
              {search ? "Nic nie pasuje." : "Wszystkie ogłoszenia ze strefy są już połączone."}
            </p>
          ) : null}
          {!search && panel.options.length > FIRST_OPTIONS ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 self-start px-2 text-xs"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll ? "Pokaż mniej" : `Pokaż wszystkie (${panel.options.length})`}
            </Button>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              loading={pair.isPending}
              disabled={!pickedAd || unpair.isPending}
              onClick={() => pickedAd && pair.mutate(pickedAd.strefa_id)}
              data-testid="pracuj-ad-pair"
            >
              {pickedAd?.logged_applications
                ? `Połącz i dodaj ${pickedAd.logged_applications} ${plural(pickedAd.logged_applications, "osobę", "osoby", "osób")} do „Nowi”`
                : "Połącz"}
            </Button>
            <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
              Anuluj
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Osoby przechodzą te same bramki co przy dodaniu ręcznym (czarna lista, konflikty
            klienta, już w procesie). Tytuł tylko podpowiada — sprawdź numer ogłoszenia w strefie.
          </p>
        </fieldset>
      ) : null}
      {confirmDialog}
    </div>
  );
}
