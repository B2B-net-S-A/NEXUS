"use client";

/**
 * „Umowy” w „Czeka na Ciebie” (04.10.2026, decyzje Artura D1 i D5).
 *
 * Rekruter generuje umowę z panelu osoby, ale podpis potwierdza osoba
 * z uprawnieniem „Podpis B2B” (Delivery Lead, TCM, admin). Ta sekcja zbiera
 * dla niej sprawy z `GET /api/board-tasks` → `agreements`:
 *  - do potwierdzenia: prośby rekruterów i karty „Zatrudniony” z umową
 *    „W trakcie” (np. ruch z Traffita) — „Potwierdź podpis” otwiera to samo
 *    okno co w rejestrze, ono zakłada kontrakt i zamówienie,
 *  - do zamknięcia: karta odrzucona/rezygnacja przy umowie „W trakcie”
 *    („Anuluj umowę”) albo przy podpisanej umowie z trwającym kontraktem
 *    („Zakończ współpracę” w kontrakcie).
 * Twoje prośby, na które czekasz, stoją w „U innych” (`AgreementWaitingSection`).
 */

import Link from "next/link";
import dynamic from "next/dynamic";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  AGREEMENT_TASK_REASON_LABEL,
  BOARD_TASKS_QUERY_KEY,
  waitingFor,
  type AgreementTaskRow,
  type AgreementTasks,
} from "@/lib/api/boardTasks";

// Okno podpisu żyje w module Generatora — ładowane dopiero po kliknięciu.
const ConfirmFullySignedDialog = dynamic(
  () =>
    import("@/components/v2/pages/B2BContractGeneratorV2").then(
      (m) => m.ConfirmFullySignedDialog,
    ),
  { ssr: false },
);

const ROWS = 5;

function personLink(row: AgreementTaskRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function registerLink(row: AgreementTaskRow): string {
  return `/contracts/b2b-generator?tab=generated&q=${encodeURIComponent(row.contract_number)}`;
}

function RowHead({ row }: { row: AgreementTaskRow }) {
  return (
    <div className="min-w-[12rem] flex-1">
      <Link
        href={personLink(row)}
        title={row.candidate_name}
        className="block max-w-full truncate text-sm font-medium hover:underline"
      >
        {row.candidate_name}
      </Link>
      <p className="truncate text-xs text-muted-foreground">
        Umowa {row.contract_number} · {row.job_title}
        {row.client_name ? ` · ${row.client_name}` : ""}
      </p>
      <p className="text-xs text-muted-foreground">
        {AGREEMENT_TASK_REASON_LABEL[row.reason]}
        {row.requested_by_name ? ` — prosi ${row.requested_by_name}` : ""}
      </p>
    </div>
  );
}

function AgreementList({
  title,
  hint,
  rows,
  children,
}: {
  title: string;
  hint: string;
  rows: AgreementTaskRow[];
  children: (row: AgreementTaskRow) => React.ReactNode;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, ROWS);
  return (
    <section aria-label={title} className="min-w-0">
      <header className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {rows.length}
        </span>
      </header>
      <p className="mb-2 text-xs text-muted-foreground">{hint}</p>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => (
          <li
            key={`${row.reason}-${row.generated_id}`}
            className="flex flex-wrap items-center gap-x-2 gap-y-1.5 px-3 py-2"
          >
            {children(row)}
          </li>
        ))}
      </ul>
      {rows.length > ROWS ? (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {all ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
        </button>
      ) : null}
    </section>
  );
}

export function agreementTasksCount(tasks: AgreementTasks | null | undefined): number {
  if (!tasks) return 0;
  return tasks.to_confirm.length + tasks.to_close.length;
}

export function AgreementTasksSection({ tasks }: { tasks: AgreementTasks | null | undefined }) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [signRow, setSignRow] = useState<B2BGeneratedContractRow | null>(null);

  if (!tasks || agreementTasksCount(tasks) === 0) return null;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    void queryClient.invalidateQueries({ queryKey: ["kanban"] });
  };

  const openSignature = async (row: AgreementTaskRow) => {
    setBusyId(row.generated_id);
    try {
      const rows = await b2bGeneratorApi.generated(20, {
        jobId: row.job_id,
        candidateId: row.candidate_id,
      });
      const found = rows.find((r) => r.id === row.generated_id);
      if (!found) {
        showError(`Nie znaleziono umowy ${row.contract_number} w rejestrze — odśwież pulpit.`);
        refresh();
        return;
      }
      if (!found.can_confirm_signed) {
        showError(
          found.blocked_reason ??
            `Umowy ${row.contract_number} nie możesz oznaczyć jako podpisanej.`,
        );
        return;
      }
      setSignRow(found);
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się otworzyć umowy."));
    } finally {
      setBusyId(null);
    }
  };

  const cancelAgreement = async (row: AgreementTaskRow) => {
    const ok = await askConfirm({
      title: `Anulować umowę ${row.contract_number}?`,
      description:
        "Umowa nie doszła do skutku. Wpis zostaje w rejestrze, a numer nie wraca do puli.",
      confirmLabel: "Anuluj umowę",
      cancelLabel: "Wróć",
      variant: "destructive",
    });
    if (!ok) return;
    setBusyId(row.generated_id);
    try {
      await b2bGeneratorApi.updateGenerated(row.generated_id, { contract_status: "cancelled" });
      showSuccess(`Umowa ${row.contract_number} jest anulowana.`);
      refresh();
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się anulować umowy."));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      {tasks.to_confirm.length > 0 ? (
        <AgreementList
          title="Umowy do potwierdzenia"
          hint="Partner podpisał? Potwierdzenie zakłada kontrakt i zamówienie i przesuwa kartę na „Zatrudniony”."
          rows={tasks.to_confirm}
        >
          {(row) => (
            <>
              <RowHead row={row} />
              <div className="ml-auto flex shrink-0 items-center gap-2">
                {row.since ? (
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {waitingFor(row.since)}
                  </span>
                ) : null}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyId === row.generated_id}
                  onClick={() => void openSignature(row)}
                  aria-label={`Potwierdź podpis: ${row.candidate_name}`}
                >
                  Potwierdź podpis
                </Button>
              </div>
            </>
          )}
        </AgreementList>
      ) : null}
      {tasks.to_close.length > 0 ? (
        <AgreementList
          title="Umowy do zamknięcia"
          hint="Proces kandydata jest zamknięty, a umowa albo kontrakt nadal żyje."
          rows={tasks.to_close}
        >
          {(row) => (
            <>
              <RowHead row={row} />
              <div className="ml-auto flex shrink-0 items-center gap-2">
                {row.reason === "closed_unsigned" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busyId === row.generated_id}
                    onClick={() => void cancelAgreement(row)}
                    aria-label={`Anuluj umowę: ${row.candidate_name}`}
                  >
                    Anuluj umowę
                  </Button>
                ) : row.contract_id !== null ? (
                  <Button size="sm" variant="outline" asChild>
                    <Link
                      href={`/contracts/${row.contract_id}`}
                      aria-label={`Zakończ współpracę: ${row.candidate_name}`}
                    >
                      Zakończ współpracę
                    </Link>
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" asChild>
                    <Link href={registerLink(row)}>W rejestrze</Link>
                  </Button>
                )}
              </div>
            </>
          )}
        </AgreementList>
      ) : null}
      {signRow ? (
        <ConfirmFullySignedDialog
          row={signRow}
          open={true}
          onOpenChange={(v: boolean) => {
            if (!v) setSignRow(null);
          }}
          onConfirmed={(result) => {
            setSignRow(null);
            showSuccess(result.message);
            refresh();
          }}
        />
      ) : null}
      {confirmDialog}
    </>
  );
}

/** „U innych”: Twoje prośby o potwierdzenie podpisu, na które czekasz. */
export function AgreementWaitingSection({
  rows,
}: {
  rows: AgreementTaskRow[] | null | undefined;
}) {
  if (!rows || rows.length === 0) return null;
  return (
    <AgreementList
      title="Prośby o podpis umowy"
      hint="Czekasz, aż Delivery Lead potwierdzi podpis Partnera."
      rows={rows}
    >
      {(row) => (
        <>
          <RowHead row={row} />
          {row.since ? (
            <span className="ml-auto inline-flex shrink-0 items-center gap-1 text-xs tabular-nums text-muted-foreground">
              <Clock className="h-3 w-3" aria-hidden />
              {waitingFor(row.since)}
            </span>
          ) : null}
        </>
      )}
    </AgreementList>
  );
}
