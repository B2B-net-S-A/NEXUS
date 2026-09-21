"use client";

/**
 * Wynik zbiorczego „Wyślij CV do klienta" — JEDNO okno po całej pętli.
 *
 * Link do CV niesie sekret zwracany przez serwer RAZ (w bazie zostaje skrót),
 * a to okno jest jedynym miejscem, w którym adresy istnieją: nic nie jest
 * zapisywane po stronie przeglądarki. Stąd trzy reguły:
 * - adres jest zawsze WIDOCZNY (`OneTimeLinkField`), a „skopiowano" pada
 *   wyłącznie po udanym zapisie do schowka (`lib/clipboard.ts`);
 * - zamknięcie okna z nieskopiowanym linkiem pyta o potwierdzenie W OKNIE
 *   (natywny `window.confirm` zamraża automatyzację przeglądarki);
 * - link, który padł PO udanym ruchu, da się ponowić tylko stąd — okno
 *   pamięta etap sprzed ruchu, a profil i dok celują już w „CV Wysłane".
 */

import { useMemo, useState } from "react";
import { AlertTriangle, Copy, Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
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
import { OneTimeLinkField } from "@/components/v2/jobs/OneTimeLinkField";
import { apiErrorMessage } from "@/lib/api-error";
import type { BulkCvHandoffOutcome } from "@/lib/bulk-cv-handoff";
import { copyTextToClipboard } from "@/lib/clipboard";

export type BulkCvHandoffRetryTarget = Extract<
  BulkCvHandoffOutcome,
  { kind: "moved_no_link" }
>;

export interface BulkCvHandoffDialogProps {
  open: boolean;
  outcomes: BulkCvHandoffOutcome[];
  /** Ponawia SAM link (etap sprzed ruchu); zwraca `share_url_suffix` albo rzuca. */
  onRetryLink: (target: BulkCvHandoffRetryTarget) => Promise<string>;
  onClose: () => void;
  /** Początek adresu linku — domyślnie `window.location.origin`. */
  origin?: string;
}

function daysLabel(days: number): string {
  return days === 1 ? "1 dzień" : `${days} dni`;
}

function peopleLabel(count: number): string {
  if (count === 1) return "1 osoba";
  const lastTwo = count % 100;
  const last = count % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} osoby`;
  return `${count} osób`;
}

function failureText(outcome: BulkCvHandoffOutcome): string {
  switch (outcome.kind) {
    case "skipped":
      return `Pominięto — ${outcome.reason}. Osoba nie została przeniesiona.`;
    case "cancelled":
      return `Nie przeniesiono — ${outcome.reason}.`;
    case "move_refused":
      return `Nie przeniesiono: ${outcome.reason} Link nie powstał.`;
    case "move_unknown":
      return `${outcome.reason}. Link nie powstał.`;
    case "moved_no_link":
      return `Przeniesiono na „CV Wysłane”, ale link nie powstał: ${outcome.reason}`;
    case "linked":
      return "";
  }
}

export function BulkCvHandoffDialog({
  open,
  outcomes,
  onRetryLink,
  onClose,
  origin,
}: BulkCvHandoffDialogProps) {
  const { showSuccess, showError } = useToast();
  // Linki utworzone ponowieniem — po `candidateId`.
  const [retried, setRetried] = useState<Record<number, string>>({});
  const [retrying, setRetrying] = useState<Set<number>>(new Set());
  const [retryErrors, setRetryErrors] = useState<Record<number, string>>({});
  const [copied, setCopied] = useState<Set<number>>(new Set());
  const [confirmClose, setConfirmClose] = useState(false);

  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);

  const { links, failures } = useMemo(() => {
    const linkRows: {
      candidateId: number;
      fullName: string;
      url: string;
      expiresInDays: number;
      rateFailed: string | null;
    }[] = [];
    const failureRows: BulkCvHandoffOutcome[] = [];
    for (const outcome of outcomes) {
      const suffix =
        outcome.kind === "linked"
          ? outcome.suffix
          : outcome.kind === "moved_no_link"
            ? (retried[outcome.candidateId] ?? null)
            : null;
      if (suffix && (outcome.kind === "linked" || outcome.kind === "moved_no_link")) {
        linkRows.push({
          candidateId: outcome.candidateId,
          fullName: outcome.fullName,
          url: `${base}${suffix}`,
          expiresInDays: outcome.expiresInDays,
          rateFailed: outcome.rateFailed,
        });
      } else {
        failureRows.push(outcome);
      }
    }
    return { links: linkRows, failures: failureRows };
  }, [outcomes, retried, base]);

  const uncopied = links.filter((row) => !copied.has(row.candidateId)).length;
  const withoutLink = failures.filter((o) => o.kind === "moved_no_link").length;
  const needsConfirm = uncopied > 0 || withoutLink > 0 || retrying.size > 0;

  const markCopied = (candidateIds: number[]) =>
    setCopied((prev) => {
      const next = new Set(prev);
      for (const id of candidateIds) next.add(id);
      return next;
    });

  const copyAll = async () => {
    const text = links.map((row) => `${row.fullName} — ${row.url}`).join("\n");
    if (await copyTextToClipboard(text)) {
      markCopied(links.map((row) => row.candidateId));
      showSuccess(
        links.length === 1 ? "Link skopiowany." : `Skopiowano linki: ${links.length}.`,
      );
    } else {
      showError(
        "Nie udało się skopiować linków — zaznacz adresy w polach i skopiuj je ręcznie.",
      );
    }
  };

  const retry = async (target: BulkCvHandoffRetryTarget) => {
    const id = target.candidateId;
    setRetrying((prev) => new Set(prev).add(id));
    setRetryErrors((prev) => {
      const { [id]: _dropped, ...rest } = prev;
      return rest;
    });
    try {
      const suffix = await onRetryLink(target);
      setRetried((prev) => ({ ...prev, [id]: suffix }));
    } catch (e) {
      setRetryErrors((prev) => ({
        ...prev,
        [id]: apiErrorMessage(e, "Nie udało się utworzyć linku dla klienta."),
      }));
    } finally {
      setRetrying((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const requestClose = () => {
    if (needsConfirm) setConfirmClose(true);
    else onClose();
  };

  const moved = outcomes.filter(
    (o) => o.kind === "linked" || o.kind === "moved_no_link",
  ).length;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) requestClose();
      }}
    >
      <DialogContent size="lg" hideClose>
        <DialogHeader>
          <DialogTitle>Wyślij CV do klienta — wynik</DialogTitle>
          <DialogDescription>
            Przeniesiono na „CV Wysłane”: {moved} z {outcomes.length}. Linki: {links.length}.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-4">
          {links.length > 0 ? (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-warning/25 bg-warning-muted px-3 py-2.5 text-xs text-warning-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <p>
                <strong className="font-semibold">Skopiuj linki teraz.</strong> Każdy adres
                to jednorazowy sekret — nigdzie go nie zapisujemy i po zamknięciu tego
                okna nie da się go odtworzyć.
              </p>
            </div>
          ) : null}

          {links.length > 0 ? (
            <section aria-label="Utworzone linki" className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground">
                  Linki dla klienta ({links.length})
                </h3>
                <Button size="sm" variant="outline" onClick={() => void copyAll()}>
                  <Copy className="size-3.5" aria-hidden /> Kopiuj wszystkie
                </Button>
              </div>
              <ul className="space-y-3">
                {links.map((row) => (
                  <li key={row.candidateId} data-testid={`bulk-cv-link-${row.candidateId}`}>
                    <OneTimeLinkField
                      label={row.fullName}
                      url={row.url}
                      note={
                        copied.has(row.candidateId)
                          ? `Skopiowany · ważny ${daysLabel(row.expiresInDays)}`
                          : `Ważny ${daysLabel(row.expiresInDays)}`
                      }
                      onCopied={() => markCopied([row.candidateId])}
                    />
                    {row.rateFailed ? (
                      <p className="mt-1 text-[11px] text-destructive-muted-foreground">
                        Stawki do klienta nie udało się zapisać ({row.rateFailed}) — uzupełnij
                        ją z profilu kandydata.
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {failures.length > 0 ? (
            <section aria-label="Osoby bez linku" className="space-y-2">
              <h3 className="text-sm font-semibold text-foreground">
                Bez linku ({failures.length})
              </h3>
              <ul className="divide-y divide-border rounded-lg border border-border">
                {failures.map((outcome) => {
                  const busy = retrying.has(outcome.candidateId);
                  const retryError = retryErrors[outcome.candidateId];
                  return (
                    <li
                      key={outcome.candidateId}
                      data-testid={`bulk-cv-failure-${outcome.candidateId}`}
                      className="flex flex-wrap items-start justify-between gap-2 px-3 py-2"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-foreground">
                          {outcome.fullName}
                        </p>
                        <p className="text-xs text-muted-foreground">{failureText(outcome)}</p>
                        {outcome.kind === "moved_no_link" && outcome.rateFailed ? (
                          <p className="text-xs text-destructive-muted-foreground">
                            Stawki do klienta nie udało się zapisać ({outcome.rateFailed}) —
                            uzupełnij ją z profilu kandydata.
                          </p>
                        ) : null}
                        {retryError ? (
                          <p role="alert" className="text-xs text-destructive-muted-foreground">
                            Ponowienie nie powiodło się: {retryError}
                          </p>
                        ) : null}
                      </div>
                      {outcome.kind === "moved_no_link" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => void retry(outcome)}
                        >
                          {busy ? (
                            <Loader2 className="size-3.5 animate-spin" aria-hidden />
                          ) : null}
                          {busy ? "Tworzę link…" : "Utwórz link ponownie"}
                        </Button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          {outcomes.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nie wybrano żadnej osoby.</p>
          ) : null}
        </DialogBody>

        {confirmClose ? (
          <div
            role="alertdialog"
            aria-label="Potwierdź zamknięcie"
            className="mx-6 mb-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2.5"
          >
            <p className="text-sm font-medium text-foreground">Zamknąć okno?</p>
            <p className="mt-0.5 text-xs text-destructive-muted-foreground">
              {uncopied > 0
                ? `Nieskopiowane linki: ${peopleLabel(uncopied)}. Po zamknięciu ich adresów nie da się odtworzyć. `
                : ""}
              {withoutLink > 0
                ? `Bez linku mimo przeniesienia: ${peopleLabel(withoutLink)} — „Utwórz link ponownie” jest dostępne tylko w tym oknie.`
                : ""}
            </p>
            <div className="mt-2 flex flex-wrap justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setConfirmClose(false)}>
                Wróć do linków
              </Button>
              <Button size="sm" variant="destructive" onClick={onClose}>
                Zamknij mimo to
              </Button>
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant={needsConfirm ? "ghost" : "primary"} onClick={requestClose}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
