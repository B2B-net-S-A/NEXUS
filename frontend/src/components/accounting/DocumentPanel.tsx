"use client";

import { Lock, X } from "lucide-react";
import Link from "next/link";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useApproveDocuments,
  useDeleteDocument,
  useDocumentCard,
  useReverseDocument,
  type DocumentCard,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { datePl, gr, sourceLabel } from "./ledger-model";

/** Karta dokumentu: dekret, fakty, ślad i akcje (bufor albo storno). */
export function DocumentPanel({
  id,
  onClose,
  onEdit,
  onOpenDocument,
}: {
  id: number;
  onClose: () => void;
  onEdit: (card: DocumentCard) => void;
  onOpenDocument: (id: number) => void;
}) {
  const card = useDocumentCard(id);
  const approve = useApproveDocuments();
  const remove = useDeleteDocument();
  const reverse = useReverseDocument();
  const { showToast } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();

  if (card.isLoading) {
    return <aside className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">Wczytywanie…</aside>;
  }
  if (card.isError || !card.data) {
    return <QueryStateNotice state="error" onRetry={() => card.refetch()} />;
  }
  const doc = card.data;
  const debit = doc.lines.filter((line) => line.side === "debit").reduce((sum, line) => sum + line.amount, 0);
  const credit = doc.lines.filter((line) => line.side === "credit").reduce((sum, line) => sum + line.amount, 0);

  const doApprove = () =>
    approve.mutate([doc.id], {
      onSuccess: (result) => {
        const done = result.approved[0];
        if (done) showToast(`Zatwierdzono — pozycja dziennika ${done.journal_no}.`);
        else if (result.refused[0]) showToast(result.refused[0].detail, "error");
      },
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zatwierdzić."), "error"),
    });

  const doDelete = async () => {
    const ok = await askConfirm({
      title: `Usunąć ${doc.number} z bufora?`,
      description: "Szkic zniknie z bufora; w śladzie zostanie jego numer i kwota.",
      confirmLabel: "Usuń szkic",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(doc.id, {
      onSuccess: () => {
        showToast("Usunięto szkic.");
        onClose();
      },
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się usunąć szkicu."), "error"),
    });
  };

  const doReverse = async () => {
    const reason = await askReason({
      title: `Storno ${doc.number}?`,
      description:
        "Powstanie dokument ST z tymi samymi kontami i kwotami z minusem (storno czerwone), od razu zatwierdzony w bieżącym otwartym okresie.",
      confirmLabel: "Zrób storno",
      variant: "destructive",
      field: { label: "Powód", placeholder: "np. błędna kwota faktury", minLength: 3, maxLength: 500 },
    });
    if (!reason) return;
    reverse.mutate(
      { id: doc.id, reason },
      {
        onSuccess: (storno) => {
          showToast(`Storno ${storno.number} — pozycja dziennika ${storno.journal_no}.`);
          onOpenDocument(storno.id);
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zrobić storna."), "error"),
      },
    );
  };

  return (
    <aside className="min-w-0 self-start rounded-lg border border-border bg-card xl:sticky xl:top-3">
      <div className="flex items-start justify-between gap-3 border-b border-border/70 px-3.5 py-2.5">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
            {doc.type_label} · {doc.status === "approved" ? `dziennik poz. ${doc.journal_no}` : "bufor"}
          </p>
          <h2 className="truncate text-[15px] font-semibold">{doc.number}</h2>
          <p className="truncate text-[12px] text-muted-foreground">
            {doc.counterparty?.name ?? (doc.description || "—")}
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Zamknij kartę" className="text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 px-3.5 py-2 text-[12px]">
        <dt className="text-muted-foreground">Data operacji</dt>
        <dd className="tabular-nums">{datePl(doc.op_date)}</dd>
        <dt className="text-muted-foreground">Data dokumentu</dt>
        <dd className="tabular-nums">{datePl(doc.doc_date)}</dd>
        {doc.description ? (
          <>
            <dt className="text-muted-foreground">Opis</dt>
            <dd className="break-words">{doc.description}</dd>
          </>
        ) : null}
        {doc.source ? (
          <>
            <dt className="text-muted-foreground">Źródło</dt>
            <dd className="truncate">
              {(() => {
                const source = sourceLabel(doc.source);
                return source.href ? (
                  <Link href={source.href} className="text-primary hover:underline">
                    {source.label}
                  </Link>
                ) : (
                  source.label
                );
              })()}
            </dd>
          </>
        ) : null}
        {doc.fx_rate ? (
          <>
            <dt className="text-muted-foreground">Kurs</dt>
            <dd className="tabular-nums">
              {doc.currency} {doc.fx_rate.replace(".", ",")} z {datePl(doc.fx_date)}
            </dd>
          </>
        ) : null}
        {doc.reverses_id ? (
          <>
            <dt className="text-muted-foreground">Storno dokumentu</dt>
            <dd>
              <button type="button" className="text-primary hover:underline" onClick={() => onOpenDocument(doc.reverses_id!)}>
                otwórz oryginał
              </button>
            </dd>
          </>
        ) : null}
        {doc.reversed_by_id ? (
          <>
            <dt className="text-muted-foreground">Odwrócony</dt>
            <dd>
              <button type="button" className="text-primary hover:underline" onClick={() => onOpenDocument(doc.reversed_by_id!)}>
                otwórz storno
              </button>
            </dd>
          </>
        ) : null}
      </dl>
      {doc.sensitivity === "payroll" ? (
        <p className="mx-3.5 mb-2 flex items-start gap-1.5 rounded-md bg-muted/60 px-2.5 py-2 text-[12px] text-muted-foreground">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Dokument płacowy — widzą go Płace i administrator.
        </p>
      ) : null}
      <table className="w-full table-fixed text-[12.5px]">
        <thead>
          <tr className="border-y border-border/70">
            <th className={cn(CALM_HEAD, "w-[27%] px-3.5 py-1.5 text-left")}>Konto</th>
            <th className={cn(CALM_HEAD, "px-1 py-1.5 text-left")}>Treść</th>
            <th className={cn(CALM_HEAD, "w-[21%] px-1 py-1.5 text-right")}>Wn</th>
            <th className={cn(CALM_HEAD, "w-[21%] px-3.5 py-1.5 text-right")}>Ma</th>
          </tr>
        </thead>
        <tbody>
          {doc.lines.map((line) => (
            <tr key={line.line_no} className={cn(CALM_ROW, "align-top")}>
              <td className="min-w-0 px-3.5 py-1.5">
                <span className="font-medium tabular-nums">{line.account}</span>
                <span className={cn(CALM_SUBLINE, "truncate")} title={line.account_name ?? undefined}>
                  {line.account_name ?? "konta nie ma w planie"}
                </span>
              </td>
              <td className="min-w-0 px-1 py-1.5">
                <span className="block truncate" title={line.description}>
                  {line.description || line.counterparty?.name || "—"}
                </span>
                {line.mpk ? <span className={CALM_SUBLINE}>MPK {line.mpk}</span> : null}
              </td>
              <td className={cn(CALM_AMOUNT, "px-1 py-1.5")}>
                {line.side === "debit" ? gr(line.amount) : <span className={CALM_EMPTY}>—</span>}
              </td>
              <td className={cn(CALM_AMOUNT, "px-3.5 py-1.5")}>
                {line.side === "credit" ? gr(line.amount) : <span className={CALM_EMPTY}>—</span>}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td className="px-3.5 py-1.5 text-[12px] font-semibold" colSpan={2}>
              Razem{" "}
              {debit === credit ? (
                <span className="text-success">· Wn = Ma</span>
              ) : (
                <span className="text-destructive">· różnica</span>
              )}
            </td>
            <td className={cn(CALM_AMOUNT, "px-1 py-1.5 font-semibold")}>{gr(debit)}</td>
            <td className={cn(CALM_AMOUNT, "px-3.5 py-1.5 font-semibold")}>{gr(credit)}</td>
          </tr>
        </tfoot>
      </table>
      <div className="flex flex-wrap items-center gap-2 border-t border-border/70 px-3.5 py-2.5">
        {doc.can_approve ? (
          <Button size="sm" loading={approve.isPending} onClick={doApprove}>
            Zatwierdź
          </Button>
        ) : null}
        {doc.can_edit ? (
          <Button size="sm" variant="outline" onClick={() => onEdit(doc)}>
            Popraw
          </Button>
        ) : null}
        {doc.can_edit ? (
          <Button size="sm" variant="quiet" loading={remove.isPending} onClick={() => void doDelete()}>
            Usuń szkic
          </Button>
        ) : null}
        {doc.can_reverse ? (
          <Button size="sm" variant="quiet" loading={reverse.isPending} onClick={() => void doReverse()}>
            Storno
          </Button>
        ) : null}
        <span className="ml-auto text-[11.5px] text-muted-foreground">
          {doc.status === "approved" ? "Zapis trwały — poprawka tylko stornem" : "Bufor — można poprawić dekret"}
        </span>
      </div>
      {doc.events.length ? (
        <div className="border-t border-border/70 px-3.5 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">Ślad</p>
          <ul className="mt-1 space-y-1">
            {doc.events.map((event, index) => (
              <li key={`${event.action}-${index}`}>
                <StatusDot
                  tone="neutral"
                  note={`${event.actor_name ?? "system"} · ${event.at ? event.at.slice(0, 16).replace("T", " ") : ""}`}
                >
                  {event.label}
                </StatusDot>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {confirmDialog}
    </aside>
  );
}
