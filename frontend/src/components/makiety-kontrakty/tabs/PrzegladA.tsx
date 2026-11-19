"use client";
// A · Przegląd — zastępuje „Szczegóły”: okres umowy i zamówienia jako pasek
// z dzisiejszą datą, pieniądze w jednej karcie (bez kroków „nieobowiązujących”),
// porównanie stawki jednym zdaniem, ostatnie zdarzenia i dokumenty po ludzku.
import Link from "next/link";
import { ArrowRight, FileText, Mail, Phone } from "lucide-react";
import { cn } from "@/lib/utils";
import { humanizeActivity } from "../shared/activity";
import {
  useMkActivities,
  useMkBenchmark,
  useMkContract,
  useMkDocuments,
  type MkContract,
  type MkRateStep,
} from "../shared/data";
import {
  CONTRACT_TYPE_LABEL,
  fmtDate,
  fmtNum,
  curUnit,
  fmtPhone,
  fmtPln,
  marginPct,
  personFromEmail,
  relDays,
  today,
} from "../shared/format";
import type { TabProps } from "./types";

const DOC_TYPE: Record<string, string> = { contract: "Umowa", annex: "Aneks", order: "Zamówienie", other: "Inny" };

function Card({ title, action, children, className }: { title: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-xl border border-border bg-card p-4 shadow-xs", className)}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-[13.5px] font-semibold text-foreground">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11.5px] text-muted-foreground">{label}</dt>
      <dd className="line-clamp-2 break-words text-[13px] font-medium text-foreground">{children ?? <span className="font-normal text-muted-foreground/60">—</span>}</dd>
    </div>
  );
}

const ms = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);

/** Pasek okresu: umowa (szara, bezterminowa wygasa w prawo), zamówienie (kolor), dziś (kreska). */
function PeriodBar({ c }: { c: MkContract }) {
  const start = c.start_date ?? today();
  const orderStart = c.client_order_start_date ?? start;
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
  const anchors = [start, today(), orderEnd, c.end_date].filter(Boolean) as string[];
  const lo = ms(start);
  const last = Math.max(...anchors.map(ms));
  const hi = last + (last - lo) * 0.12 + 86_400_000 * 20;
  const pos = (iso: string) => `${(((ms(iso) - lo) / (hi - lo)) * 100).toFixed(2)}%`;
  const width = (a: string, b: string) => `${(((ms(b) - ms(a)) / (hi - lo)) * 100).toFixed(2)}%`;
  const todayPos = pos(today());
  const open = !c.end_date;

  return (
    <div className="space-y-2">
      <div className="relative h-[52px]">
        <div className="absolute inset-x-0 top-1 flex h-5 items-center">
          <span className="w-[92px] shrink-0 text-[11.5px] text-muted-foreground">Umowa</span>
          <div className="relative h-2.5 flex-1">
            <div
              className={cn("absolute inset-y-0 rounded-full bg-muted-foreground/25", open && "rounded-r-none")}
              style={{ left: 0, width: c.end_date ? width(start, c.end_date) : "100%" }}
            />
            {open ? (
              <div className="absolute inset-y-0 right-0 w-16 bg-gradient-to-r from-transparent to-card" />
            ) : null}
          </div>
        </div>
        <div className="absolute inset-x-0 top-7 flex h-5 items-center">
          <span className="w-[92px] shrink-0 text-[11.5px] text-muted-foreground">Zamówienie</span>
          <div className="relative h-2.5 flex-1">
            {orderEnd ? (
              <div
                className="absolute inset-y-0 rounded-full bg-primary/45"
                style={{ left: pos(orderStart), width: width(orderStart, orderEnd) }}
              />
            ) : null}
          </div>
        </div>
        <div className="pointer-events-none absolute inset-y-0 left-[92px] right-0">
          <div className="absolute -top-0.5 bottom-0 w-px bg-foreground/70" style={{ left: todayPos }}>
            <span className="absolute -top-3.5 -translate-x-1/2 whitespace-nowrap text-[10.5px] font-medium text-foreground">dziś</span>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3 border-t border-border/60 pt-2 text-[12.5px]">
        <div>
          <p className="text-muted-foreground">Umowa</p>
          <p className="font-medium tabular-nums text-foreground">
            od {fmtDate(c.start_date)} · {open ? "bezterminowa" : `do ${fmtDate(c.end_date)}`}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">Bieżące zamówienie</p>
          <p className="font-medium tabular-nums text-foreground">
            {orderEnd ? `${fmtDate(orderStart)} – ${fmtDate(orderEnd)}` : "brak"}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">Do końca zamówienia</p>
          <p className="font-medium text-foreground">{orderEnd ? relDays(orderEnd) : "—"}</p>
        </div>
      </div>
    </div>
  );
}

function lastChange(c: MkContract): string | null {
  const steps = (list: MkRateStep[] | undefined) => {
    const byDate = new Map<string, MkRateStep>();
    for (const s of list ?? []) byDate.set(s.effective_from ?? "", s);
    return [...byDate.values()].sort((a, b) => (a.effective_from ?? "").localeCompare(b.effective_from ?? ""));
  };
  const cl = steps(c.client_rate_schedule);
  const ca = steps(c.candidate_rate_schedule);
  const parts: string[] = [];
  let date: string | null = null;
  if (cl.length >= 2) {
    const [a, b] = cl.slice(-2);
    parts.push(`klient ${fmtNum(a.rate)} → ${fmtNum(b.rate)}`);
    date = b.effective_from ?? null;
  }
  if (ca.length >= 2) {
    const [a, b] = ca.slice(-2);
    if (a.rate !== b.rate) parts.push(`kandydat ${fmtNum(a.rate)} → ${fmtNum(b.rate)}`);
    date = date ?? b.effective_from ?? null;
  }
  if (parts.length === 0) return null;
  return `od ${fmtDate(date)}: ${parts.join(", ")}`;
}

export function PrzegladA({ contractId }: TabProps) {
  const c = useMkContract(contractId).data;
  const bench = useMkBenchmark(contractId).data as
    | { contract_rate_monthly?: number; internal_median_monthly?: number; internal_sample_size?: number; role_used?: string }
    | undefined;
  const acts = useMkActivities(contractId).data ?? [];
  const docs = useMkDocuments(contractId).data ?? [];
  if (!c) return null;

  const monthlyMargin = c.monthly_margin ?? (c.margin != null && c.billing_hours_per_month ? c.margin * c.billing_hours_per_month : null);
  const change = lastChange(c);
  const benchLine =
    bench?.contract_rate_monthly && bench.internal_median_monthly
      ? (() => {
          const diff = Math.round(((bench.contract_rate_monthly - bench.internal_median_monthly) / bench.internal_median_monthly) * 100);
          const where = diff === 0 ? "równo z naszą medianą" : `${Math.abs(diff)} % ${diff > 0 ? "powyżej" : "poniżej"} naszej mediany`;
          return `Stawka klienta ${fmtPln(bench.contract_rate_monthly)}/mies. — ${where} dla roli ${bench.role_used ?? "—"} (${bench.internal_sample_size} umów).`;
        })()
      : null;
  const recent = acts
    .map(humanizeActivity)
    .filter((a) => !a.automatic)
    .slice(0, 4);
  const latestDocs = [...docs].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4);

  return (
    <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-4">
      <Card title="Umowa i zamówienie">
        <PeriodBar c={c} />
        <dl className="mt-4 grid grid-cols-3 gap-x-4 gap-y-3 border-t border-border/60 pt-3">
          <Fact label="Typ umowy">{CONTRACT_TYPE_LABEL[c.contract_type] ?? c.contract_type}</Fact>
          <Fact label="Tryb pracy">{c.work_mode}</Fact>
          <Fact label="Line manager">{c.line_manager}</Fact>
          <Fact label="PM po stronie klienta">{c.client_pm_contact_name ?? c.client_pm_name}</Fact>
          <Fact label="Replacement">
            <span className="font-normal text-muted-foreground">nie zapisano</span>
          </Fact>
          <Fact label="Wskazany przez klienta">
            <span className="font-normal text-muted-foreground">nie zapisano</span>
          </Fact>
        </dl>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-border/60 pt-3 text-[13px]">
          <span className="inline-flex items-center gap-1.5">
            <Mail className="size-3.5 text-muted-foreground" aria-hidden />
            {c.candidate_email_effective ?? "—"}
          </span>
          <span className="inline-flex items-center gap-1.5 tabular-nums">
            <Phone className="size-3.5 text-muted-foreground" aria-hidden />
            {fmtPhone(c.candidate_phone_effective)}
          </span>
        </div>
      </Card>

      <Card
        title="Pieniądze"
        action={
          <Link href={`/contracts/${c.id}/makieta?w=a&tab=pieniadze`} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline">
            Stawki i faktury <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      >
        <div className="grid grid-cols-3 gap-3">
          <div>
            <p className="text-[11.5px] text-muted-foreground">Klient płaci</p>
            <p className="text-[19px] font-semibold tabular-nums text-foreground">{fmtNum(c.rate_client)}</p>
            <p className="text-[11px] text-muted-foreground">{curUnit(c.rate_client_currency)}/h</p>
          </div>
          <div>
            <p className="text-[11.5px] text-muted-foreground">Konsultant dostaje</p>
            <p className="text-[19px] font-semibold tabular-nums text-foreground">{fmtNum(c.rate_candidate)}</p>
            <p className="text-[11px] text-muted-foreground">{curUnit(c.rate_candidate_currency)}/h</p>
          </div>
          <div>
            <p className="text-[11.5px] text-muted-foreground">Marża</p>
            <p className="text-[19px] font-semibold tabular-nums text-success">{fmtNum(c.margin)}</p>
            <p className="text-[11px] text-muted-foreground">zł/h · {marginPct(c.rate_client, c.rate_candidate, c.rate_client_currency, c.rate_candidate_currency)}</p>
          </div>
        </div>
        <ul className="mt-3 space-y-1.5 border-t border-border/60 pt-3 text-[12.5px] leading-5 text-muted-foreground">
          {curUnit(c.rate_client_currency) !== curUnit(c.rate_candidate_currency) ? (
            <li>
              Marży nie liczymy: klient płaci w {curUnit(c.rate_client_currency)}, konsultant dostaje w {curUnit(c.rate_candidate_currency)}.
            </li>
          ) : (
            <li>
              <span className="font-medium text-foreground">≈ {fmtPln(monthlyMargin)}</span> marży miesięcznie ({c.billing_hours_per_month ?? 168} h)
            </li>
          )}
          {change ? <li>Ostatnia zmiana stawek {change}.</li> : <li>Stawki bez zmian od startu.</li>}
          {c.framework_rate ? <li>Stawka z umowy ramowej: {fmtNum(c.framework_rate)} zł/h.</li> : null}
          {benchLine ? <li>{benchLine}</li> : null}
        </ul>
      </Card>

      <Card
        title="Ostatnio"
        action={
          <Link href={`/contracts/${c.id}/makieta?w=a&tab=historia`} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline">
            Cała historia <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      >
        {recent.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Bez zmian wprowadzonych ręcznie.</p>
        ) : (
          <ol className="space-y-2">
            {recent.map((a) => (
              <li key={a.id} className="grid grid-cols-[78px_minmax(0,1fr)] gap-3 text-[13px] leading-5">
                <span className="tabular-nums text-muted-foreground">{fmtDate(a.at)}</span>
                <span className="min-w-0">
                  <span className="text-foreground">{a.title}</span>
                  <span className="block truncate text-[12px] text-muted-foreground">
                    {[a.detail, a.who].filter(Boolean).join(" · ")}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>

      <Card
        title="Dokumenty"
        action={
          <Link href={`/contracts/${c.id}/makieta?w=a&tab=dokumenty`} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline">
            Wszystkie ({docs.length}) <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        }
      >
        {latestDocs.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Brak dokumentów — dodaj podpisaną umowę.</p>
        ) : (
          <ul className="space-y-2">
            {latestDocs.map((d) => (
              <li key={d.id} className="flex items-start gap-2 text-[13px] leading-5">
                <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-primary" title={d.filename}>
                    {d.filename}
                  </span>
                  <span className="block text-[12px] text-muted-foreground">
                    {DOC_TYPE[d.doc_type ?? ""] ?? "Dokument"} · dodano {fmtDate(d.created_at)} · {personFromEmail(d.uploaded_by_email)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
