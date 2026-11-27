"use client";

/**
 * Panel znaleziska z boku (makieta 2 raportu „Tarcza NEXUSA”, 27.11.2026):
 * skąd, dowód, wpływ, właściciel, kroki i trzy akcje. „Wyjątek do…” wymaga
 * powodu i daty (najwyżej rok); po terminie znalezisko samo wraca na listę.
 * „Otwórz sesję naprawy” kopiuje kompletny brief do nowej sesji Claude Code.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";

import {
  exceptionBounds,
  exceptionError,
  repairBrief,
  SECURITY_OVERVIEW_KEY,
  SEVERITY_LABEL,
  SEVERITY_TONE,
  sourceLabel,
  type SecurityFinding,
  type SecurityOwner,
} from "./security-model";
import { TONE_BADGE } from "./tone";

export interface SecurityFindingSheetProps {
  finding: SecurityFinding | null;
  owners: readonly SecurityOwner[];
  today: string;
  onClose: () => void;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-foreground">{children}</dd>
    </>
  );
}

export function SecurityFindingSheet({ finding, owners, today, onClose }: SecurityFindingSheetProps) {
  return (
    <Sheet open={finding !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" size="md" aria-describedby={undefined}>
        {finding ? (
          <FindingBody key={finding.id} finding={finding} owners={owners} today={today} onClose={onClose} />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function FindingBody({
  finding,
  owners,
  today,
  onClose,
}: {
  finding: SecurityFinding;
  owners: readonly SecurityOwner[];
  today: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [exceptionOpen, setExceptionOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [touched, setTouched] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const bounds = exceptionBounds(today);
  const validation = exceptionError(reason, until, today);

  const refresh = () => queryClient.invalidateQueries({ queryKey: SECURITY_OVERVIEW_KEY });

  const owner = useMutation({
    mutationFn: async (ownerId: number | null) =>
      (await api.patch<SecurityFinding>(`/api/security/findings/${finding.id}`, { owner_user_id: ownerId })).data,
    onSuccess: () => {
      setActionError(null);
      void refresh();
    },
    onError: (error: unknown) => setActionError(apiErrorMessage(error, "Nie udało się zmienić właściciela.")),
  });

  const except = useMutation({
    mutationFn: async () =>
      (await api.post<SecurityFinding>(`/api/security/findings/${finding.id}/exception`, { reason: reason.trim(), until })).data,
    onSuccess: () => {
      showSuccess(`Wyjątek do ${formatIsoDatePl(until)}. Po tym dniu znalezisko wróci na listę.`);
      void refresh();
      onClose();
    },
    onError: (error: unknown) => setActionError(apiErrorMessage(error, "Nie udało się zapisać wyjątku.")),
  });

  const close = useMutation({
    mutationFn: async () => (await api.post<SecurityFinding>(`/api/security/findings/${finding.id}/close`, {})).data,
    onSuccess: () => {
      showSuccess("Zamknięte jako naprawione.");
      void refresh();
      onClose();
    },
    onError: (error: unknown) => setActionError(apiErrorMessage(error, "Nie udało się zamknąć znaleziska.")),
  });

  const reopen = useMutation({
    mutationFn: async () => (await api.post<SecurityFinding>(`/api/security/findings/${finding.id}/reopen`, {})).data,
    onSuccess: () => {
      void refresh();
      onClose();
    },
    onError: (error: unknown) => setActionError(apiErrorMessage(error, "Nie udało się otworzyć znaleziska.")),
  });

  const copyBrief = async () => {
    try {
      await navigator.clipboard.writeText(repairBrief(finding));
      showSuccess("Brief skopiowany — wklej go w nowej sesji Claude Code.");
    } catch (error: unknown) {
      showError(apiErrorMessage(error, "Przeglądarka nie pozwoliła skopiować briefu."));
    }
  };

  const askClose = async () => {
    const ok = await askConfirm({
      title: "Zamknąć jako naprawione?",
      description:
        "Znalezisko zniknie z listy „Czeka na reakcję”. Jeśli skaner zgłosi je ponownie, wróci samo.",
      confirmLabel: "Zamknij jako naprawione",
    });
    if (ok) close.mutate();
  };

  const submitException = () => {
    setTouched(true);
    if (!validation) except.mutate();
  };

  const isOpen = finding.status === "open";
  const busy = except.isPending || close.isPending || reopen.isPending;

  return (
    <>
      <SheetHeader className="pr-12">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant={TONE_BADGE[SEVERITY_TONE[finding.severity]]}>{SEVERITY_LABEL[finding.severity]}</Badge>
          <span>
            od {formatIsoDatePl(finding.first_seen_at)} · źródło: {sourceLabel(finding.source)}
            {finding.scanner && finding.scanner !== finding.source ? ` (${finding.scanner})` : ""}
          </span>
        </div>
        <SheetTitle className="text-lg">{finding.title}</SheetTitle>
        <SheetDescription className="sr-only">Szczegóły znaleziska bezpieczeństwa</SheetDescription>
        {finding.exception_expired ? (
          <p className="text-xs text-destructive">
            Wyjątek minął {formatIsoDatePl(finding.exception_until)} — znalezisko wróciło na listę.
          </p>
        ) : null}
      </SheetHeader>
      <SheetBody className="space-y-4 text-sm">
        <dl className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5">
          <Fact label="Gdzie">{finding.location ? <code className="text-xs">{finding.location}</code> : "—"}</Fact>
          <Fact label="Dowód">{finding.evidence ?? "—"}</Fact>
          <Fact label="Wpływ">{finding.impact ?? "—"}</Fact>
          <Fact label="Właściciel">
            <select
              aria-label="Właściciel"
              value={finding.owner_user_id ?? ""}
              disabled={owner.isPending}
              onChange={(event) => owner.mutate(event.target.value ? Number(event.target.value) : null)}
              className="h-8 rounded-md border border-border bg-card px-2 text-sm text-foreground"
            >
              <option value="">— nikt —</option>
              {owners.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Fact>
          <Fact label="Ostatnio widziane">{formatMomentPl(finding.last_seen_at)}</Fact>
          {finding.status === "excepted" ? (
            <Fact label="Wyjątek">
              do {formatIsoDatePl(finding.exception_until)} — {finding.exception_reason}
            </Fact>
          ) : null}
          {finding.status === "fixed" ? (
            <Fact label="Zamknięte">
              {formatMomentPl(finding.closed_at)}
              {finding.closed_note ? ` — ${finding.closed_note}` : ""}
            </Fact>
          ) : null}
        </dl>

        {finding.steps.length ? (
          <div>
            <h3 className="mb-1 font-semibold text-foreground">Co zrobić</h3>
            <ol className="list-decimal space-y-1 pl-5">
              {finding.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </div>
        ) : null}

        {exceptionOpen ? (
          <form
            className="space-y-2 rounded-lg border border-border bg-muted/40 p-3"
            onSubmit={(event) => {
              event.preventDefault();
              submitException();
            }}
          >
            <h3 className="font-semibold text-foreground">Wyjątek do…</h3>
            <label className="block text-xs text-muted-foreground" htmlFor="security-exception-reason">
              Powód (obowiązkowy)
            </label>
            <Textarea
              id="security-exception-reason"
              value={reason}
              maxLength={1000}
              rows={3}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Np. poprawka w oknie upgrade'u serwera 05.12"
            />
            <label className="block text-xs text-muted-foreground" htmlFor="security-exception-until">
              Do kiedy (najwyżej rok)
            </label>
            <Input
              id="security-exception-until"
              type="date"
              value={until}
              min={bounds.min}
              max={bounds.max}
              onChange={(event) => setUntil(event.target.value)}
              className="w-44"
            />
            {touched && validation ? (
              <p role="alert" className="text-xs text-destructive">
                {validation}
              </p>
            ) : null}
            <div className="flex gap-2 pt-1">
              <Button type="submit" size="sm" loading={except.isPending}>
                Zapisz wyjątek
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setExceptionOpen(false)}>
                Anuluj
              </Button>
            </div>
          </form>
        ) : null}

        {actionError ? (
          <p role="alert" className="text-xs text-destructive">
            {actionError}
          </p>
        ) : null}
      </SheetBody>
      <SheetFooter className="sm:justify-start">
        <Button size="sm" onClick={() => void copyBrief()}>
          Otwórz sesję naprawy
        </Button>
        {finding.status !== "fixed" ? (
          <>
            {isOpen && !exceptionOpen ? (
              <Button size="sm" variant="outline" onClick={() => setExceptionOpen(true)} disabled={busy}>
                Wyjątek do…
              </Button>
            ) : null}
            <Button size="sm" variant="outline" onClick={() => void askClose()} disabled={busy}>
              Zamknij jako naprawione
            </Button>
          </>
        ) : (
          <Button size="sm" variant="outline" onClick={() => reopen.mutate()} disabled={busy}>
            Otwórz ponownie
          </Button>
        )}
      </SheetFooter>
      {confirmDialog}
    </>
  );
}
