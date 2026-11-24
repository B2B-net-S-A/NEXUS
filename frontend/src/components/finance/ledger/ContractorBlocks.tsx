"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useGarnishments,
  useHolds,
  useLiftGarnishment,
  useReleaseHold,
  useSaveGarnishment,
  useSetHold,
  type Garnishment,
  type PlanItem,
} from "@/lib/api/finance-payments";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import {
  AUTHORITY_OPTIONS,
  INTEREST_OPTIONS,
  emptyGarnishmentForm,
  formFromGarnishment,
  garnishmentInput,
  releasedMessage,
  type GarnishmentForm,
} from "./contractor-blocks-model";
import { formatAccount } from "./payment-model";

const CONTROL =
  "h-8 w-full rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const FIELD = "space-y-1 text-xs text-muted-foreground";
const LABEL =
  "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

/** Co otwiera okno: zajęcie na kontrakcie (nowe albo zmiana) albo spór. */
export type BlockTarget =
  | {
      kind: "garnishment";
      contractId: number;
      label: string;
      garnishment: Garnishment | null;
    }
  | { kind: "hold"; item: PlanItem };

export function GarnishmentDialog({
  target,
  onClose,
}: {
  target: Extract<BlockTarget, { kind: "garnishment" }>;
  onClose: () => void;
}) {
  const today = warsawToday();
  const save = useSaveGarnishment();
  const { showToast } = useToast();
  const [form, setForm] = useState<GarnishmentForm>(() =>
    target.garnishment
      ? formFromGarnishment(target.garnishment)
      : emptyGarnishmentForm(today),
  );
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<GarnishmentForm>) =>
    setForm((current) => ({ ...current, ...patch }));

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {target.garnishment ? "Zmień zajęcie" : "Zajęcie wierzytelności"} —{" "}
            {target.label}
          </DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const result = garnishmentInput(form);
            if ("error" in result) {
              setError(result.error);
              return;
            }
            setError(null);
            save.mutate(
              {
                id: target.garnishment?.id ?? null,
                contractId: target.contractId,
                body: result.body,
              },
              {
                onSuccess: (saved) => {
                  const released = releasedMessage(saved.released_from_batches);
                  showToast(
                    released ?? "Zajęcie zapisane — paczka podzieli płatność.",
                    released ? "info" : "success",
                  );
                  onClose();
                },
                onError: (err) =>
                  setError(
                    apiErrorMessage(err, "Nie udało się zapisać zajęcia."),
                  ),
              },
            );
          }}
        >
          <DialogBody className="grid gap-3 sm:grid-cols-2">
            <label className={FIELD}>
              Organ
              <select
                aria-label="Rodzaj organu"
                value={form.authority_kind}
                onChange={(e) =>
                  set({
                    authority_kind: e.target
                      .value as GarnishmentForm["authority_kind"],
                  })
                }
                className={CONTROL}
              >
                {AUTHORITY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={FIELD}>
              Nazwa organu
              <input
                aria-label="Nazwa organu"
                value={form.authority_name}
                onChange={(e) => set({ authority_name: e.target.value })}
                className={CONTROL}
              />
            </label>
            <label className={FIELD}>
              Sygnatura sprawy
              <input
                aria-label="Sygnatura sprawy"
                value={form.case_number}
                onChange={(e) => set({ case_number: e.target.value })}
                className={cn(CONTROL, "font-mono")}
              />
            </label>
            <label className={FIELD}>
              Data doręczenia
              <input
                type="date"
                aria-label="Data doręczenia"
                value={form.served_on}
                max={today}
                onChange={(e) => set({ served_on: e.target.value })}
                className={CONTROL}
              />
            </label>
            <label className={FIELD}>
              Należność główna (zł)
              <input
                aria-label="Należność główna"
                inputMode="decimal"
                value={form.principal_amount}
                onChange={(e) => set({ principal_amount: e.target.value })}
                className={cn(CONTROL, "tabular-nums")}
              />
            </label>
            <label className={FIELD}>
              Koszty (zł)
              <input
                aria-label="Koszty"
                inputMode="decimal"
                value={form.costs_amount}
                onChange={(e) => set({ costs_amount: e.target.value })}
                className={cn(CONTROL, "tabular-nums")}
              />
            </label>
            <label className={FIELD}>
              Odsetki
              <select
                aria-label="Odsetki"
                value={form.interest_mode}
                onChange={(e) =>
                  set({
                    interest_mode: e.target
                      .value as GarnishmentForm["interest_mode"],
                  })
                }
                className={CONTROL}
              >
                {INTEREST_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            {form.interest_mode === "fixed" ? (
              <label className={FIELD}>
                Kwota odsetek (zł)
                <input
                  aria-label="Kwota odsetek"
                  inputMode="decimal"
                  value={form.interest_amount}
                  onChange={(e) => set({ interest_amount: e.target.value })}
                  className={cn(CONTROL, "tabular-nums")}
                />
              </label>
            ) : form.interest_mode === "rate" ? (
              <div className="grid grid-cols-2 gap-2">
                <label className={FIELD}>
                  Stopa roczna (%)
                  <input
                    aria-label="Stopa odsetek"
                    inputMode="decimal"
                    value={form.interest_rate}
                    onChange={(e) => set({ interest_rate: e.target.value })}
                    className={cn(CONTROL, "tabular-nums")}
                  />
                </label>
                <label className={FIELD}>
                  Od dnia
                  <input
                    type="date"
                    aria-label="Odsetki od dnia"
                    value={form.interest_from}
                    onChange={(e) => set({ interest_from: e.target.value })}
                    className={CONTROL}
                  />
                </label>
              </div>
            ) : (
              <span />
            )}
            <label className={cn(FIELD, "sm:col-span-2")}>
              Rachunek organu
              <input
                aria-label="Rachunek organu"
                value={form.authority_account}
                onChange={(e) => set({ authority_account: e.target.value })}
                placeholder="00 0000 0000 0000 0000 0000 0000"
                className={cn(CONTROL, "font-mono")}
              />
            </label>
            <label className={cn(FIELD, "sm:col-span-2")}>
              Uwaga (opcjonalnie)
              <input
                aria-label="Uwaga"
                value={form.note}
                onChange={(e) => set({ note: e.target.value })}
                className={CONTROL}
              />
            </label>
            <p className="text-xs text-muted-foreground sm:col-span-2">
              Przy paczce przelewów należność z odsetkami do dnia przelewu idzie
              na rachunek organu, reszta do kontraktora. Bez odsetek albo
              rachunku organu płatność czeka na Twoją decyzję.
            </p>
            {error ? (
              <p
                role="alert"
                className="text-sm text-destructive sm:col-span-2"
              >
                {error}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Anuluj
            </Button>
            <Button type="submit" loading={save.isPending}>
              Zapisz zajęcie
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function HoldDialog({
  item,
  onClose,
}: {
  item: PlanItem;
  onClose: () => void;
}) {
  const setHold = useSetHold();
  const { showToast } = useToast();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            Spór / wstrzymane — {item.seller_name ?? "kontraktor"}
            {item.period_month ? ` · ${item.period_month}` : ""}
          </DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!reason.trim()) {
              setError("Podaj powód wstrzymania.");
              return;
            }
            setHold.mutate(
              { entry_id: item.entry_id, reason: reason.trim() },
              {
                onSuccess: (hold) => {
                  const released = releasedMessage(hold.released_from_batches);
                  showToast(
                    released ?? "Płatność wstrzymana do zwolnienia.",
                    released ? "info" : "success",
                  );
                  onClose();
                },
                onError: (err) =>
                  setError(
                    apiErrorMessage(err, "Nie udało się wstrzymać płatności."),
                  ),
              },
            );
          }}
        >
          <DialogBody className="space-y-2">
            <label className={FIELD}>
              Powód (widzą go wszyscy przy paczce przelewów)
              <textarea
                aria-label="Powód wstrzymania"
                value={reason}
                maxLength={500}
                rows={3}
                onChange={(e) => setReason(e.target.value)}
                placeholder="np. praca bez zamówienia klienta od 1.10"
                className="w-full rounded-md border border-border bg-background p-2.5 text-sm"
              />
            </label>
            <p className="text-xs text-muted-foreground">
              Wstrzymanie dotyczy rozliczenia kontraktora za ten miesiąc:
              wszystkie jego faktury z tego miesiąca czekają, aż ktoś je zwolni.
            </p>
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Anuluj
            </Button>
            <Button
              type="submit"
              variant="destructive"
              loading={setHold.isPending}
            >
              Wstrzymaj płatność
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function LiftDialog({
  garnishment,
  onClose,
}: {
  garnishment: Garnishment;
  onClose: () => void;
}) {
  const today = warsawToday();
  const lift = useLiftGarnishment();
  const { showToast } = useToast();
  const [day, setDay] = useState(today);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Uchylenie zajęcia {garnishment.case_number}</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            lift.mutate(
              { id: garnishment.id, lifted_on: day, note: note.trim() || null },
              {
                onSuccess: (saved) => {
                  showToast(
                    releasedMessage(saved.released_from_batches) ??
                      "Zajęcie uchylone — od tego dnia płacimy kontraktorowi.",
                    "success",
                  );
                  onClose();
                },
                onError: (err) =>
                  setError(
                    apiErrorMessage(err, "Nie udało się uchylić zajęcia."),
                  ),
              },
            );
          }}
        >
          <DialogBody className="grid gap-3 sm:grid-cols-2">
            <label className={FIELD}>
              Data uchylenia
              <input
                type="date"
                aria-label="Data uchylenia"
                value={day}
                min={garnishment.served_on}
                max={today}
                onChange={(e) => setDay(e.target.value)}
                className={CONTROL}
              />
            </label>
            <label className={FIELD}>
              Uwaga (np. numer postanowienia)
              <input
                aria-label="Uwaga do uchylenia"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className={CONTROL}
              />
            </label>
            {error ? (
              <p
                role="alert"
                className="text-sm text-destructive sm:col-span-2"
              >
                {error}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Anuluj
            </Button>
            <Button type="submit" loading={lift.isPending}>
              Uchyl zajęcie
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function contractLabel(row: {
  contractor_name?: string | null;
  client_name?: string | null;
  contract_id?: number;
}): string {
  const who = row.contractor_name || `Kontrakt #${row.contract_id ?? "?"}`;
  return row.client_name ? `${who} · ${row.client_name}` : who;
}

/** Sekcja „Zajęcia i spory”: aktywne zajęcia i wstrzymania z akcjami. */
export function ContractorBlocks({
  canWrite,
  onEdit,
}: {
  canWrite: boolean;
  onEdit: (target: BlockTarget) => void;
}) {
  const garnishments = useGarnishments();
  const holds = useHolds();
  const release = useReleaseHold();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showToast } = useToast();
  const [lifting, setLifting] = useState<Garnishment | null>(null);
  const [showLifted, setShowLifted] = useState(false);
  const rows = (garnishments.data?.items ?? []).filter(
    (g) => showLifted || g.active,
  );
  const lifted = (garnishments.data?.items ?? []).filter(
    (g) => !g.active,
  ).length;
  useEffect(() => {
    if (lifted === 0) setShowLifted(false);
  }, [lifted]);

  return (
    <section className="space-y-2.5" aria-labelledby="contractor-blocks">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="contractor-blocks" className={LABEL}>
          Zajęcia i spory
        </h2>
        {lifted > 0 ? (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={() => setShowLifted((v) => !v)}
          >
            {showLifted ? "Ukryj uchylone" : `Pokaż uchylone (${lifted})`}
          </Button>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        Zajęcie dopisujesz z wiersza faktury kontraktora w „Do zapłaty”
        (przycisk „Zajęcie”). Działa na wszystkie faktury tego kontraktora.
      </p>
      {garnishments.isError ? (
        <QueryStateNotice
          state="error"
          onRetry={() => garnishments.refetch()}
        />
      ) : garnishments.isSuccess && rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
          Brak aktywnych zajęć wierzytelności.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {rows.map((g) => (
            <li
              key={g.id}
              className="flex flex-wrap items-start gap-x-3 gap-y-1 px-3.5 py-2.5 text-sm"
            >
              <div className="min-w-0 flex-1">
                <span className="block font-medium">{contractLabel(g)}</span>
                <span className={CALM_SUBLINE}>
                  {g.authority_label} · {g.authority_name} ·{" "}
                  <span className="font-mono">{g.case_number}</span> · doręczone{" "}
                  {formatIsoDatePl(g.served_on)}
                </span>
                <span className={cn(CALM_SUBLINE, "font-mono")}>
                  {formatAccount(g.authority_account) || "bez rachunku organu"}
                </span>
                {g.problem ? (
                  <span className="mt-0.5 block text-xs text-destructive">
                    Kwoty nie da się policzyć: {g.problem}
                  </span>
                ) : null}
                {!g.active ? (
                  <span className={CALM_SUBLINE}>
                    Uchylone {g.lifted_on ? formatIsoDatePl(g.lifted_on) : ""}
                    {g.lifted_by_name ? ` · ${g.lifted_by_name}` : ""}
                    {g.lifted_note ? ` · ${g.lifted_note}` : ""}
                  </span>
                ) : null}
              </div>
              <div className="text-right tabular-nums">
                <span className="block">
                  {g.due_today !== null ? formatMoney(g.due_today, "PLN") : "—"}
                </span>
                <span className={CALM_SUBLINE}>
                  do spłaty dziś · przekazano{" "}
                  {formatMoney(g.transferred, "PLN")}
                </span>
              </div>
              {canWrite && g.active ? (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      onEdit({
                        kind: "garnishment",
                        contractId: g.contract_id,
                        label: contractLabel(g),
                        garnishment: g,
                      })
                    }
                  >
                    Zmień
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setLifting(g)}
                  >
                    Uchyl
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {holds.isError ? (
        <QueryStateNotice state="error" onRetry={() => holds.refetch()} />
      ) : holds.isSuccess && holds.data.items.length > 0 ? (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {holds.data.items.map((h) => (
            <li
              key={h.id}
              className="flex flex-wrap items-start gap-x-3 gap-y-1 px-3.5 py-2.5 text-sm"
            >
              <Badge size="sm" variant="danger">
                Spór / wstrzymane
              </Badge>
              <div className="min-w-0 flex-1">
                <span className="block font-medium">
                  {contractLabel(h)}
                  {h.period_month ? ` · ${h.period_month}` : ""}
                </span>
                <span className="block text-sm">{h.reason}</span>
                <span className={CALM_SUBLINE}>
                  {h.created_by_name ?? "Finanse"}
                  {h.created_at
                    ? ` · ${formatIsoDatePl(h.created_at.slice(0, 10))}`
                    : ""}
                </span>
              </div>
              {canWrite ? (
                <Button
                  size="sm"
                  variant="outline"
                  loading={release.isPending && release.variables?.id === h.id}
                  onClick={async () => {
                    const ok = await askConfirm({
                      title: "Zwolnić wstrzymaną płatność?",
                      description:
                        "Faktury kontraktora z tego miesiąca wrócą do „Do zapłaty”.",
                      confirmLabel: "Zwolnij",
                    });
                    if (!ok) return;
                    release.mutate(
                      { id: h.id, note: null },
                      {
                        onSuccess: () =>
                          showToast("Płatność zwolniona.", "success"),
                        onError: (err) =>
                          showToast(
                            apiErrorMessage(
                              err,
                              "Nie udało się zwolnić płatności.",
                            ),
                            "error",
                          ),
                      },
                    );
                  }}
                >
                  Zwolnij
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {lifting ? (
        <LiftDialog garnishment={lifting} onClose={() => setLifting(null)} />
      ) : null}
      {confirmDialog}
    </section>
  );
}
