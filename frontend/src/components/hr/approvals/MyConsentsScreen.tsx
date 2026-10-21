"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { ExternalLink, Plus } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useApprovalList,
  useWithdrawApproval,
  type ApprovalRequestRow,
} from "@/lib/api/hr-approvals";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { STATUS_TONE, moneyPl, payoutLine, timeline, type StatusTone } from "./approvals-format";
import { ConsentRequestForm } from "./ConsentRequestForm";
import { KindIcon } from "./KindIcon";
import { SettlementSection } from "./SettlementSection";
import { settlementNeedsAuthor, settlementPill } from "./settlement-format";

const TONE: Record<StatusTone, string> = {
  neutral: "bg-muted text-foreground",
  warning: "bg-warning-muted text-warning-muted-foreground",
  success: "bg-success-muted text-success-muted-foreground",
  danger: "bg-destructive/10 text-destructive",
};

const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

function StatusPill({ row }: { row: ApprovalRequestRow }) {
  // Zatwierdzony wydatek pokazuje stan rozliczenia (etap 3): „dołącz fakturę”.
  const settlement = settlementPill(row);
  const tone = settlement && settlementNeedsAuthor(row) ? "warning" : STATUS_TONE[row.status];
  return (
    <span
      className={cn("whitespace-nowrap rounded-full px-2 py-px text-xs font-medium", TONE[tone])}
    >
      {settlement ?? row.status_label}
    </span>
  );
}

function Detail({ row, onEdit }: { row: ApprovalRequestRow; onEdit: () => void }) {
  const withdraw = useWithdrawApproval();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const payout = payoutLine(row);

  const askWithdraw = async () => {
    const ok = await askConfirm({
      title: "Wycofać zgodę?",
      description: "Zgoda zniknie ze skrzynki decydującego. Możesz złożyć nową.",
      confirmLabel: "Wycofaj",
      variant: "destructive",
    });
    if (!ok) return;
    withdraw.mutate(row.id, {
      onSuccess: () => showToast("Zgoda wycofana.", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wycofać zgody."), "error"),
    });
  };

  return (
    <section
      aria-label={`Zgoda: ${row.title}`}
      className="min-w-0 flex-[999_1_480px] space-y-4 p-4 md:p-5"
    >
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-muted px-2 py-px text-xs font-medium text-foreground">
            {row.kind_label}
          </span>
          <StatusPill row={row} />
        </div>
        <h2 className="text-lg font-semibold text-foreground">{row.title}</h2>
        <p className="text-sm text-muted-foreground">
          {row.amount_text}
          {row.kind === "bonus" && row.beneficiary_name ? ` · dla ${row.beneficiary_name}` : ""}
          {payout ? ` · wypłata: ${payout}` : ""}
        </p>
        {row.contract_basis ? (
          <p className="text-sm text-muted-foreground">
            Podstawa w umowie: <span className="text-foreground">{row.contract_basis}</span>
          </p>
        ) : null}
        {row.link_url ? (
          <a
            href={row.link_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            Oferta / cennik <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        ) : null}
      </div>

      {row.status === "returned" && row.decision_note ? (
        <div className="rounded-lg bg-warning-muted px-3.5 py-3 text-sm text-warning-muted-foreground">
          <p className="font-semibold">Pytanie od {row.decided_by_name ?? "decydującego"}</p>
          <p className="mt-0.5 whitespace-pre-line">{row.decision_note}</p>
        </div>
      ) : null}

      <ol className="space-y-0" aria-label="Przebieg zgody">
        {timeline(row).map((step, index, all) => (
          <li key={step.key} className="flex gap-3">
            <span className="flex flex-col items-center">
              <span
                aria-hidden
                className={cn(
                  "mt-1 h-3 w-3 rounded-full",
                  step.state === "done" && "bg-primary",
                  step.state === "current" && "border-2 border-warning bg-card",
                  step.state === "todo" && "border-2 border-border bg-card",
                )}
              />
              {index < all.length - 1 ? (
                <span aria-hidden className="w-px flex-1 bg-border" />
              ) : null}
            </span>
            <span className="pb-4">
              <span
                className={cn(
                  "block text-sm font-semibold",
                  step.state === "todo" ? "text-muted-foreground" : "text-foreground",
                )}
              >
                {step.title}
              </span>
              {step.detail ? (
                <span className="block text-xs text-muted-foreground">{step.detail}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>

      <div>
        <p className={LABEL}>Po co</p>
        <p className="mt-1 whitespace-pre-line text-sm text-foreground">{row.purpose}</p>
      </div>

      {row.status === "approved" && !row.settlement ? (
        <p className="border-t border-border/60 pt-3 text-sm text-foreground">
          {row.kind === "bonus"
            ? "Wynagrodzenie dodatkowe jest w Płacach jako przyznane."
            : `Możesz kupić albo zapłacić${row.decided_amount ? ` — do ${moneyPl(row.decided_amount, row.currency)}` : ""}.`}
        </p>
      ) : null}
      <SettlementSection row={row} />

      {row.can_edit || row.can_withdraw ? (
        <div className="flex flex-wrap gap-2">
          {row.can_edit ? (
            <Button variant={row.status === "returned" ? "primary" : "outline"} onClick={onEdit}>
              {row.status === "returned" ? "Popraw i wyślij" : "Popraw"}
            </Button>
          ) : null}
          {row.can_withdraw ? (
            <Button variant="ghost" onClick={askWithdraw} disabled={withdraw.isPending}>
              Wycofaj
            </Button>
          ) : null}
        </div>
      ) : null}
      {confirmDialog}
    </section>
  );
}

const GROUPS: { title: string; match: (row: ApprovalRequestRow) => boolean }[] = [
  {
    title: "Do zrobienia przez Ciebie",
    match: (row) => row.status === "returned" || settlementNeedsAuthor(row),
  },
  {
    title: "W toku",
    match: (row) => row.status === "pending_supervisor" || row.status === "pending_final",
  },
  {
    title: "Zamknięte",
    match: (row) =>
      ["approved", "rejected", "withdrawn"].includes(row.status) && !settlementNeedsAuthor(row),
  },
];

/**
 * „Ludzie → Moje zgody” (makieta 20.10.2026): zgody, o które prosiłem — lista
 * po lewej, szczegół z osią „wysłana → poparcie → decyzja” po prawej;
 * „Poproś o zgodę” otwiera formularz w miejscu listy.
 */
export function MyConsentsScreen() {
  const params = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const mine = useApprovalList("mine");
  const linked = Number(params.get("request"));
  const [selectedId, setSelectedId] = useState<number | null>(
    Number.isInteger(linked) && linked > 0 ? linked : null,
  );
  const [form, setForm] = useState<{
    editing: ApprovalRequestRow | null;
  } | null>(params.get("new") === "1" ? { editing: null } : null);
  const rows = mine.data ?? [];
  const current = rows.find((row) => row.id === selectedId) ?? rows[0];

  if (form) {
    return (
      <ConsentRequestForm
        editing={form.editing}
        onCancel={() => setForm(null)}
        onDone={(row) => {
          setForm(null);
          setSelectedId(row.id);
          replaceUrl(`/people/consents?request=${row.id}`);
        }}
      />
    );
  }

  const state = resolveViewState({
    isLoading: mine.isLoading,
    isError: mine.isError,
    error: mine.error,
    isSuccess: mine.isSuccess,
    isEmpty: rows.length === 0,
  });
  const newButton = (
    <Button onClick={() => setForm({ editing: null })}>
      <Plus className="h-4 w-4" aria-hidden />
      Poproś o zgodę
    </Button>
  );
  if (state === "loading") {
    return <p className="py-4 text-sm text-muted-foreground">Wczytywanie zgód…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => mine.refetch()} />;
  }
  if (state === "empty" || !current) {
    return (
      <div className="space-y-3 rounded-xl border border-dashed border-border p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Nie prosiłeś(-aś) jeszcze o zgodę. Subskrypcja, koszty podróży, prezent, szkolenie albo
          wynagrodzenie dodatkowe — wszystko w jednym formularzu.
        </p>
        <div>{newButton}</div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">{newButton}</div>
      <div
        data-help="hr.consents.mine"
        className="flex flex-wrap overflow-hidden rounded-xl border border-border bg-card"
      >
        <div className="min-w-0 flex-[1_1_320px] border-b border-border/60 md:max-w-[440px] md:border-b-0 md:border-r">
          {GROUPS.map((group) => {
            const items = rows.filter(group.match);
            if (items.length === 0) return null;
            return (
              <div key={group.title}>
                <h3 className={cn(LABEL, "px-3.5 py-2.5")}>{group.title}</h3>
                <ul aria-label={group.title}>
                  {items.map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        aria-current={row.id === current.id ? "true" : undefined}
                        onClick={() => setSelectedId(row.id)}
                        className={cn(
                          "flex w-full items-center gap-2.5 border-t border-border/60 px-3.5 py-2.5 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                          row.id === current.id &&
                            "bg-primary/5 shadow-[inset_3px_0_0_hsl(var(--primary))]",
                        )}
                      >
                        <KindIcon kind={row.kind} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold text-foreground">
                            {row.title}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {row.amount_text}
                          </span>
                        </span>
                        <StatusPill row={row} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
        <Detail key={current.id} row={current} onEdit={() => setForm({ editing: current })} />
      </div>
    </div>
  );
}
