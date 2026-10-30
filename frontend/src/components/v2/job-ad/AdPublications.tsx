"use client";

/**
 * Gdzie ogłoszenie wisi (13.10.2026): rekruter wkleja treść na portalu ręcznie,
 * a tu oznacza „opublikowane” (z linkiem), „zaktualizowane” po poprawce
 * i „zdjęte z portalu”. Ten sam stan czyta okno „Ogłoszenie”,
 * sekcja „Zespół i ogłoszenie” i kolumna „Ogłoszenia” listy rekrutacji.
 *
 * NEXUS niczego na portalu nie zmienia — to wyłącznie zapis tego, co zrobił
 * człowiek. Reguły: `docs/claude/rekrutacja-tworzenie/ogloszenie-na-portale-kopiuj-wklej.md`.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  AD_PORTALS,
  jobAdApi,
  jobAdQueryKey,
  portalAdHref,
  type AdPortal,
  type AdPublication,
  type JobAdState,
  type PracujRequest,
} from "@/lib/api/jobAd";
import { copyHtmlToClipboard } from "@/lib/clipboard";
import { cn, formatDate } from "@/lib/utils";

export type AdPublicationsApi = Pick<typeof jobAdApi, "markPublished" | "markRemoved">;

/** Pierwszy człon klucza listy rekrutacji (`jobsListQueryKey`) — kolumna „Ogłoszenia”. */
export const JOBS_LIST_QUERY_ROOT = "jobs-v2";

export interface AdPublicationsProps {
  /** Wejście z maila przypomnienia: pole linku tego portalu od razu otwarte. */
  initialLinkFor?: AdPortal | null;
  /** Linia pod portalem: kto robi brak albo „nie publikujemy” (27.10.2026). */
  renderExtra?: (portal: AdPortal) => React.ReactNode;
  /**
   * „Wyślij do Pracuj.pl” — mail do opiekuna konta (27.10.2026). Brak = osoba
   * nie wysyła (rekruter) i widzi tylko stan.
   */
  onSendPracuj?: () => void;
  jobId: number;
  /** Portale do pokazania: jeden w zakładce okna, oba w sekcji rekrutacji. */
  portals: readonly AdPortal[];
  state: JobAdState;
  /** Zamknięta rekrutacja z wiszącym ogłoszeniem = przypomnienie o zdjęciu. */
  jobClosed?: boolean;
  /** Trwa zapis albo przygotowanie treści w oknie. */
  locked?: boolean;
  api?: AdPublicationsApi;
}

function lastPublication(
  publications: readonly AdPublication[],
  portal: AdPortal,
): AdPublication | null {
  return publications.find((item) => item.portal === portal) ?? null;
}

export function AdPublications({
  jobId,
  portals,
  state,
  jobClosed = false,
  locked = false,
  api = jobAdApi,
  initialLinkFor = null,
  renderExtra,
  onSendPracuj,
}: AdPublicationsProps) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  // Portal z otwartym polem linku i jego niezapisana wartość.
  const [linkFor, setLinkFor] = useState<AdPortal | null>(initialLinkFor);
  const [link, setLink] = useState("");
  // „Skopiowane” przy opisie JustJoin.IT — dla tej wersji treści.
  const [jjitCopiedAt, setJjitCopiedAt] = useState<string | null>(null);

  const apply = (next: JobAdState) => {
    queryClient.setQueryData(jobAdQueryKey(jobId), next);
    void queryClient.invalidateQueries({ queryKey: [JOBS_LIST_QUERY_ROOT] });
  };

  const mark = useMutation({
    mutationFn: (input: { portal: AdPortal; url: string | null; contentUpdated?: boolean }) =>
      api.markPublished(jobId, input.portal, input.url, input.contentUpdated ?? false),
    onSuccess: (next) => {
      apply(next);
      setLinkFor(null);
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się oznaczyć publikacji. Spróbuj ponownie.")),
  });

  const remove = useMutation({
    mutationFn: (portal: AdPortal) => api.markRemoved(jobId, portal),
    onSuccess: apply,
    onError: (err) =>
      showError(
        apiErrorMessage(err, "Nie udało się zapisać zdjęcia ogłoszenia. Spróbuj ponownie."),
      ),
  });

  const busy = locked || mark.isPending || remove.isPending;
  const blockedReason = !state.ad
    ? "Najpierw przygotuj ogłoszenie."
    : !state.can_copy
      ? "Najpierw usuń z treści fragmenty wskazane w kontroli."
      : null;

  const jjitBody = state.rendered?.jjit ?? null;
  const jjitCopied = !!state.ad && jjitCopiedAt === state.ad.updated_at;
  const copyJjit = async () => {
    if (!jjitBody) return;
    if (await copyHtmlToClipboard(jjitBody.body_html, jjitBody.body_text)) {
      setJjitCopiedAt(state.ad?.updated_at ?? null);
    } else {
      showError("Nie udało się skopiować. Otwórz zakładkę JustJoin.IT i skopiuj opis ręcznie.");
    }
  };

  const confirmRemoved = async (portal: AdPortal, label: string) => {
    const confirmed = await askConfirm({
      title: `Ogłoszenie zdjęte z ${label}?`,
      description:
        "Zapisuję tylko stan w NEXUSIE. Samo ogłoszenie zdejmujesz w panelu portalu — jeśli jeszcze tam wisi, zrób to najpierw.",
      confirmLabel: "Zdjęte z portalu",
    });
    if (confirmed) remove.mutate(portal);
  };

  return (
    <>
      <ul className="flex flex-col gap-2" data-testid="job-ad-publications">
        {AD_PORTALS.filter((item) => portals.includes(item.key)).map(({ key, label }) => {
          const last = lastPublication(state.publications, key);
          const active = last && !last.removed_at ? last : null;
          const href = active ? portalAdHref(key, active.url) : null;
          const editingLink = linkFor === key;
          // Mail do opiekuna wyszedł, a ogłoszenia jeszcze nie oznaczono.
          const request: PracujRequest | null =
            key === "pracuj" && !active ? state.pracuj_request : null;
          return (
            <li
              key={key}
              aria-label={`Publikacja: ${label}`}
              className={cn(
                "flex flex-col gap-2 rounded-md border bg-card px-3 py-2 text-[13px]",
                initialLinkFor === key ? "border-primary ring-2 ring-primary/30" : "border-border",
              )}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-medium text-foreground">{label}</span>
                {active ? (
                  <span className="text-foreground">
                    Opublikowane {formatDate(active.published_at)}
                    {active.published_by_name ? ` · ${active.published_by_name}` : ""}
                  </span>
                ) : request ? (
                  <span className="text-foreground" data-testid="pracuj-request-status">
                    Wysłane do opiekuna {formatDate(request.sent_at)}
                    {request.sent_by_name ? ` · ${request.sent_by_name}` : ""}
                    {request.waiting ? " · czeka na publikację" : ""}
                  </span>
                ) : (
                  <span className="text-muted-foreground">
                    {last?.removed_at
                      ? `Zdjęte z portalu ${formatDate(last.removed_at)}`
                      : "Nieoznaczone jako opublikowane"}
                  </span>
                )}
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
                  >
                    Otwórz ogłoszenie
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                ) : active ? (
                  <span className="text-muted-foreground">bez linku</span>
                ) : null}
                {active?.outdated ? (
                  <span className="rounded-full bg-warning-muted px-2 py-0.5 text-[11px] font-medium text-warning-muted-foreground">
                    do aktualizacji
                  </span>
                ) : null}
                <div className="ml-auto flex flex-wrap items-center gap-1">
                  {active ? (
                    <>
                      {active.outdated ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 px-2.5"
                          title={blockedReason ?? undefined}
                          disabled={busy || !!blockedReason}
                          onClick={() =>
                            mark.mutate({ portal: key, url: active.url, contentUpdated: true })
                          }
                        >
                          Zaktualizowane na portalu
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        // Sam link niczego nie potwierdza — wolno go zmienić zawsze.
                        disabled={busy || editingLink}
                        onClick={() => {
                          setLink(active.url ?? "");
                          setLinkFor(key);
                        }}
                      >
                        {active.url ? "Zmień link" : "Dodaj link"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        disabled={busy}
                        onClick={() => void confirmRemoved(key, label)}
                      >
                        Zdjęte z portalu
                      </Button>
                    </>
                  ) : (
                    <>
                      {key === "pracuj" && onSendPracuj && !jobClosed ? (
                        <Button
                          type="button"
                          size="sm"
                          variant={request ? "ghost" : "primary"}
                          className="h-7 px-2.5"
                          title={blockedReason ?? undefined}
                          disabled={busy || !!blockedReason}
                          onClick={onSendPracuj}
                          data-testid="pracuj-send"
                          data-tour="job-ad.pracuj.send"
                        >
                          {request ? "Wyślij ponownie" : "Wyślij do Pracuj.pl"}
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2.5"
                        title={blockedReason ?? undefined}
                        disabled={busy || !!blockedReason || editingLink}
                        onClick={() => {
                          setLink("");
                          setLinkFor(key);
                        }}
                      >
                        {request ? "Wisi — dodaj link" : "Oznacz jako opublikowane"}
                      </Button>
                    </>
                  )}
                </div>
              </div>

              {active?.outdated ? (
                <p className="text-xs text-warning-muted-foreground">
                  Treść zmieniła się po publikacji. Popraw ogłoszenie na portalu i kliknij
                  „Zaktualizowane na portalu”.
                </p>
              ) : null}
              {request ? (
                <p className="text-xs text-muted-foreground">
                  {request.waiting
                    ? "Opiekun zwykle wstawia ogłoszenie w 1–2 dni robocze. Gdy przyśle link, wklej go tutaj — do tego czasu codzienny mail nie przypomina o Pracuj.pl."
                    : "Ogłoszenie wciąż nie jest oznaczone. Sprawdź odpowiedź opiekuna i wklej link albo wyślij ponownie."}
                </p>
              ) : null}
              {active && jobClosed ? (
                <p className="text-xs text-warning-muted-foreground">
                  Rekrutacja jest zamknięta, a ogłoszenie nadal wisi. Zdejmij je na portalu i oznacz
                  to tutaj.
                </p>
              ) : null}

              {key === "jjit" && !active && !jobClosed ? (
                // Publikacji przez API JustJoin.IT jeszcze nie ma (brak klucza na
                // produkcji) — rekruterka szukała przycisku „dodaj” (28.10.2026).
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span>
                    Ogłoszenie wstawiasz w panelu pracodawcy JustJoin.IT: skopiuj opis, wklej go
                    w nowym ogłoszeniu, a potem oznacz je tutaj z linkiem.
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className={cn(
                      "h-7 px-2.5",
                      jjitCopied && "border-success/30 bg-success-muted text-success-muted-foreground",
                    )}
                    aria-label={jjitCopied ? "Skopiowane" : "Kopiuj opis JustJoin.IT"}
                    title={blockedReason ?? undefined}
                    disabled={busy || !!blockedReason || !jjitBody}
                    onClick={() => void copyJjit()}
                  >
                    {jjitCopied ? (
                      <Check className="h-3.5 w-3.5" aria-hidden="true" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    {jjitCopied ? "Skopiowane" : "Kopiuj opis"}
                  </Button>
                </div>
              ) : null}
              {editingLink ? (
                <form
                  className="flex flex-wrap items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    mark.mutate({ portal: key, url: link.trim() || null });
                  }}
                >
                  <label className="flex min-w-[240px] flex-1 flex-col gap-1">
                    <span className="text-xs text-muted-foreground">
                      {/* RocketJobs połączył się z JustJoin.IT — serwer przyjmuje oba adresy. */}
                      Link do ogłoszenia na {label}
                      {key === "jjit" ? " albo RocketJobs" : ""} (możesz dodać później)
                    </span>
                    {/* Zwykłe pole: adres sprawdza serwer i odpowiada po polsku. */}
                    <Input
                      inputMode="url"
                      value={link}
                      maxLength={500}
                      placeholder="https://"
                      className="h-8 text-[13px]"
                      onChange={(event) => setLink(event.target.value)}
                      autoFocus
                    />
                  </label>
                  <Button type="submit" size="sm" loading={mark.isPending} disabled={locked}>
                    {active ? "Zapisz link" : "Oznacz"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={mark.isPending}
                    onClick={() => setLinkFor(null)}
                  >
                    Anuluj
                  </Button>
                </form>
              ) : null}
              {!active ? renderExtra?.(key) : null}
            </li>
          );
        })}
      </ul>
      {confirmDialog}
    </>
  );
}
