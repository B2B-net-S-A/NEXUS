"use client";

/**
 * Mail z ogłoszeniem do opiekuna Pracuj.pl (27.10.2026).
 *
 * Pracuj.pl nie ma u nas API — ogłoszenie wstawia opiekun konta po mailu.
 * Okno pokazuje mail złożony przez serwer z treści zakładki Pracuj.pl (po
 * kontroli); osoba dopisuje tylko stawkę dla kandydata. Mail wychodzi z jej
 * skrzynki M365; bez podłączonej skrzynki okno prosi o podłączenie i daje
 * „Kopiuj treść maila”. Reguły:
 * `docs/claude/rekrutacja-tworzenie/ogloszenie-pracuj-mailem-do-opiekuna.md`,
 * makiety https://claude.ai/artifact/6cgqm3LhTM7t8MzMXazmEe.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Mail } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jobAdApi,
  jobAdQueryKey,
  pracujMailPreviewQueryKey,
  type JobAdState,
  type PracujMailRates,
} from "@/lib/api/jobAd";
import { newClientRequestId } from "@/lib/client-request-id";
import { useDebouncedValue } from "@/lib/use-debounced-value";

export type PracujMailApi = Pick<typeof jobAdApi, "previewPracujMail" | "sendPracujMail">;

export interface PracujMailDialogProps {
  open: boolean;
  jobId: number;
  state: JobAdState;
  onClose: () => void;
  /** Mail wyszedł — nowy stan ogłoszenia z serwera. */
  onSent: (next: JobAdState) => void;
  api?: PracujMailApi;
}

const RATE_DIGITS = 4;

/** „120” → 120; pusto albo coś innego → `null`. */
export function parseRate(value: string): number | null {
  const digits = value.replace(/\D/g, "").slice(0, RATE_DIGITS);
  return digits ? Number(digits) : null;
}

function errorStatus(err: unknown): number | undefined {
  return (err as { response?: { status?: number } } | null)?.response?.status;
}

export function PracujMailDialog({
  open,
  jobId,
  state,
  onClose,
  onSent,
  api = jobAdApi,
}: PracujMailDialogProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [rateFrom, setRateFrom] = useState("");
  const [rateTo, setRateTo] = useState("");
  const [copied, setCopied] = useState(false);
  const bodyRef = useRef<HTMLElement | null>(null);
  // Jeden klucz na otwarcie okna: ponowienie po błędzie sieci nie wyśle
  // drugiego maila (`m365/sender`, klucz żądania).
  const requestId = useRef(newClientRequestId());

  useEffect(() => {
    if (!open) return;
    requestId.current = newClientRequestId();
    setCopied(false);
  }, [open]);

  const typed: PracujMailRates = { rate_from: parseRate(rateFrom), rate_to: parseRate(rateTo) };
  // Debounce na napisach, nie na obiekcie: nowy obiekt co render restartowałby licznik.
  const debouncedFrom = useDebouncedValue(rateFrom, 300);
  const debouncedTo = useDebouncedValue(rateTo, 300);
  const rates: PracujMailRates = {
    rate_from: parseRate(debouncedFrom),
    rate_to: parseRate(debouncedTo),
  };
  const settled = debouncedFrom === rateFrom && debouncedTo === rateTo;

  // Wersja ogłoszenia w kluczu: treść zmieniona w tle (powrót do karty)
  // odświeża podgląd, a do tego czasu wysyłka i kopiowanie czekają.
  const version = state.ad?.updated_at ?? null;
  const preview = useQuery({
    queryKey: [...pracujMailPreviewQueryKey(jobId, rates), version],
    queryFn: () => api.previewPracujMail(jobId, rates),
    enabled: open,
    placeholderData: keepPreviousData,
    retry: false,
  });

  const send = useMutation({
    mutationFn: () =>
      api.sendPracujMail(jobId, {
        ...typed,
        expected_updated_at: version,
        client_request_id: requestId.current,
      }),
    onSuccess: (next) => {
      onSent(next);
      showSuccess(
        `Wysłane do ${preview.data?.to_email ?? "opiekuna Pracuj.pl"}. Gdy opiekun przyśle link, oznacz ogłoszenie jako opublikowane.`,
      );
    },
    onError: (err) => {
      const status = errorStatus(err);
      if (status === 412) void preview.refetch();
      if (status === 409) void queryClient.invalidateQueries({ queryKey: jobAdQueryKey(jobId) });
      showError(apiErrorMessage(err, "Nie udało się wysłać maila. Spróbuj ponownie."));
    },
  });

  const data = preview.data;
  const mailboxReady = data?.mailbox === "ready";
  // Ta sama bramka dla wysyłki i kopiowania: do schowka nie idzie treść
  // z blokadą kontroli, bez stawki ani z poprzednią stawką.
  const sendBlockedReason = !state.can_copy
    ? "Najpierw usuń z treści fragmenty wskazane w kontroli."
    : !data
      ? "Czekam na podgląd maila."
      : data.rate_error
        ? data.rate_error
        : !settled || preview.isFetching
          ? "Odświeżam podgląd maila."
          : null;

  const copy = async () => {
    if (!data || sendBlockedReason) return;
    const text = `${data.subject}\n\n${data.body_text}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // Schowek zablokowany — zaznacz tekst, Ctrl+C zrobi resztę.
      const node = bodyRef.current;
      const selection = window.getSelection();
      if (node && selection) {
        const range = document.createRange();
        range.selectNodeContents(node);
        selection.removeAllRanges();
        selection.addRange(range);
      }
      showError("Przeglądarka nie dała skopiować — treść jest zaznaczona, naciśnij Ctrl+C.");
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => (value ? undefined : onClose())}>
      <DialogContent size="2xl" aria-describedby="pracuj-mail-description">
        <DialogHeader>
          <DialogTitle>
            {state.pracuj_request ? "Wyślij ponownie do Pracuj.pl" : "Wyślij ogłoszenie do Pracuj.pl"}
          </DialogTitle>
          <DialogDescription id="pracuj-mail-description">
            Pracuj.pl nie ma u nas połączenia — ogłoszenie wstawia opiekun konta. Mail wychodzi
            z Twojej skrzynki, a jego treść to zakładka Pracuj.pl.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="grid grid-cols-1 gap-4 min-[1100px]:grid-cols-[300px_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-3 text-[13px]">
            {data && !mailboxReady ? (
              <Alert
                variant="warning"
                title={
                  data.mailbox === "reconnect"
                    ? "Połącz ponownie skrzynkę Microsoft 365"
                    : "Twoja skrzynka Microsoft 365 nie jest podłączona"
                }
                description={
                  <span>
                    Mail do opiekuna wychodzi z Twojej skrzynki, żeby odpowiedź wróciła do
                    Ciebie.{" "}
                    <Link href="/settings?area=me&item=outlook" className="underline">
                      Podłącz w Ustawieniach
                    </Link>{" "}
                    albo skopiuj treść i wyślij z Outlooka.
                  </span>
                }
              />
            ) : null}
            {data ? (
              <dl className="grid grid-cols-[52px_minmax(0,1fr)] gap-x-2 gap-y-1.5">
                <dt className="text-muted-foreground">Od</dt>
                <dd className="truncate text-foreground">
                  {data.from_address ?? "Twoja skrzynka (niepodłączona)"}
                </dd>
                <dt className="text-muted-foreground">Do</dt>
                <dd className="break-words text-foreground">
                  {data.to_name ? `${data.to_name} · ` : ""}
                  {data.to_email}
                </dd>
                <dt className="text-muted-foreground">Temat</dt>
                <dd className="break-words text-foreground">{data.subject}</dd>
              </dl>
            ) : null}
            <fieldset className="flex flex-col gap-1.5 rounded-md border border-border px-3 py-2.5">
              <legend className="px-1 text-xs font-medium text-foreground">
                Stawka dla kandydata (B2B, zł/h netto)
              </legend>
              <div className="flex items-center gap-2">
                <Input
                  id="pracuj-rate-from"
                  inputMode="numeric"
                  aria-label="Stawka od"
                  placeholder="od"
                  className="h-8 w-24 text-[13px]"
                  value={rateFrom}
                  onChange={(e) => setRateFrom(e.target.value.replace(/\D/g, "").slice(0, RATE_DIGITS))}
                />
                <span className="text-muted-foreground">–</span>
                <Input
                  id="pracuj-rate-to"
                  inputMode="numeric"
                  aria-label="Stawka do"
                  placeholder="do"
                  className="h-8 w-24 text-[13px]"
                  value={rateTo}
                  onChange={(e) => setRateTo(e.target.value.replace(/\D/g, "").slice(0, RATE_DIGITS))}
                />
              </div>
              {data?.rate_error && (rateFrom || rateTo) ? (
                <p role="alert" className="text-xs text-destructive">
                  {data.rate_error}
                </p>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Tylko w mailu do opiekuna — opiekun wpisuje ją w pole widełek. W treści ogłoszenia
                kwot nie ma.
              </p>
            </fieldset>
            <p className="text-xs text-muted-foreground">
              Treść poprawiasz w zakładce Pracuj.pl — mail bierze ją z zapisanego ogłoszenia, po
              kontroli. Opiekuna i adres zmienia Head of Recruitment w Ustawieniach → Rekrutacja →
              Stałe części ogłoszenia.
            </p>
          </div>
          {preview.isError ? (
            <Alert
              variant="error"
              title="Nie udało się złożyć maila"
              description={apiErrorMessage(preview.error, "Zamknij okno i spróbuj ponownie.")}
            />
          ) : (
            <section
              ref={bodyRef}
              aria-label="Podgląd maila"
              aria-busy={preview.isFetching}
              data-testid="pracuj-mail-body"
              className="max-h-[52dvh] min-w-0 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-muted/40 px-3 py-2.5 text-[13px] leading-relaxed text-foreground"
            >
              {data ? data.body_text : "Składam mail…"}
              {data ? (
                <span className="mt-3 block text-xs text-muted-foreground">
                  + Twoja stopka z Outlooka
                </span>
              ) : null}
            </section>
          )}
        </DialogBody>
        <DialogFooter className="flex-wrap gap-2">
          <Button
            type="button"
            variant="ghost"
            disabled={!!sendBlockedReason}
            title={sendBlockedReason ?? undefined}
            onClick={() => void copy()}
          >
            <Copy className="size-4" aria-hidden="true" />
            {copied ? "Skopiowano" : "Kopiuj treść maila"}
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          {mailboxReady ? (
            <Button
              type="button"
              variant="primary"
              loading={send.isPending}
              disabled={!!sendBlockedReason}
              title={sendBlockedReason ?? undefined}
              onClick={() => send.mutate()}
            >
              <Mail className="size-4" aria-hidden="true" />
              Wyślij z mojej skrzynki
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
