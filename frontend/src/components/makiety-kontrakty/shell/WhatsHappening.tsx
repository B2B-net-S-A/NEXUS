"use client";
// „Co się dzieje” — jedno miejsce na górze kontraktu, które zbiera to, co dziś
// leży w trzech miejscach: dwa ostrzeżenia w panelu listy, czerwona karta
// zakończenia na dole „Szczegółów” i powody „Uwaga” w 7. zakładce „Opieka”.
import { AlertTriangle, CalendarClock, HeartPulse, CircleDollarSign } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { MkCareCard, MkContract } from "../shared/data";
import {
  daysUntil,
  fmtDate,
  PROLONGATION_LABEL,
  relDays,
  terminationReasonLabel,
} from "../shared/format";

type Tone = "danger" | "warning" | "info";

export interface HappeningAction {
  label: string;
  variant: "outline" | "ghost" | "quiet" | "primary";
}

export interface HappeningItem {
  id: string;
  tone: Tone;
  icon: "end" | "care" | "money";
  lead: string;
  detail?: string;
  actions: HappeningAction[];
}

/** Koniec współpracy zapisany oknem „Zakończ współpracę” (data w przyszłości albo dziś). */
function plannedEnd(c: MkContract): string | null {
  if (c.status === "ending" && (c.terminated_at || c.end_date)) return c.terminated_at ?? c.end_date;
  if (c.terminated_at && (daysUntil(c.terminated_at) ?? -1) >= 0) return c.terminated_at;
  return null;
}

export function buildHappening(c: MkContract, care: MkCareCard | undefined): HappeningItem[] {
  const items: HappeningItem[] = [];
  const end = plannedEnd(c);
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;

  if (end) {
    const reason = terminationReasonLabel(c.termination_reason);
    const agreementOpen = c.contract_type === "b2b" && !c.agreement_termination_mode;
    const detail = [
      reason ? `Powód: ${reason.toLowerCase()}${c.termination_lessons ? ` („${c.termination_lessons}”)` : ""}.` : null,
      agreementOpen
        ? "Umowa B2B nie jest rozwiązana — zostaw ją tylko, jeśli osoba wraca na inny projekt."
        : null,
    ]
      .filter(Boolean)
      .join(" ");
    items.push({
      id: "end",
      tone: (daysUntil(end) ?? 99) <= 14 ? "danger" : "warning",
      icon: "end",
      lead: `Współpraca kończy się ${fmtDate(end)} — ${relDays(end)}`,
      detail,
      actions: [
        ...(agreementOpen ? [{ label: "Zapisz rozwiązanie umowy", variant: "outline" as const }] : []),
        ...(c.can_reverse_termination ? [{ label: "Cofnij zakończenie", variant: "quiet" as const }] : []),
      ],
    });
  } else if (orderEnd && (daysUntil(orderEnd) ?? 999) <= 60 && (daysUntil(orderEnd) ?? -1) >= 0) {
    items.push({
      id: "order-end",
      tone: (daysUntil(orderEnd) ?? 99) <= 14 ? "danger" : "warning",
      icon: "end",
      lead: `Zamówienie kończy się ${fmtDate(orderEnd)} — ${relDays(orderEnd)}`,
      detail: `Kolejnego zamówienia nie ma. Decyzja o przedłużeniu: ${(
        PROLONGATION_LABEL[c.prolongation_status ?? "unknown"] ?? "brak decyzji"
      ).toLowerCase()}.`,
      actions: [
        { label: "Dodaj zamówienie", variant: "outline" },
        { label: "Zakończ współpracę…", variant: "quiet" },
      ],
    });
  }

  if (care?.health && care.health.level !== "ok" && care.health.reasons.length > 0) {
    // Koniec zamówienia już stoi wyżej — nie powtarzamy go w powodach opieki.
    const reasons = care.health.reasons.filter((r) => !/zamówienie kończy/i.test(r) || items.length === 0);
    if (reasons.length > 0) {
      const [first, ...rest] = reasons;
      items.push({
        id: "care",
        tone: "warning",
        icon: "care",
        lead: `Opieka: ${first.charAt(0).toUpperCase()}${first.slice(1)}`,
        detail: [
          rest.length ? rest.map((r) => r.charAt(0).toUpperCase() + r.slice(1)).join(" · ") : null,
          care.owner ? `Opiekun: ${care.owner.name}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
        actions: [{ label: "Zapisz rozmowę", variant: "outline" }],
      });
    }
  }

  if (c.rate_client == null && ["active", "ending"].includes(c.status)) {
    items.push({
      id: "rate",
      tone: "info",
      icon: "money",
      lead: "Brak stawki klienta",
      detail: "Przychód i marża tego kontraktu nie liczą się w sumach, dopóki stawka nie zostanie wpisana.",
      actions: [{ label: "Uzupełnij stawkę", variant: "outline" }],
    });
  }
  return items;
}

const TONE_BAR: Record<Tone, string> = {
  danger: "bg-destructive",
  warning: "bg-warning",
  info: "bg-info",
};
const TONE_ICON: Record<Tone, string> = {
  danger: "text-destructive",
  warning: "text-warning",
  info: "text-info",
};
const ICONS = { end: CalendarClock, care: HeartPulse, money: CircleDollarSign } as const;

/** Wersja A: pas pod nagłówkiem, jeden wiersz na sprawę, akcje po prawej. */
export function WhatsHappeningA({ items }: { items: HappeningItem[] }) {
  if (items.length === 0) return null;
  return (
    <section
      aria-label="Co się dzieje"
      className="overflow-hidden rounded-xl border border-border bg-card shadow-xs"
    >
      <ul className="divide-y divide-border/70">
        {items.map((item) => {
          const Icon = ICONS[item.icon];
          return (
            <li key={item.id} className="relative flex items-center gap-3 py-2.5 pl-4 pr-3">
              <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", TONE_BAR[item.tone])} />
              <Icon aria-hidden className={cn("size-4 shrink-0", TONE_ICON[item.tone])} />
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] font-semibold leading-5 text-foreground">{item.lead}</p>
                {item.detail ? (
                  <p className="text-[12.5px] leading-5 text-muted-foreground">{item.detail}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {item.actions.map((a) => (
                  <Button key={a.label} type="button" size="sm" variant={a.variant}>
                    {a.label}
                  </Button>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Wersja B: zwięzły pas nad zakładkami — jedna linia na sprawę. */
export function WhatsHappeningB({ items }: { items: HappeningItem[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-label="Co się dzieje" className="space-y-1.5">
      {items.map((item) => (
        <div
          key={item.id}
          className={cn(
            "flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12.5px]",
            item.tone === "danger" && "bg-destructive/8 text-foreground",
            item.tone === "warning" && "bg-warning/10 text-foreground",
            item.tone === "info" && "bg-info/10 text-foreground",
          )}
        >
          <AlertTriangle aria-hidden className={cn("size-3.5 shrink-0", TONE_ICON[item.tone])} />
          <span className="min-w-0 flex-1 truncate" title={item.detail}>
            <span className="font-semibold">{item.lead}</span>
            {item.detail ? <span className="text-muted-foreground"> · {item.detail}</span> : null}
          </span>
          {item.actions[0] ? (
            <button type="button" className="shrink-0 font-medium text-primary hover:underline">
              {item.actions[0].label}
            </button>
          ) : null}
        </div>
      ))}
    </section>
  );
}
