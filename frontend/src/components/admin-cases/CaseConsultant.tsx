"use client";

import { useState } from "react";
import Link from "next/link";
import { ExternalLink, UserCheck, UserSearch } from "lucide-react";

import { HealthWord } from "@/components/work-board/HealthMark";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  usePatchCase,
  type CaseContractRef,
  type CaseDetail,
} from "@/lib/api/admin-cases";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { httpStatusFromError } from "@/lib/view-state";

import { ContractPicker } from "./CaseFormDialog";

/** Komunikat zapisu z wersją karty: 409 = ktoś zmienił sprawę w międzyczasie. */
export function casePatchError(err: unknown, fallback: string): string {
  return httpStatusFromError(err) === 409
    ? "Ktoś zmienił tę sprawę w międzyczasie — odśwież i spróbuj jeszcze raz."
    : apiErrorMessage(err, fallback);
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

/**
 * Sekcja „Konsultant” sprawy z kontraktem (panel tablicy i pełny widok):
 * kto, u kogo, opiekun i rytm, koniec zamówienia, ostatnia rozmowa, zdrowie
 * relacji (krąg D11 — inaczej `null`) i inne otwarte sprawy osoby.
 * „Przypisz opiekunowi” = zwykła zmiana osoby sprawy na efektywnego opiekuna.
 */
export function CaseConsultantSection({
  detail,
  careAccess,
}: {
  detail: CaseDetail;
  careAccess: boolean;
}) {
  const { showToast } = useToast();
  const patch = usePatchCase();
  const consultant = detail.consultant;
  const contract = detail.contract;
  if (!contract) return null;
  const ownerId = consultant?.owner_user_id ?? contract.care_owner_user_id ?? null;
  const ownerName = consultant?.owner_name ?? contract.care_owner_name ?? null;
  const canAssignOwner =
    detail.can_manage && ownerId != null && detail.assignee?.id !== ownerId;
  const assignOwner = () => {
    if (ownerId == null) return;
    patch.mutate(
      {
        id: detail.id,
        patch: { assignee_user_id: ownerId, expected_updated_at: detail.updated_at },
      },
      {
        onSuccess: () => showToast(`Sprawę prowadzi teraz ${ownerName ?? "opiekun"}`, "success"),
        onError: (err) =>
          showToast(casePatchError(err, "Nie udało się przypisać sprawy opiekunowi."), "error"),
      },
    );
  };
  const name = consultant?.candidate_name ?? contract.candidate_name ?? `Kontrakt #${contract.id}`;
  const place = [consultant?.client_name ?? contract.client_name, consultant?.role, consultant?.form]
    .filter(Boolean)
    .join(" · ");
  return (
    <section aria-label="Konsultant" className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold text-foreground">{name}</p>
          {place ? <p className="truncate text-xs text-muted-foreground">{place}</p> : null}
        </div>
        {consultant?.health ? <HealthWord health={consultant.health} className="shrink-0" /> : null}
      </div>
      {consultant?.health?.reasons.length ? (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
          {consultant.health.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      <div>
        <Row label="Opiekun">{ownerName ?? "nikt"}</Row>
        {consultant?.cadence_label ? <Row label="Rytm">{consultant.cadence_label}</Row> : null}
        <Row label="Koniec zamówienia">
          {consultant?.order_end_on ? formatIsoDatePl(consultant.order_end_on) : "bez końca"}
        </Row>
        {consultant ? (
          <Row label="Ostatnia rozmowa">
            {consultant.last_conversation
              ? formatDayMonthPl(consultant.last_conversation.on)
              : "jeszcze nie było"}
          </Row>
        ) : null}
        {consultant && consultant.other_open_cases > 0 ? (
          <Row label="Inne sprawy">
            {countPl(consultant.other_open_cases, "otwarta", "otwarte", "otwartych")}
          </Row>
        ) : null}
      </div>
      {consultant?.last_conversation?.excerpt ? (
        <p className="line-clamp-3 rounded-md bg-muted/60 px-2 py-1 text-xs">
          „{consultant.last_conversation.excerpt}”
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2 pt-1">
        <Button size="sm" variant="outline" asChild>
          {careAccess ? (
            <Link href={`/care?contract=${contract.id}`}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              Otwórz kartę konsultanta
            </Link>
          ) : (
            <Link href={`/contracts/${contract.id}`}>
              <ExternalLink className="h-4 w-4" aria-hidden />
              Otwórz kontrakt
            </Link>
          )}
        </Button>
        {canAssignOwner ? (
          <Button size="sm" variant="outline" onClick={assignOwner} disabled={patch.isPending}>
            <UserCheck className="h-4 w-4" aria-hidden />
            Przypisz opiekunowi
          </Button>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Pasek „Kogo dotyczy?” — sprawa bez kontraktu (i bez pracownika). Propozycje
 * liczy serwer (`link_suggestions`); nic nie wiąże się samo — „Powiąż z X”
 * to zmiana sprawy z wersją karty. „Inny konsultant…” szuka kontraktu.
 */
export function CaseWhoBar({ detail }: { detail: CaseDetail }) {
  const { showToast } = useToast();
  const patch = usePatchCase();
  const [picking, setPicking] = useState(false);
  if (detail.contract || detail.subject_user || !detail.can_manage) return null;
  const suggestions = detail.link_suggestions ?? [];
  const link = (contractId: number, label: string) =>
    patch.mutate(
      {
        id: detail.id,
        patch: { contract_id: contractId, expected_updated_at: detail.updated_at },
      },
      {
        onSuccess: () => {
          showToast(`Sprawa powiązana: ${label}`, "success");
          setPicking(false);
        },
        onError: (err) =>
          showToast(casePatchError(err, "Nie udało się powiązać sprawy."), "error"),
      },
    );
  const label = (item: Pick<CaseContractRef, "candidate_name" | "client_name" | "id">) =>
    [item.candidate_name ?? `Kontrakt #${item.id}`, item.client_name].filter(Boolean).join(" · ");
  return (
    <section
      aria-label="Kogo dotyczy?"
      className="space-y-2 rounded-lg border border-warning/30 bg-warning-muted/40 px-3 py-2.5"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <UserSearch className="h-4 w-4 shrink-0 text-warning-muted-foreground" aria-hidden />
        <span className="font-semibold text-foreground">Kogo dotyczy?</span>
        <span className="text-xs text-muted-foreground">
          {suggestions.length
            ? "Propozycja z maila — powiąż, jeśli to ta osoba."
            : "Sprawa nie jest spięta z konsultantem."}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {suggestions.map((item) => (
          <Button
            key={item.contract_id}
            size="sm"
            variant="outline"
            disabled={patch.isPending}
            title={item.reason ?? undefined}
            onClick={() =>
              link(
                item.contract_id,
                label({ id: item.contract_id, candidate_name: item.candidate_name, client_name: item.client_name }),
              )
            }
          >
            Powiąż z {item.candidate_name ?? `kontraktem #${item.contract_id}`}
            {item.client_name ? (
              <span className="font-normal text-muted-foreground"> · {item.client_name}</span>
            ) : null}
          </Button>
        ))}
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={picking}
          onClick={() => setPicking((value) => !value)}
        >
          Inny konsultant…
        </Button>
      </div>
      {suggestions.some((item) => item.reason) ? (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {suggestions
            .filter((item) => item.reason)
            .map((item) => (
              <li key={item.contract_id}>
                {item.candidate_name}: {item.reason}
              </li>
            ))}
        </ul>
      ) : null}
      {picking ? (
        <ContractPicker value={null} onChange={(next) => (next ? link(next.id, label(next)) : null)} />
      ) : null}
    </section>
  );
}
