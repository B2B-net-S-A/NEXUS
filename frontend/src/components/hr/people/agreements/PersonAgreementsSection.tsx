"use client";

import { useState } from "react";
import { FilePlus2, MoreHorizontal } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadAgreementDocx,
  openAgreementPdf,
  useApplyAgreement,
  usePersonAgreements,
  useSendAgreement,
  useWithdrawAgreement,
  type Agreement,
  type PersonAgreements,
} from "@/lib/api/hr-agreements";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { CancelAgreementDialog, MarkSignedDialog } from "./AgreementActionDialogs";
import { AgreementDialog } from "./AgreementDialog";
import { STATUS_TONE, attention, periodLabel, rateLabel, statusNote } from "./agreement-format";

type Dialog =
  | { kind: "new" }
  | { kind: "edit"; agreement: Agreement }
  | { kind: "signed"; agreement: Agreement }
  | { kind: "cancel"; agreement: Agreement }
  | null;

type Command = "send" | "withdraw" | "apply" | "mark_signed" | "edit" | "cancel";

/** Główna akcja wiersza; reszta w menu „Więcej”. */
export function primaryCommand(agreement: Agreement): Command | null {
  const can = agreement.actions;
  if (can.send) return "send";
  if (can.mark_signed) return "mark_signed";
  if (can.withdraw) return "withdraw";
  if (can.apply) return "apply";
  return null;
}

const COMMAND_LABELS: Record<Command, string> = {
  send: "Wyślij do podpisu",
  withdraw: "Wycofaj z podpisu",
  apply: "Przepisz ponownie",
  mark_signed: "Oznacz jako podpisaną",
  edit: "Edytuj szkic",
  cancel: "Anuluj umowę",
};

function secondaryCommands(agreement: Agreement): Command[] {
  const can = agreement.actions;
  const primary = primaryCommand(agreement);
  const all: Command[] = [];
  if (can.edit) all.push("edit");
  if (can.mark_signed) all.push("mark_signed");
  if (can.cancel) all.push("cancel");
  return all.filter((command) => command !== primary);
}

function AgreementRow({
  agreement,
  busy,
  onCommand,
  onFile,
}: {
  agreement: Agreement;
  busy: boolean;
  onCommand: (command: Command, agreement: Agreement) => void;
  onFile: (kind: "pdf" | "docx", agreement: Agreement) => void;
}) {
  const primary = primaryCommand(agreement);
  const secondary = secondaryCommands(agreement);
  const note = statusNote(agreement);
  const warning = attention(agreement);
  const muted = agreement.status === "cancelled" || agreement.status === "rejected";
  return (
    <tr className={CALM_ROW}>
      <td className="py-2 pr-3 align-top">
        <span className={cn("font-medium", muted && "text-muted-foreground")}>{agreement.title}</span>
        <span className={CALM_SUBLINE}>
          {agreement.template
            ? `${agreement.template.name} · wersja ${agreement.template.version}`
            : "wzór niedostępny"}
          {" · "}
          {periodLabel(agreement)}
        </span>
        {warning ? (
          <span role="status" className="mt-1 block text-xs text-destructive">
            {warning}
          </span>
        ) : null}
      </td>
      <td className="py-2 pr-3 align-top text-sm">{rateLabel(agreement)}</td>
      <td className="py-2 pr-3 align-top">
        <StatusDot tone={STATUS_TONE[agreement.status]} note={note}>
          {agreement.status_label}
        </StatusDot>
      </td>
      <td className="py-2 align-top">
        <div className="flex items-center justify-end gap-1">
          {primary ? (
            <Button
              size="sm"
              variant={primary === "send" ? "primary" : "outline"}
              disabled={busy}
              onClick={() => onCommand(primary, agreement)}
            >
              {COMMAND_LABELS[primary]}
            </Button>
          ) : null}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={`Więcej: ${agreement.title}`}>
                <MoreHorizontal className="h-4 w-4" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onFile("pdf", agreement)}>Podgląd PDF</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onFile("docx", agreement)}>Plik Word</DropdownMenuItem>
              {secondary.map((command) => (
                <DropdownMenuItem key={command} onSelect={() => onCommand(command, agreement)}>
                  {COMMAND_LABELS[command]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </td>
    </tr>
  );
}

function AgreementsTable({
  data,
  onNew,
  onCommand,
  onFile,
  busy,
}: {
  data: PersonAgreements;
  onNew: () => void;
  onCommand: (command: Command, agreement: Agreement) => void;
  onFile: (kind: "pdf" | "docx", agreement: Agreement) => void;
  busy: boolean;
}) {
  if (data.agreements.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Nie ma jeszcze umów przygotowanych w NEXUSIE.
        {data.can_write ? (
          <div className="mt-3">
            <Button size="sm" variant="outline" onClick={onNew}>
              Przygotuj pierwszą umowę
            </Button>
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr>
            <th className={cn(CALM_HEAD, "w-[44%] py-2 pr-3 text-left")}>Umowa</th>
            <th className={cn(CALM_HEAD, "w-[20%] py-2 pr-3 text-left")}>Stawka</th>
            <th className={cn(CALM_HEAD, "w-[18%] py-2 pr-3 text-left")}>Stan</th>
            <th className={cn(CALM_HEAD, "py-2")}>
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.agreements.map((agreement) => (
            <AgreementRow
              key={agreement.id}
              agreement={agreement}
              busy={busy}
              onCommand={onCommand}
              onFile={onFile}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Kartoteka → „Umowy” (etap 5, E5): umowy i aneksy z osobą z generatora NEXUSA,
 * podpis przez Autenti albo ręcznie ze skanem. Widzą Kadry i Płace (Płace
 * tylko czytają); przełożony i sama osoba — nie (serwer 403, sekcja się
 * chowa). Podpisana umowa trafia do „Dokumentów” osoby.
 */
export function PersonAgreementsSection({ userId, enabled }: { userId: number; enabled: boolean }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = usePersonAgreements(userId, enabled);
  const send = useSendAgreement();
  const withdraw = useWithdrawAgreement();
  const apply = useApplyAgreement();
  const [dialog, setDialog] = useState<Dialog>(null);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (!enabled || state === "forbidden" || state === "not_found") return null;
  const data = query.data;
  const busy = send.isPending || withdraw.isPending || apply.isPending;

  const runCommand = async (command: Command, agreement: Agreement) => {
    if (command === "edit") return setDialog({ kind: "edit", agreement });
    if (command === "mark_signed") return setDialog({ kind: "signed", agreement });
    if (command === "cancel") return setDialog({ kind: "cancel", agreement });
    if (command === "send") {
      const ok = await askConfirm({
        title: "Wysłać umowę do podpisu?",
        description: `${agreement.title} · ${agreement.person_name ?? ""}. Autenti wyśle osobie e-mail z linkiem do podpisu; treść umowy zamrozi się w tej wersji.`,
        confirmLabel: "Wyślij do podpisu",
        cancelLabel: "Jeszcze nie",
      });
      if (!ok) return;
      send.mutate(agreement.id, {
        onSuccess: () => showToast("Umowa wysłana do podpisu", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wysłać umowy."), "error"),
      });
      return;
    }
    if (command === "withdraw") {
      const ok = await askConfirm({
        title: "Wycofać umowę z podpisu?",
        description: "Autenti zamknie link do podpisu, a umowa wróci do szkicu — możesz ją poprawić i wysłać ponownie.",
        confirmLabel: "Wycofaj",
        cancelLabel: "Zostaw",
        variant: "destructive",
      });
      if (!ok) return;
      withdraw.mutate(agreement.id, {
        onSuccess: () => showToast("Umowa wróciła do szkicu", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wycofać umowy."), "error"),
      });
      return;
    }
    apply.mutate(agreement.id, {
      onSuccess: (saved) =>
        saved.applied_at
          ? showToast("Umowa przepisana do kartoteki", "success")
          : showToast(saved.apply_error ?? "Umowa dalej nie przeszła do kartoteki.", "error"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przepisać umowy."), "error"),
    });
  };

  const openFile = (kind: "pdf" | "docx", agreement: Agreement) => {
    const action = kind === "pdf" ? openAgreementPdf(agreement.id) : downloadAgreementDocx(agreement.id);
    void action.catch((err: unknown) => showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error"));
  };

  return (
    <Card id="umowy" className="space-y-3 p-4" aria-labelledby={`agreements-title-${userId}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2
            id={`agreements-title-${userId}`}
            className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
          >
            Umowy
          </h2>
          <p className="text-xs text-muted-foreground">
            {data && !data.autenti_configured
              ? "Autenti nie jest ustawione — podpis oznaczasz ręcznie, ze skanem."
              : "Generator NEXUSA i podpis przez Autenti. Widzą Kadry i Płace."}
          </p>
        </div>
        {data?.can_write ? (
          <Button size="sm" onClick={() => setDialog({ kind: "new" })}>
            <FilePlus2 className="h-4 w-4" aria-hidden />
            Nowa umowa albo aneks
          </Button>
        ) : null}
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state !== "ready" || !data ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać umów."
          onRetry={() => void query.refetch()}
        />
      ) : (
        <AgreementsTable
          data={data}
          busy={busy}
          onNew={() => setDialog({ kind: "new" })}
          onCommand={(command, agreement) => void runCommand(command, agreement)}
          onFile={openFile}
        />
      )}
      {data && dialog?.kind === "new" ? <AgreementDialog overview={data} onClose={() => setDialog(null)} /> : null}
      {data && dialog?.kind === "edit" ? (
        <AgreementDialog overview={data} agreement={dialog.agreement} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "signed" ? (
        <MarkSignedDialog agreement={dialog.agreement} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "cancel" ? (
        <CancelAgreementDialog agreement={dialog.agreement} onClose={() => setDialog(null)} />
      ) : null}
      {confirmDialog}
    </Card>
  );
}
