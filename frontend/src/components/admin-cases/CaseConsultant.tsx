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
  type CaseLinkSuggestion,
} from "@/lib/api/admin-cases";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { httpStatusFromError } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import { ContractPicker } from "./CaseFormDialog";
import { linkButtonLabels } from "./case-format";

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
 * Sekcja „Konsultant” sprawy z kontraktem (panel tablicy i pełny widok, makieta
 * S4 22.10.2026): zdrowie relacji (krąg D11 — inaczej `null`), kto, kontrakt
 * (rola · klient · forma), koniec zamówienia z „przedłużenie w toku”, opiekun
 * z rytmem, ostatnia rozmowa z fragmentem i inne otwarte sprawy („brak
 * otwartych” przy zerze). „Przypisz opiekunowi” = zwykła zmiana osoby sprawy
 * na efektywnego opiekuna. Kartę widzi tylko obsługa Spraw (`can_manage`) —
 * osoba przypisana bez uprawnienia dostaje samą sprawę (serwer: `consultant: null`).
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
  if (!contract || !detail.can_manage) return null;
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
  const place = [consultant?.role, consultant?.client_name ?? contract.client_name, consultant?.form]
    .filter(Boolean)
    .join(" · ");
  // „31.10” w tym roku, pełna data w innym — „10.05” bez roku byłoby zagadką.
  const orderEnd = consultant?.order_end_on
    ? consultant.order_end_on.slice(0, 4) === warsawToday().slice(0, 4)
      ? formatDayMonthPl(consultant.order_end_on)
      : formatIsoDatePl(consultant.order_end_on)
    : "bez końca";
  const owner = [ownerName ?? "nikt", consultant?.cadence_label ? `rytm: ${consultant.cadence_label}` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <section aria-label="Konsultant" className="space-y-2">
      <div className="min-w-0">
        {consultant?.health ? <HealthWord health={consultant.health} className="mb-1" /> : null}
        <p className="truncate font-semibold text-foreground">{name}</p>
      </div>
      {consultant?.health?.reasons.length ? (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
          {consultant.health.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      <div>
        {place ? <Row label="Kontrakt">{place}</Row> : null}
        <Row label="Koniec zamówienia">
          {consultant?.order_extension_pending ? `${orderEnd} · przedłużenie w toku` : orderEnd}
        </Row>
        <Row label="Opiekun">{owner}</Row>
        {consultant ? (
          <Row label="Ostatnia rozmowa">
            {consultant.last_conversation ? (
              <>
                {formatDayMonthPl(consultant.last_conversation.on)}
                {consultant.last_conversation.excerpt ? (
                  <span className="line-clamp-3 font-normal text-muted-foreground">
                    „{consultant.last_conversation.excerpt}”
                  </span>
                ) : null}
              </>
            ) : (
              "jeszcze nie było"
            )}
          </Row>
        ) : null}
        {consultant ? (
          <Row label="Inne sprawy">
            {consultant.other_open_cases > 0
              ? countPl(consultant.other_open_cases, "otwarta", "otwarte", "otwartych")
              : "brak otwartych"}
          </Row>
        ) : null}
      </div>
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

/** Zdanie „skąd wiemy” nad przyciskami (makieta S4): nadawca i nazwisko z treści. */
function SuggestionSentence({ item }: { item: CaseLinkSuggestion }) {
  const name = item.candidate_name ?? `kontrakt #${item.contract_id}`;
  const only = item.only_match ? " — jedyny nasz konsultant o tym nazwisku u tego klienta" : "";
  if (item.sender_kind === "client_contact") {
    return (
      <p className="text-sm text-foreground">
        Nadawca to kontakt klienta{" "}
        <strong className="font-semibold">{item.client_name ?? "klienta"}</strong>
        {item.sender_contact_name ? ` (${item.sender_contact_name})` : ""}. W treści:{" "}
        <strong className="font-semibold">{name}</strong>
        {only}.
      </p>
    );
  }
  if (item.sender_kind === "consultant") {
    return (
      <p className="text-sm text-foreground">
        Nadawca to e-mail konsultanta z kontraktu: <strong className="font-semibold">{name}</strong>
        {item.client_name ? ` · ${item.client_name}` : ""}.
      </p>
    );
  }
  return (
    <p className="text-sm text-foreground">
      W treści sprawy: <strong className="font-semibold">{name}</strong>
      {item.client_name ? ` · ${item.client_name}` : ""}
      {only}.
    </p>
  );
}

/**
 * Karta „Kogo dotyczy?” — sprawa bez kontraktu (i bez pracownika). Propozycje
 * liczy serwer (`link_suggestions`, z nadawcą i „jedynym konsultantem o tym
 * nazwisku”); nic nie wiąże się samo — „Powiąż z X” to zmiana sprawy z wersją
 * karty. „Inny konsultant…” szuka kontraktu.
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
  const buttonLabels = linkButtonLabels(suggestions.map((item) => item.candidate_name));
  // Ta sama osoba u dwóch klientów — przycisk mówi też, u którego.
  const repeatedNames = new Set(
    suggestions
      .map((item) => item.candidate_name)
      .filter((name, index, all) => name && all.indexOf(name) !== index),
  );
  return (
    <section
      aria-label="Kogo dotyczy?"
      className="space-y-2 rounded-lg border border-warning/30 bg-warning-muted/40 px-3 py-2.5"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <UserSearch className="h-4 w-4 shrink-0 text-warning-muted-foreground" aria-hidden />
        <span className="font-semibold text-foreground">Kogo dotyczy?</span>
        {suggestions.length ? null : (
          <span className="text-xs text-muted-foreground">Sprawa nie jest spięta z konsultantem.</span>
        )}
      </div>
      {suggestions.map((item) => (
        <SuggestionSentence key={item.contract_id} item={item} />
      ))}
      <div className="flex flex-wrap items-center gap-2">
        {suggestions.map((item, index) => (
          <Button
            key={item.contract_id}
            size="sm"
            variant={index === 0 ? "primary" : "outline"}
            disabled={patch.isPending}
            title={item.reason ?? undefined}
            onClick={() =>
              link(
                item.contract_id,
                label({ id: item.contract_id, candidate_name: item.candidate_name, client_name: item.client_name }),
              )
            }
          >
            {buttonLabels[index]}
            {item.client_name && item.candidate_name && repeatedNames.has(item.candidate_name) ? (
              <span className="font-normal opacity-80"> · {item.client_name}</span>
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
      {picking ? (
        <ContractPicker value={null} onChange={(next) => (next ? link(next.id, label(next)) : null)} />
      ) : null}
    </section>
  );
}
