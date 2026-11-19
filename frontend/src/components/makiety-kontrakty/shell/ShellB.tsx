"use client";
// Kierunek B — strona kontraktu jako „karta umowy” po lewej (zawsze na widoku,
// zastępuje zakładkę „Szczegóły”, kartę „Szczegóły administracyjne” i
// „Historię stawek”) i praca w zakładkach po prawej.
import Link from "next/link";
import { ArrowLeft, ChevronDown, ChevronRight, Mail, MoreHorizontal, Pencil, Phone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useMkAmendments, useMkCareCard, useMkContract, useMkDocuments, type MkContract, type MkRateStep } from "../shared/data";
import {
  CONTRACT_STATUS_LABEL,
  CONTRACT_TYPE_LABEL,
  fmtDate,
  curUnit,
  fmtNum,
  fmtPhone,
  fmtPln,
  marginPct,
  relDays,
} from "../shared/format";
import { buildHappening, WhatsHappeningB } from "./WhatsHappening";
import { statusTone } from "./ShellA";

export const TABS_B = [
  { key: "aktywnosc", label: "Aktywność" },
  { key: "dokumenty", label: "Dokumenty" },
  { key: "aneksy", label: "Aneksy" },
  { key: "opieka", label: "Opieka" },
  { key: "wejscie", label: "Wejście" },
  { key: "sprzet", label: "Sprzęt" },
  { key: "faktury", label: "Faktury" },
] as const;

export type TabKeyB = (typeof TABS_B)[number]["key"];

function CardSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1.5 border-t border-border/70 pt-3">
      <h2 className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-2 text-[13px] leading-5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

/** Kroki harmonogramu bez wpisów zastąpionych krokiem z tą samą datą. */
function liveSteps(steps: MkRateStep[] | undefined): MkRateStep[] {
  const byDate = new Map<string, MkRateStep>();
  for (const s of steps ?? []) byDate.set(s.effective_from ?? "", s);
  return [...byDate.values()].sort((a, b) => (a.effective_from ?? "").localeCompare(b.effective_from ?? ""));
}

function RateChanges({ c }: { c: MkContract }) {
  const client = liveSteps(c.client_rate_schedule);
  const cand = liveSteps(c.candidate_rate_schedule);
  const dates = [...new Set([...client, ...cand].map((s) => s.effective_from ?? ""))].sort().reverse();
  if (dates.length === 0) return <p className="text-[12.5px] text-muted-foreground">Stawki bez zmian od startu.</p>;
  return (
    <ol className="space-y-1">
      {dates.map((d) => {
        const cl = client.find((s) => s.effective_from === d);
        const ca = cand.find((s) => s.effective_from === d);
        return (
          <li key={d} className="grid grid-cols-[76px_minmax(0,1fr)] gap-2 text-[12.5px] leading-5">
            <span className="tabular-nums text-muted-foreground">od {fmtDate(d)}</span>
            <span className="tabular-nums text-foreground">
              {cl ? `klient ${fmtNum(cl.rate)}` : null}
              {cl && ca ? " · " : null}
              {ca ? `kandydat ${fmtNum(ca.rate)}` : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function ShellB({
  contractId,
  tab,
  expandRates = false,
  children,
}: {
  contractId: number;
  tab: TabKeyB;
  expandRates?: boolean;
  children: React.ReactNode;
}) {
  const { data: c, isLoading, isError } = useMkContract(contractId);
  const care = useMkCareCard(contractId).data;
  const docs = useMkDocuments(contractId).data;
  const amendments = useMkAmendments(contractId).data;
  // Sprzęt żyje w rejestrze „Sprzęt” (`/api/equipment/contracts/{id}`), nie w starej `contract_equipment`.
  const equipment = useQuery<{ active?: unknown[] }>({
    queryKey: ["mk-equipment-registry-count", contractId],
    queryFn: () => api.get<{ active?: unknown[] }>(`/api/equipment/contracts/${contractId}`).then((r) => r.data),
    enabled: Number.isFinite(contractId),
  }).data?.active;

  if (isLoading) return <p className="text-sm text-muted-foreground">Ładowanie kontraktu…</p>;
  if (isError || !c) return <p className="text-sm text-destructive">Nie udało się pobrać kontraktu.</p>;

  const happening = buildHappening(c, care);
  const counts: Partial<Record<TabKeyB, number | undefined>> = {
    dokumenty: docs?.length,
    aneksy: amendments?.length,
    sprzet: equipment?.length,
  };
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
  const steps = new Set([...liveSteps(c.client_rate_schedule), ...liveSteps(c.candidate_rate_schedule)].map((s) => s.effective_from)).size;
  const monthlyMargin = c.monthly_margin ?? (c.margin != null && c.billing_hours_per_month ? c.margin * c.billing_hours_per_month : null);

  return (
    <div className="space-y-3">
      <Link
        href="/contracts?status=active&status=ending"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Kontrakty
      </Link>
      <div className="grid grid-cols-[288px_minmax(0,1fr)] items-start gap-5">
        <aside className="sticky top-0 space-y-3 rounded-xl border border-border bg-card p-4 shadow-xs">
          <div className="space-y-1">
            <div className="flex items-start justify-between gap-2">
              <h1 className="text-[19px] font-semibold leading-6 tracking-tight text-foreground">{c.candidate_name}</h1>
              <Button type="button" variant="ghost" size="icon" className="-mr-2 -mt-1 size-8" aria-label="Więcej akcji">
                <MoreHorizontal className="size-4" aria-hidden />
              </Button>
            </div>
            {c.job_title ? (
              <p className="line-clamp-2 text-[12.5px] leading-4 text-muted-foreground" title={c.job_title}>
                {c.job_title}
              </p>
            ) : null}
            <button
              type="button"
              className="mt-1 inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs font-medium text-foreground hover:bg-muted"
            >
              <span aria-hidden className={cn("size-1.5 rounded-full", statusTone(c.status))} />
              {CONTRACT_STATUS_LABEL[c.status] ?? c.status}
              <ChevronDown className="size-3 text-muted-foreground" aria-hidden />
            </button>
          </div>

          <CardSection title="Klient">
            <dl className="space-y-1">
              <Row label="Firma">
                <Link href={`/clients/${c.client_id}`} className="font-medium text-primary hover:underline">
                  {c.client_name}
                </Link>
              </Row>
              <Row label="Line manager">{c.line_manager ?? <span className="text-muted-foreground/60">—</span>}</Row>
            </dl>
          </CardSection>

          <CardSection title="Okres">
            <dl className="space-y-1">
              <Row label="Umowa">
                <span className="tabular-nums">
                  {fmtDate(c.start_date)} → {c.end_date ? fmtDate(c.end_date) : <em className="not-italic text-muted-foreground">bezterminowo</em>}
                </span>
              </Row>
              <Row label="Zamówienie">
                <span className="tabular-nums">
                  {c.client_order_start_date ? `${fmtDate(c.client_order_start_date)} → ` : ""}
                  {fmtDate(orderEnd)}
                </span>
                {orderEnd ? <span className="block text-[11.5px] text-muted-foreground">{relDays(orderEnd)}</span> : null}
              </Row>
            </dl>
          </CardSection>

          <CardSection title="Stawki · zł/h">
            <div className="grid grid-cols-3 gap-2">
              <div>
                <p className="text-[11px] text-muted-foreground">Klient</p>
                <p className="text-[15px] font-semibold tabular-nums">
                  {fmtNum(c.rate_client)}
                  {curUnit(c.rate_client_currency) !== "zł" ? <span className="ml-1 text-[11px] font-normal text-muted-foreground">{curUnit(c.rate_client_currency)}</span> : null}
                </p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">Kandydat</p>
                <p className="text-[15px] font-semibold tabular-nums">{fmtNum(c.rate_candidate)}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">Marża</p>
                <p className="text-[15px] font-semibold tabular-nums text-success">{fmtNum(c.margin)}</p>
              </div>
            </div>
            <p className="text-[12px] text-muted-foreground">
              {curUnit(c.rate_client_currency) !== curUnit(c.rate_candidate_currency)
                ? `Marży nie liczymy: klient płaci w ${curUnit(c.rate_client_currency)}, konsultant dostaje w ${curUnit(c.rate_candidate_currency)}.`
                : `${marginPct(c.rate_client, c.rate_candidate, c.rate_client_currency, c.rate_candidate_currency)} · ≈ ${fmtPln(monthlyMargin)} marży / mies.`}
            </p>
            {expandRates ? (
              <div className="rounded-lg bg-muted/50 p-2">
                <p className="mb-1 text-[11.5px] font-medium text-foreground">Zmiany stawek</p>
                <RateChanges c={c} />
              </div>
            ) : steps >= 2 ? (
              <Link
                href={`/contracts/${c.id}/makieta?w=b&tab=${tab}&stawki=1`}
                className="inline-flex items-center gap-0.5 text-[12.5px] font-medium text-primary hover:underline"
              >
                Zmiany stawek ({steps - 1})
                <ChevronRight className="size-3.5" aria-hidden />
              </Link>
            ) : (
              <p className="text-[12.5px] text-muted-foreground">Stawki bez zmian od startu.</p>
            )}
          </CardSection>

          <CardSection title="Kontakt">
            <p className="flex items-center gap-2 truncate text-[13px]">
              <Mail className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">{c.candidate_email_effective ?? "—"}</span>
            </p>
            <p className="flex items-center gap-2 text-[13px] tabular-nums">
              <Phone className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              {fmtPhone(c.candidate_phone_effective)}
            </p>
          </CardSection>

          <CardSection title="Szczegóły">
            <dl className="space-y-1">
              <Row label="Typ">{CONTRACT_TYPE_LABEL[c.contract_type] ?? c.contract_type}</Row>
              <Row label="Tryb pracy">{c.work_mode ?? <span className="text-muted-foreground/60">—</span>}</Row>
              <Row label="Replacement">
                <span className="text-muted-foreground">nie zapisano</span>
              </Row>
              <Row label="Numer">#{c.id}</Row>
            </dl>
          </CardSection>

          <Button type="button" variant="outline" size="sm" className="w-full">
            <Pencil className="mr-1.5 size-3.5" aria-hidden />
            Edytuj kartę
          </Button>
        </aside>

        <div className="min-w-0 space-y-3">
          <WhatsHappeningB items={happening} />
          <nav aria-label="Sekcje kontraktu" className="flex gap-0.5 overflow-x-auto border-b border-border">
            {TABS_B.map((t) => {
              const active = t.key === tab;
              const count = counts[t.key];
              return (
                <Link
                  key={t.key}
                  href={`/contracts/${c.id}/makieta?w=b&tab=${t.key}`}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-2.5 py-2 text-[13px] transition-colors",
                    active
                      ? "border-primary font-semibold text-foreground"
                      : "border-transparent font-medium text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t.label}
                  {count != null && count > 0 ? (
                    <span className="rounded-full bg-muted px-1.5 text-[11px] tabular-nums text-muted-foreground">{count}</span>
                  ) : null}
                  {t.key === "opieka" && care?.health && care.health.level !== "ok" ? (
                    <span aria-label="wymaga uwagi" className="size-1.5 rounded-full bg-warning" />
                  ) : null}
                </Link>
              );
            })}
          </nav>
          <div>{children}</div>
        </div>
      </div>
    </div>
  );
}
