"use client";

// Okno szczegółów zgodności umów B2B z umową ramową klienta (część G):
// tabela temat / wymaga klient / nasza umowa / stan / krok. Otwiera się
// z panelu w Generatorze, z zadania asystenta (`?zgodnosc=` w Generatorze
// aneksów) i z karty klienta (Umowy). Nie ma własnej pozycji menu.
//
// „Zaproponuj jako klauzulę klienta do nowych umów” zakłada SZKIC dla
// programisty albo administratora — wzór Generatora (`clause_overrides`)
// sam się nie zmienia.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, Loader2, RefreshCw } from "lucide-react";

import { useOptionalToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import { apiErrorMessage } from "@/lib/api-error";
import {
  legalClientFitApi,
  legalClientFitKeys,
  useClientFit,
  type ClientFitFinding,
  type ClientFitResponse,
} from "@/lib/api/legalClientFit";
import { formatDateTimePl } from "@/lib/date-pl";
import {
  CLIENT_FIT_STATE_LABEL,
  affectedLabel,
  clientFitTitle,
  hasResult,
  sortFindings,
} from "@/lib/legal-client-fit";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";

import { ClientFitStaleNote, ClientFitStatusNote } from "./ClientFitStatus";
import { LawyerBadge, QuoteText, RefChip, STATE_ICON, STATE_TONE, useRecheck } from "./parts";

export interface ClientFitDialogProps {
  clientId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ClientFitDialog({ clientId, open, onOpenChange }: ClientFitDialogProps) {
  const query = useClientFit(open ? clientId : null);
  const data = query.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="full" className="max-w-[1180px]">
        <DialogHeader>
          <DialogTitle className="text-lg">
            {data ? clientFitTitle(data.client_name) : "Zgodność umów B2B z umową ramową klienta"}
          </DialogTitle>
          <DialogDescription>
            {data
              ? [
                  data.sources.map((s) => s.name).join(" + ") || null,
                  data.template_label || null,
                  data.checked_at ? `sprawdzono ${formatDateTimePl(data.checked_at)}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : "Wymogi z umowy ramowej i aneksów klienta porównane z naszym wzorem umowy B2B."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {query.isError ? (
            <Alert
              variant="error"
              title={
                isForbiddenError(query.error)
                  ? "Treść umów tego klienta wymaga podglądu kwot u klienta"
                  : "Nie udało się wczytać sprawdzenia"
              }
              description={apiErrorMessage(query.error, "Spróbuj ponownie za chwilę.")}
            >
              {!isForbiddenError(query.error) ? (
                <Button size="sm" variant="outline" className="mt-2" onClick={() => void query.refetch()}>
                  Ponów
                </Button>
              ) : null}
            </Alert>
          ) : !query.isSuccess || !data ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Wczytuję ustalenia…
            </p>
          ) : !hasResult(data) ? (
            <ClientFitStatusNote data={data} />
          ) : (
            <>
              <ClientFitStaleNote data={data} />
              <SourcesNote data={data} />
              {data.findings.length ? (
                <FindingsTable data={data} />
              ) : (
                <p className="text-sm text-muted-foreground">
                  Sprawdzenie nie znalazło w umowie ramowej wymogów, które dałoby się porównać z naszym wzorem.
                </p>
              )}
            </>
          )}
        </DialogBody>
        <DialogFooter className="items-center">
          <p className="mr-auto text-[12px] text-muted-foreground">
            {data?.disclaimer || "Asystent nie jest poradą prawną."}
          </p>
          {data && hasResult(data) ? <RecheckButton clientId={clientId} /> : null}
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RecheckButton({ clientId }: { clientId: number }) {
  const recheck = useRecheck(clientId);
  return (
    <Button
      size="sm"
      variant="outline"
      loading={recheck.isPending}
      disabled={recheck.isPending}
      onClick={() => recheck.mutate()}
    >
      <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Sprawdź ponownie
    </Button>
  );
}

function SourcesNote({ data }: { data: ClientFitResponse }) {
  const unreadable = data.sources.filter((s) => !s.readable || s.note);
  const parts = [
    data.active_b2b_contracts > 0
      ? `Aktywne umowy B2B u klienta: ${data.active_b2b_contracts}.`
      : "Klient nie ma dziś aktywnych umów B2B.",
  ];
  return (
    <div className="space-y-1 text-[12.5px] text-muted-foreground">
      <p>{parts.join(" ")}</p>
      {unreadable.map((s) => (
        <p key={`${s.kind}-${s.id}`} className="text-warning-muted-foreground">
          {s.name}: {s.note ?? "treści nie da się odczytać — ten dokument nie wszedł do sprawdzenia."}
        </p>
      ))}
    </div>
  );
}

function FindingsTable({ data }: { data: ClientFitResponse }) {
  const rows = sortFindings(data.findings);
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[880px] border-collapse text-left text-[12.5px]">
        <thead className="bg-muted/50 text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
          <tr>
            <th scope="col" className="w-[15%] px-3 py-2 font-semibold">Temat</th>
            <th scope="col" className="w-[30%] px-3 py-2 font-semibold">Wymaga klient</th>
            <th scope="col" className="w-[27%] px-3 py-2 font-semibold">Nasza umowa</th>
            <th scope="col" className="w-[13%] px-3 py-2 font-semibold">Stan</th>
            <th scope="col" className="w-[15%] px-3 py-2 font-semibold">Krok</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70 align-top">
          {rows.map((finding) => (
            <FindingTableRow
              key={finding.id}
              finding={finding}
              clientId={data.client_id}
              canDraft={data.can_request_clause_draft}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FindingTableRow({
  finding,
  clientId,
  canDraft,
}: {
  finding: ClientFitFinding;
  clientId: number;
  canDraft: boolean;
}) {
  const Icon = STATE_ICON[finding.state];
  return (
    <tr data-state={finding.state}>
      <td className="px-3 py-2.5">
        <p className="font-medium text-foreground">{finding.topic_label}</p>
        {finding.summary ? <p className="mt-0.5 text-muted-foreground">{finding.summary}</p> : null}
      </td>
      <td className="space-y-1 px-3 py-2.5">
        <QuoteText text={finding.client_quote} className="text-foreground" />
        <RefChip kind="client" label={finding.client_ref} />
      </td>
      <td className="space-y-1 px-3 py-2.5">
        {finding.our_quote ? <QuoteText text={finding.our_quote} className="text-foreground" /> : null}
        {finding.our_ref ? (
          <RefChip kind="ours" label={finding.our_ref} />
        ) : (
          <p className="font-medium text-destructive">brak w naszej umowie</p>
        )}
      </td>
      <td className="px-3 py-2.5">
        <span className={cn("inline-flex items-center gap-1 font-medium", STATE_TONE[finding.state])}>
          <Icon className="size-3.5" aria-hidden />
          {CLIENT_FIT_STATE_LABEL[finding.state]}
        </span>
        <div className="mt-1">
          <LawyerBadge reasons={finding.lawyer_review} />
        </div>
      </td>
      <td className="space-y-1.5 px-3 py-2.5">
        {finding.state !== "ok" ? (
          <>
            {finding.next_step ? <p>{finding.next_step}</p> : null}
            <p className="text-muted-foreground">{affectedLabel(finding.affected_contracts)}</p>
            {finding.state === "gap" && finding.annex_text ? (
              <ClauseDraftAction finding={finding} clientId={clientId} canDraft={canDraft} />
            ) : null}
          </>
        ) : (
          <p className="text-muted-foreground">—</p>
        )}
      </td>
    </tr>
  );
}

function ClauseDraftAction({
  finding,
  clientId,
  canDraft,
}: {
  finding: ClientFitFinding;
  clientId: number;
  canDraft: boolean;
}) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const draft = useMutation({
    mutationFn: () => legalClientFitApi.requestClauseDraft(clientId, finding.id),
    onSuccess: (res) => {
      queryClient.setQueryData<ClientFitResponse>(legalClientFitKeys.client(clientId), (prev) =>
        prev
          ? {
              ...prev,
              findings: prev.findings.map((f) =>
                f.id === finding.id ? { ...f, clause_draft: res.clause_draft } : f,
              ),
            }
          : prev,
      );
      toast?.showSuccess(
        "Szkic klauzuli trafił do programisty i administratora. Wzór umowy sam się nie zmienia — nowe umowy dostaną zapis dopiero po przeglądzie.",
      );
    },
    onError: (error) =>
      toast?.showError(apiErrorMessage(error, "Nie udało się zapisać szkicu klauzuli.")),
  });
  if (finding.clause_draft) {
    return (
      <Badge variant="info" size="sm" className="h-auto whitespace-normal py-0.5">
        Szkic klauzuli zgłoszony {formatDateTimePl(finding.clause_draft.requested_at)}
        {finding.clause_draft.requested_by_name ? ` · ${finding.clause_draft.requested_by_name}` : ""}
      </Badge>
    );
  }
  if (!canDraft) return null;
  return (
    <Button
      size="sm"
      variant="outline"
      className="h-auto min-h-7 whitespace-normal py-1 text-left text-[12px]"
      loading={draft.isPending}
      disabled={draft.isPending}
      onClick={() => draft.mutate()}
    >
      <FilePlus2 className="h-3 w-3 shrink-0" aria-hidden />
      Zaproponuj jako klauzulę klienta do nowych umów
    </Button>
  );
}
