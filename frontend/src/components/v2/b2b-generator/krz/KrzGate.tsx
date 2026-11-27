"use client";

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
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
import { Textarea } from "@/components/ui/textarea";
import {
  b2bGeneratorApi,
  type B2BGeneratedContractRow,
  type B2BKrzState,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  EMPTY_KRZ_FORM,
  krzBadge,
  krzCheckedLine,
  krzFormToPayload,
  krzWaitingLine,
  type KrzFormState,
} from "@/lib/b2b-krz";
import { cn } from "@/lib/utils";

import { KrzSearchPanel } from "./KrzSearchPanel";

function useRefreshAfterKrz() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    void queryClient.invalidateQueries({ queryKey: ["kanban"] });
    void queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
  };
}

interface KrzBadgeProps {
  state: B2BKrzState;
  className?: string;
}

/** Plakietka KRZ przy wierszu rejestru i w panelu osoby. */
export function KrzBadge({ state, className }: KrzBadgeProps) {
  const view = krzBadge(state);
  return (
    <Badge
      variant={view.tone}
      size="sm"
      className={cn("whitespace-nowrap", className)}
      data-testid="krz-badge"
    >
      {view.label}
    </Badge>
  );
}

interface KrzCheckDialogProps {
  row: B2BGeneratedContractRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** „Sprawdź w KRZ” przy umowie z rejestru albo z panelu osoby. */
export function KrzCheckDialog({ row, open, onOpenChange }: KrzCheckDialogProps) {
  const toast = useToast();
  const refresh = useRefreshAfterKrz();
  const [form, setForm] = React.useState<KrzFormState>(EMPTY_KRZ_FORM);
  React.useEffect(() => {
    if (open) setForm(EMPTY_KRZ_FORM);
  }, [open]);
  const payload = krzFormToPayload(form);
  const save = useMutation({
    mutationFn: () => {
      if (!payload) throw new Error("Zaznacz wynik sprawdzenia.");
      return b2bGeneratorApi.recordKrz(row.id, payload);
    },
    onSuccess: () => {
      refresh();
      toast.showSuccess(
        payload?.result === "entry"
          ? "Zapisano wpis w KRZ. Delivery Lead klienta dostał prośbę o decyzję."
          : "Zapisano: brak wpisów w KRZ.",
      );
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Sprawdź Partnera w Krajowym Rejestrze Zadłużonych</DialogTitle>
          <DialogDescription>
            Umowa {row.contract_number}. Otwórz KRZ, wklej numer w wyszukiwarce i zaznacz,
            co pokazał rejestr.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <KrzSearchPanel
            nip={row.partner_nip ?? ""}
            value={form}
            onChange={setForm}
            disabled={save.isPending}
          />
          {save.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(save.error, "Nie udało się zapisać wyniku KRZ.")}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button disabled={!payload || save.isPending} onClick={() => save.mutate()}>
            Zapisz wynik
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface KrzDecisionDialogProps {
  row: B2BGeneratedContractRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Decyzja Delivery Leada przy wpisie w KRZ: dopuść albo anuluj umowę. */
export function KrzDecisionDialog({ row, open, onOpenChange }: KrzDecisionDialogProps) {
  const toast = useToast();
  const refresh = useRefreshAfterKrz();
  const reasonId = React.useId();
  const [reason, setReason] = React.useState("");
  React.useEffect(() => {
    if (open) setReason("");
  }, [open]);
  const state = row.krz;
  const decide = useMutation({
    mutationFn: (decision: "allowed" | "rejected") =>
      b2bGeneratorApi.decideKrz(row.id, { decision, reason: reason.trim() }),
    onSuccess: (_row, decision) => {
      refresh();
      toast.showSuccess(
        decision === "allowed"
          ? "Umowa dopuszczona do podpisu. Finanse dostały informację."
          : "Umowa niedopuszczona i anulowana.",
      );
      onOpenChange(false);
    },
  });
  const reasonOk = reason.trim().length >= 3;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Wpis w KRZ: umowa {row.contract_number}</DialogTitle>
          <DialogDescription>
            {row.partner_display_name ?? row.partner_name ?? "Partner"} ma wpis w Krajowym
            Rejestrze Zadłużonych. Zdecyduj, czy umowa idzie do podpisu.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {state ? (
            <div className="space-y-1 rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground">
              <p className="font-medium">{state.entry_label ?? "Wpis w KRZ"}</p>
              {state.entry_note ? <p>Sygnatura albo opis: {state.entry_note}</p> : null}
              {krzCheckedLine(state) ? (
                <p className="text-xs">{krzCheckedLine(state)}</p>
              ) : null}
            </div>
          ) : null}
          <p className="text-sm text-muted-foreground">
            Przy umorzonej egzekucji albo upadłości komornik może zająć faktury Partnera i wtedy
            płacimy komornikowi. Po dopuszczeniu Finanse dostaną informację.
          </p>
          <div className="space-y-1">
            <label htmlFor={reasonId} className="text-sm font-medium">
              Uzasadnienie
            </label>
            <Textarea
              id={reasonId}
              value={reason}
              maxLength={500}
              rows={3}
              placeholder="np. egzekucja z 2022, Partner przedstawił potwierdzenie spłaty"
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          {decide.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(decide.error, "Nie udało się zapisać decyzji.")}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            variant="outline"
            className="text-destructive"
            disabled={!reasonOk || decide.isPending}
            onClick={() => decide.mutate("rejected")}
          >
            Nie podpisujemy, anuluj umowę
          </Button>
          <Button disabled={!reasonOk || decide.isPending} onClick={() => decide.mutate("allowed")}>
            Dopuść do podpisu
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface KrzGateProps {
  row: B2BGeneratedContractRow;
  /** Węższy układ do panelu osoby (bez linii „Sprawdzono …”). */
  compact?: boolean;
}

/**
 * Plakietka KRZ z następnym krokiem: „Sprawdź w KRZ” dla osoby, która wysyła
 * albo potwierdza podpis, „Zdecyduj” dla Delivery Leada przy wpisie.
 */
export function KrzGate({ row, compact }: KrzGateProps) {
  const [checkOpen, setCheckOpen] = React.useState(false);
  const [decideOpen, setDecideOpen] = React.useState(false);
  const state = row.krz;
  if (!state || (!state.required && state.result === null)) return null;
  const pendingDecision = state.result === "entry" && state.decision === null;
  const mayCheckAgain = state.can_record && state.result !== null && !compact;
  const needsCheck = state.can_record && state.result === null;
  const waiting = krzWaitingLine(state);
  const checked = compact ? null : krzCheckedLine(state);

  return (
    <div className="flex flex-col items-start gap-1" data-testid="krz-gate">
      <KrzBadge state={state} />
      {checked ? <span className="text-[11px] text-muted-foreground">{checked}</span> : null}
      {pendingDecision && !state.can_decide && waiting ? (
        <span className="text-[11px] text-muted-foreground">{waiting}</span>
      ) : null}
      {state.decision && state.decision_reason && !compact ? (
        <span className="text-[11px] text-muted-foreground">
          {state.decided_by_name ? `${state.decided_by_name}: ` : ""}
          {state.decision_reason}
        </span>
      ) : null}
      <div className="flex flex-wrap gap-1.5">
        {needsCheck ? (
          <Button size="sm" onClick={() => setCheckOpen(true)}>
            Sprawdź w KRZ
          </Button>
        ) : null}
        {pendingDecision && state.can_decide ? (
          <Button size="sm" onClick={() => setDecideOpen(true)}>
            Zdecyduj o wpisie
          </Button>
        ) : null}
        {mayCheckAgain ? (
          <button
            type="button"
            className="text-[11px] text-muted-foreground underline hover:text-foreground"
            onClick={() => setCheckOpen(true)}
          >
            Sprawdź jeszcze raz
          </button>
        ) : null}
      </div>
      {checkOpen ? (
        <KrzCheckDialog row={row} open={checkOpen} onOpenChange={setCheckOpen} />
      ) : null}
      {decideOpen ? (
        <KrzDecisionDialog row={row} open={decideOpen} onOpenChange={setDecideOpen} />
      ) : null}
    </div>
  );
}
