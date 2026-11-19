"use client";
// Kierunek A — strona kontraktu: zwarty nagłówek (2 linie), pas „Co się dzieje”,
// 7 zakładek z licznikami zamiast 10. Rzadkie akcje („Przepnij”, „Usuń”,
// „Generuj z szablonu”, „Dodaj kolejny projekt”) w menu „⋯”, status jako
// kropka z menu zamiast natywnej listy.
import Link from "next/link";
import { ArrowLeft, ChevronDown, MoreHorizontal, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useMkAmendments, useMkCareCard, useMkContract, useMkDocuments } from "../shared/data";
import { CONTRACT_STATUS_LABEL, CONTRACT_TYPE_LABEL, fmtDate } from "../shared/format";
import { buildHappening, WhatsHappeningA } from "./WhatsHappening";

export const TABS_A = [
  { key: "przeglad", label: "Przegląd" },
  { key: "pieniadze", label: "Pieniądze" },
  { key: "dokumenty", label: "Dokumenty" },
  { key: "aneksy", label: "Aneksy" },
  { key: "opieka", label: "Opieka i rozmowy" },
  { key: "start", label: "Start i sprzęt" },
  { key: "historia", label: "Historia" },
] as const;

export type TabKeyA = (typeof TABS_A)[number]["key"];

export function statusTone(status: string): string {
  if (status === "active") return "bg-success";
  if (status === "ending") return "bg-warning";
  if (status === "draft" || status === "ready_for_signature") return "bg-info";
  return "bg-muted-foreground/50";
}

export function ShellA({
  contractId,
  tab,
  children,
}: {
  contractId: number;
  tab: TabKeyA;
  children: React.ReactNode;
}) {
  const { data: c, isLoading, isError } = useMkContract(contractId);
  const care = useMkCareCard(contractId).data;
  const docs = useMkDocuments(contractId).data;
  const amendments = useMkAmendments(contractId).data;

  if (isLoading) return <p className="text-sm text-muted-foreground">Ładowanie kontraktu…</p>;
  if (isError || !c) return <p className="text-sm text-destructive">Nie udało się pobrać kontraktu.</p>;

  const happening = buildHappening(c, care);
  const counts: Partial<Record<TabKeyA, number | undefined>> = {
    dokumenty: docs?.length,
    aneksy: amendments?.length,
  };
  const careWatch = care?.health && care.health.level !== "ok";
  const period = c.end_date ? `${fmtDate(c.start_date)} – ${fmtDate(c.end_date)}` : `od ${fmtDate(c.start_date)}, bezterminowo`;

  return (
    <div className="space-y-3.5">
      <header className="space-y-1">
        <Link
          href="/contracts?status=active&status=ending"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Kontrakty
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex min-w-0 items-center gap-3">
            <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">
              {c.candidate_name}
            </h1>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-0.5 text-xs font-medium text-foreground hover:bg-muted"
              title="Zmień status"
            >
              <span aria-hidden className={cn("size-1.5 rounded-full", statusTone(c.status))} />
              {CONTRACT_STATUS_LABEL[c.status] ?? c.status}
              <ChevronDown className="size-3 text-muted-foreground" aria-hidden />
            </button>
          </div>
          <div className="flex items-center gap-1.5">
            <Button type="button" variant="outline" size="sm">
              Dodaj aneks
              <ChevronDown className="ml-1 size-3.5" aria-hidden />
            </Button>
            <Button type="button" variant="outline" size="sm">
              <Pencil className="mr-1.5 size-3.5" aria-hidden />
              Edytuj
            </Button>
            <Button type="button" variant="ghost" size="icon" aria-label="Więcej akcji" title="Generuj z szablonu, Dodaj kolejny projekt, Przepnij na innego klienta, Usuń">
              <MoreHorizontal className="size-4" aria-hidden />
            </Button>
          </div>
        </div>
        <p className="flex flex-wrap items-center gap-x-2 text-[13px] text-muted-foreground">
          <Link href={`/clients/${c.client_id}`} className="font-medium text-primary hover:underline">
            {c.client_name}
          </Link>
          {c.job_title ? (
            <>
              <span aria-hidden>·</span>
              <span className="max-w-[340px] truncate" title={c.job_title}>
                {c.job_title}
              </span>
            </>
          ) : null}
          <span aria-hidden>·</span>
          <span>{CONTRACT_TYPE_LABEL[c.contract_type] ?? c.contract_type}</span>
          <span aria-hidden>·</span>
          <span>{period}</span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">#{c.id}</span>
        </p>
      </header>

      <WhatsHappeningA items={happening} />

      <nav aria-label="Sekcje kontraktu" className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS_A.map((t) => {
          const active = t.key === tab;
          const count = counts[t.key];
          return (
            <Link
              key={t.key}
              href={`/contracts/${c.id}/makieta?w=a&tab=${t.key}`}
              aria-current={active ? "page" : undefined}
              className={cn(
                "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] transition-colors",
                active
                  ? "border-primary font-semibold text-foreground"
                  : "border-transparent font-medium text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
              {count != null ? (
                <span
                  className={cn(
                    "rounded-full px-1.5 text-[11px] tabular-nums",
                    count === 0 ? "text-muted-foreground/60" : "bg-muted text-muted-foreground",
                  )}
                >
                  {count}
                </span>
              ) : null}
              {t.key === "opieka" && careWatch ? (
                <span aria-label="wymaga uwagi" className="size-1.5 rounded-full bg-warning" />
              ) : null}
            </Link>
          );
        })}
      </nav>

      <div>{children}</div>
    </div>
  );
}
