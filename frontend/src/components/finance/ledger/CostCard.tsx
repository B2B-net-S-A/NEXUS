"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCostAction,
  useCostCard,
  useCostPatch,
  type CostCard as CostCardData,
  type CostCategory,
  type CostFlag,
  type CostStage,
} from "@/lib/api/finance-ledger";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";
import { useAuthStore } from "@/store/auth";

import { Concerning } from "./CostsTab";
import { DecreePanel } from "./DecreePanel";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  FLAG_LABELS,
  FLAG_ORDER,
  stageButtons,
  type StageButton,
} from "./ledger-model";

const STEPS: readonly { stage: CostStage; label: string }[] = [
  { stage: "received", label: "Z KSeF do przyjęcia" },
  { stage: "new", label: "Do opisu" },
  { stage: "verified", label: "Zweryfikowana" },
  { stage: "ready", label: "Gotowa do księgowania" },
  { stage: "booked", label: "Zaksięgowana" },
];
const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";
const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

function Steps({ card }: { card: CostCardData }) {
  const steps = card.from_ksef ? STEPS : STEPS.slice(1);
  const current = steps.findIndex((step) => step.stage === card.stage);
  return (
    <ol className="flex flex-wrap text-xs" aria-label="Etap faktury">
      {steps.map((step, index) => (
        <li
          key={step.stage}
          aria-current={index === current ? "step" : undefined}
          className={cn(
            "-mr-px border border-border px-2.5 py-1",
            index < current && "bg-success-muted text-success-muted-foreground",
            index === current && "bg-primary/10 font-semibold text-primary",
            index > current && "bg-card text-muted-foreground",
          )}
        >
          {step.label}
        </li>
      ))}
    </ol>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children ?? "—"}</dd>
    </>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-3.5">
      <h2 className={LABEL}>{title}</h2>
      {children}
    </section>
  );
}

function historyText(item: CostCardData["history"][number]): string {
  if (item.action === "decree") {
    return item.detail.manual ? "Dekret poprawiony ręcznie" : "Dekret przeliczony z reguły";
  }
  if (item.action === "export") return `W paczce eksportu ${item.detail.batch ?? ""}`.trim();
  if (item.action === "unexport") return `Paczka ${item.detail.batch ?? ""} anulowana`.replace("  ", " ");
  if (item.action === "book") return `Zaksięgowana (paczka ${item.detail.batch ?? "—"})`;
  if (item.action === "reject") return `Odrzucona: ${item.detail.reason ?? ""}`.trim();
  if (item.to_stage_label && item.action === "back") return `Cofnięta do „${item.to_stage_label}”`;
  if (item.to_stage_label) return item.action_label;
  if (item.action === "flags") {
    const to = Array.isArray(item.detail.to) ? (item.detail.to as CostFlag[]) : [];
    return `Flagi: ${to.length ? to.map((flag) => FLAG_LABELS[flag] ?? flag).join(", ") : "bez flag"}`;
  }
  if (item.action === "category") {
    const to = item.detail.to as CostCategory | undefined;
    return `Kategoria: ${to ? CATEGORY_LABELS[to] : "—"}`;
  }
  if (item.action === "due_date") {
    const to = item.detail.to as string | null | undefined;
    return `Termin płatności: ${to ? formatIsoDatePl(to) : "usunięty"}`;
  }
  return item.action_label;
}

function Bookkeeping({ card, locked }: { card: CostCardData; locked: boolean }) {
  const patch = useCostPatch(card.id);
  const { showToast } = useToast();
  const [note, setNote] = useState(card.note ?? "");
  useEffect(() => setNote(card.note ?? ""), [card.note]);
  const save = (body: Parameters<typeof patch.mutate>[0], done: string) =>
    patch.mutate(body, {
      onSuccess: () => showToast(done, "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać."), "error"),
    });
  const toggle = (flag: CostFlag) => {
    const on = !card.flags.includes(flag);
    let next = on ? [...card.flags, flag] : card.flags.filter((item) => item !== flag);
    if (on && flag === "mpp") next = next.filter((item) => item !== "no_mpp");
    if (on && flag === "no_mpp") next = next.filter((item) => item !== "mpp");
    save({ flags: next }, "Flagi zapisane.");
  };
  return (
    <Panel title="Opis do księgowania">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm text-muted-foreground" htmlFor="cost-category">
          Kategoria
        </label>
        <select
          id="cost-category"
          value={card.category}
          disabled={locked || patch.isPending}
          onChange={(event) =>
            save({ category: event.target.value as CostCategory }, "Kategoria zapisana.")
          }
          className={CONTROL}
        >
          {CATEGORY_ORDER.map((category) => (
            <option key={category} value={category}>
              {CATEGORY_LABELS[category]}
            </option>
          ))}
        </select>
        <label className="ml-2 text-sm text-muted-foreground" htmlFor="cost-due">
          Termin płatności
        </label>
        <input
          id="cost-due"
          type="date"
          value={card.due_date_set ? (card.due_date ?? "") : ""}
          placeholder={card.due_date ?? undefined}
          disabled={locked || patch.isPending}
          onChange={(event) =>
            save({ due_date: event.target.value || null }, "Termin zapisany.")
          }
          className={CONTROL}
        />
      </div>
      {!card.due_date_set && card.due_date ? (
        <p className="text-xs text-muted-foreground">
          Termin z rozliczenia osoby: {formatIsoDatePl(card.due_date)}.
        </p>
      ) : null}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Flagi">
        {FLAG_ORDER.map((flag) => {
          const on = card.flags.includes(flag);
          return (
            <button
              key={flag}
              type="button"
              aria-pressed={on}
              disabled={locked || patch.isPending}
              onClick={() => toggle(flag)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors disabled:opacity-50 pointer-coarse:min-h-10",
                on
                  ? "border-warning/40 bg-warning-muted text-warning-muted-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {FLAG_LABELS[flag]}
            </button>
          );
        })}
      </div>
      <div className="space-y-1.5">
        <label className="text-sm text-muted-foreground" htmlFor="cost-note">
          Notatka
        </label>
        <Textarea
          id="cost-note"
          value={note}
          maxLength={4000}
          rows={2}
          disabled={locked || patch.isPending}
          onChange={(event) => setNote(event.target.value)}
        />
        {note !== (card.note ?? "") ? (
          <Button
            size="sm"
            variant="outline"
            loading={patch.isPending}
            onClick={() => save({ note: note.trim() || null }, "Notatka zapisana.")}
          >
            Zapisz notatkę
          </Button>
        ) : null}
      </div>
    </Panel>
  );
}

/** Karta faktury kosztowej (makieta M2, z dekretem do Symfonii FK z E2). */
export function CostCard({ id }: { id: number }) {
  const card = useCostCard(id);
  const action = useCostAction();
  const { askReason, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  // Podgląd jako inna osoba jest tylko do odczytu (backend i tak odmówi).
  const impersonating = useAuthStore((store) => store.realUser !== null);
  const state = resolveViewState({
    isLoading: card.isLoading,
    isError: card.isError,
    error: card.error,
    isSuccess: card.isSuccess,
    isEmpty: !card.data,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie faktury…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => card.refetch()} />;
  }
  if (!card.data) return <QueryStateNotice state="not_found" />;
  const data = card.data;
  const locked = data.own || data.stage === "booked" || impersonating;
  const run = async (button: StageButton) => {
    let reason: string | undefined;
    if (button.needsReason) {
      const answer = await askReason({
        title: "Odrzucić fakturę?",
        description:
          "Odrzucona faktura nie idzie do księgowania. Można ją przywrócić z zakładki „Odrzucone”.",
        confirmLabel: "Odrzuć",
        variant: "destructive",
        field: { label: "Powód", placeholder: "np. faktura nie dotyczy firmy", minLength: 3, maxLength: 500 },
      });
      if (!answer) return;
      reason = answer;
    }
    action.mutate(
      { ids: [data.id], action: button.action, reason },
      {
        onSuccess: () => showToast("Zapisano.", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić etapu."), "error"),
      },
    );
  };
  const back = `/finance?view=costs${data.stage === "received" ? "" : `&costStage=${data.stage}`}`;
  return (
    <div className="space-y-3.5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link href={back} className="text-sm text-primary hover:underline">
          ← Koszty
        </Link>
        <h1 className="font-display text-xl font-semibold leading-tight tracking-tight">
          {data.invoice_number ?? `Faktura #${data.id}`}
        </h1>
        <Badge variant={data.from_ksef ? "info" : "outline"}>{data.from_ksef ? "KSeF" : "PDF"}</Badge>
        <Badge variant="soft">{data.stage_label}</Badge>
      </header>

      {data.stage === "rejected" ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive-muted px-3.5 py-2.5 text-sm text-destructive-muted-foreground">
          Odrzucona: {data.reject_reason}
        </div>
      ) : (
        <Steps card={data} />
      )}
      {data.own ? (
        <div className="rounded-lg border border-border bg-muted/40 px-3.5 py-2.5 text-sm text-muted-foreground">
          To Twoja faktura — jej etap i opis zmienia ktoś inny z Finansów.
        </div>
      ) : null}

      <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3.5">
          <Panel title="Faktura">
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
              <Field label="Sprzedawca">{data.seller_name}</Field>
              <Field label="NIP">{data.seller_nip}</Field>
              <Field label="Numer">{data.invoice_number}</Field>
              <Field label="Numer KSeF">
                {data.ksef_number ? <span className="font-mono text-xs">{data.ksef_number}</span> : null}
              </Field>
              <Field label="Wystawiona">{data.issue_date ? formatIsoDatePl(data.issue_date) : null}</Field>
              <Field label="Wpłynęła">{formatIsoDatePl(warsawToday(new Date(data.received_at)))}</Field>
              <Field label="Netto">{formatMoney(data.net_amount, data.currency)}</Field>
              <Field label="VAT">{formatMoney(data.vat_amount, data.currency)}</Field>
              <Field label="Brutto">{formatMoney(data.gross_amount, data.currency)}</Field>
              <Field label="Źródło">{data.source_label}</Field>
            </dl>
          </Panel>
          <Panel title="Kogo dotyczy">
            <div className="text-sm">
              <Concerning row={data} />
            </div>
          </Panel>
          <Panel title="Kontrahent w kartotece">
            {data.counterparty_id ? (
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
                <Field label="Nazwa">{data.counterparty_name}</Field>
                <Field label="Konto kosztowe">
                  {data.cost_account ? <span className="font-mono">{data.cost_account}</span> : null}
                </Field>
                <Field label="ID Symfonii">{data.symfonia_partner_id}</Field>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">
                NIP-u sprzedawcy nie ma w kartotece kontrahentów.{" "}
                <Link href="/finance?view=counterparties" className="text-primary hover:underline">
                  Kontrahenci
                </Link>
              </p>
            )}
          </Panel>
        </div>
        <div className="space-y-3.5">
          <Bookkeeping card={data} locked={locked} />
          {data.decree ? (
            <DecreePanel entryId={data.id} section={data.decree} readOnly={impersonating || data.own} />
          ) : null}
          {!data.own && !impersonating && stageButtons(data.stage, data.from_ksef).length > 0 ? (
            <div className="flex flex-wrap justify-end gap-2">
              {stageButtons(data.stage, data.from_ksef).map((button) => (
                <Button
                  key={button.action}
                  size="sm"
                  variant={button.primary ? "primary" : "outline"}
                  disabled={action.isPending}
                  loading={action.isPending && action.variables?.action === button.action}
                  onClick={() => void run(button)}
                >
                  {button.label}
                </Button>
              ))}
            </div>
          ) : null}
          <Panel title="Historia">
            <ol className="space-y-1.5 text-sm">
              <li className="text-muted-foreground">
                {formatMomentPl(data.received_at)} · wpłynęła {data.from_ksef ? "z KSeF" : "jako PDF"}
              </li>
              {data.history.map((item, index) => (
                <li key={`${item.at}-${index}`}>
                  <span className="text-muted-foreground">{formatMomentPl(item.at)}</span> ·{" "}
                  {historyText(item)}
                  {item.actor ? <span className="text-muted-foreground"> · {item.actor}</span> : null}
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      </div>
      {confirmDialog}
    </div>
  );
}

export default CostCard;
