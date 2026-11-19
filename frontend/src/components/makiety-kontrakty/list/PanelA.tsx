"use client";
// A · Panel podglądu z listy: jedno ostrzeżenie zamiast dwóch o tym samym,
// pieniądze w jednej linii, okres jako dwie linie z „ile zostało”, kontakt
// zwięźle, trzy ostatnie dokumenty i zdarzenia. Stopka: jedna akcja główna
// („Otwórz kontrakt”) i menu — bez natywnej listy statusu obok przycisków.
import Link from "next/link";
import { ChevronDown, ExternalLink, FileText, Mail, MoreHorizontal, Phone } from "lucide-react";
import { DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { humanizeActivity } from "../shared/activity";
import { useMkActivities, useMkCareCard, useMkContract, useMkDocuments } from "../shared/data";
import {
  CONTRACT_STATUS_LABEL,
  CONTRACT_TYPE_LABEL,
  fmtDate,
  fmtNum,
  fmtPhone,
  fmtPln,
  marginPct,
  relDays,
} from "../shared/format";
import { statusTone } from "../shell/ShellA";
import { buildHappening } from "../shell/WhatsHappening";

export function PanelA({ contractId, onClose }: { contractId: number; onClose: () => void }) {
  const c = useMkContract(contractId).data;
  const care = useMkCareCard(contractId).data;
  const docs = useMkDocuments(contractId).data ?? [];
  const acts = (useMkActivities(contractId).data ?? []).map(humanizeActivity).filter((a) => !a.automatic).slice(0, 3);
  if (!c) return null;
  const happening = buildHappening(c, care);
  const first = happening[0];
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
  const monthly = c.monthly_margin ?? (c.margin != null ? c.margin * (c.billing_hours_per_month ?? 168) : null);

  return (
    <DetailPanel
      title={c.candidate_name}
      badges={
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
          <span aria-hidden className={cn("size-1.5 rounded-full", statusTone(c.status))} />
          {CONTRACT_STATUS_LABEL[c.status] ?? c.status}
        </span>
      }
      subtitle={
        <span>
          {c.client_name} · {CONTRACT_TYPE_LABEL[c.contract_type] ?? c.contract_type} · #{c.id}
        </span>
      }
      onClose={onClose}
      footer={
        <>
          <Button type="button" size="sm" variant="primary" asChild>
            <Link href={`/contracts/${c.id}/makieta?w=a`}>
              Otwórz kontrakt
              <ExternalLink className="ml-1.5 size-3.5" aria-hidden />
            </Link>
          </Button>
          <Button type="button" size="sm" variant="outline">
            Dodaj aneks
            <ChevronDown className="ml-1 size-3.5" aria-hidden />
          </Button>
          <Button type="button" size="icon" variant="ghost" className="ml-auto size-8" aria-label="Więcej: zmień status, zamówienie, zakończ współpracę">
            <MoreHorizontal className="size-4" aria-hidden />
          </Button>
        </>
      }
    >
      {first ? (
        <div className={cn("rounded-lg border px-3 py-2.5", first.tone === "danger" ? "border-destructive/30 bg-destructive/5" : "border-warning/40 bg-warning/5")}>
          <p className="text-[13px] font-semibold text-foreground">{first.lead}</p>
          {first.detail ? <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{first.detail}</p> : null}
          {first.actions[0] ? (
            <Button type="button" size="sm" variant="outline" className="mt-2">
              {first.actions[0].label}
            </Button>
          ) : null}
          {happening.length > 1 ? (
            <p className="mt-2 border-t border-border/60 pt-1.5 text-[12px] text-muted-foreground">
              Także: {happening.slice(1).map((h) => h.lead).join(" · ")}
            </p>
          ) : null}
        </div>
      ) : null}

      <DetailSection title="Pieniądze · zł/h">
        <p className="text-[13px] tabular-nums text-foreground">
          <span className="text-muted-foreground">Klient</span> <strong className="font-semibold">{fmtNum(c.rate_client)}</strong>
          <span className="mx-2 text-muted-foreground/50">·</span>
          <span className="text-muted-foreground">Konsultant</span> <strong className="font-semibold">{fmtNum(c.rate_candidate)}</strong>
          <span className="mx-2 text-muted-foreground/50">·</span>
          <span className="text-muted-foreground">Marża</span> <strong className="font-semibold text-success">{fmtNum(c.margin)}</strong>
        </p>
        <p className="text-[12px] text-muted-foreground">
          {marginPct(c.rate_client, c.rate_candidate, c.rate_client_currency, c.rate_candidate_currency)} · ≈ {fmtPln(monthly)} marży miesięcznie
        </p>
      </DetailSection>

      <DetailSection title="Okres">
        <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13px]">
          <dt className="text-muted-foreground">Umowa</dt>
          <dd className="tabular-nums">
            {fmtDate(c.start_date)} – {c.end_date ? fmtDate(c.end_date) : "bezterminowo"}
          </dd>
          <dt className="text-muted-foreground">Zamówienie</dt>
          <dd className="tabular-nums">
            {orderEnd ? (
              <>
                do {fmtDate(orderEnd)} <span className="text-muted-foreground">· {relDays(orderEnd)}</span>
              </>
            ) : (
              "brak"
            )}
          </dd>
          <dt className="text-muted-foreground">Line manager</dt>
          <dd>{c.line_manager ?? "—"}</dd>
        </dl>
      </DetailSection>

      <DetailSection title="Kontakt">
        <p className="flex items-center gap-2 text-[13px]">
          <Mail className="size-3.5 text-muted-foreground" aria-hidden />
          {c.candidate_email_effective ?? "—"}
        </p>
        <p className="flex items-center gap-2 text-[13px] tabular-nums">
          <Phone className="size-3.5 text-muted-foreground" aria-hidden />
          {fmtPhone(c.candidate_phone_effective)}
        </p>
      </DetailSection>

      <DetailSection title={`Dokumenty · ${docs.length}`}>
        <ul className="space-y-1">
          {docs.slice(0, 3).map((d) => (
            <li key={d.id} className="flex items-center gap-2 text-[13px]">
              <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate text-primary" title={d.filename}>
                {d.filename}
              </span>
            </li>
          ))}
        </ul>
      </DetailSection>

      <DetailSection title="Ostatnio">
        <ol className="space-y-1">
          {acts.map((a) => (
            <li key={a.id} className="grid grid-cols-[74px_minmax(0,1fr)] gap-2 text-[12.5px]">
              <span className="tabular-nums text-muted-foreground">{fmtDate(a.at)}</span>
              <span className="truncate text-foreground" title={a.detail}>
                {a.title}
              </span>
            </li>
          ))}
        </ol>
      </DetailSection>
    </DetailPanel>
  );
}
