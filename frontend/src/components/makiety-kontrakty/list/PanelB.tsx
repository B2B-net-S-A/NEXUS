"use client";
// B · Panel jako mini-karta z zakładkami (Przegląd · Dokumenty · Historia):
// fakty w dwóch kolumnach etykieta–wartość, status jako przycisk z menu
// w nagłówku, w stopce tylko „Otwórz kontrakt” i „Więcej”.
import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ExternalLink, FileText, MoreHorizontal } from "lucide-react";
import { DetailFacts, DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { humanizeActivity } from "../shared/activity";
import { useMkActivities, useMkCareCard, useMkContract, useMkDocuments } from "../shared/data";
import {
  CONTRACT_STATUS_LABEL,
  fmtDate,
  fmtNum,
  fmtPhone,
  fmtPln,
  marginPct,
  relDays,
  terminationReasonLabel,
} from "../shared/format";
import { statusTone } from "../shell/ShellA";
import { buildHappening } from "../shell/WhatsHappening";

export function PanelB({ contractId, onClose }: { contractId: number; onClose: () => void }) {
  const [tab, setTab] = useState("overview");
  const c = useMkContract(contractId).data;
  const care = useMkCareCard(contractId).data;
  const docs = useMkDocuments(contractId).data ?? [];
  const acts = (useMkActivities(contractId).data ?? []).map(humanizeActivity);
  if (!c) return null;
  const happening = buildHappening(c, care);
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
  const monthly = c.monthly_margin ?? (c.margin != null ? c.margin * (c.billing_hours_per_month ?? 168) : null);
  const end = c.terminated_at ?? c.end_date;

  return (
    <DetailPanel
      title={c.candidate_name}
      badges={
        <button type="button" className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs font-medium text-foreground hover:bg-muted">
          <span aria-hidden className={cn("size-1.5 rounded-full", statusTone(c.status))} />
          {CONTRACT_STATUS_LABEL[c.status] ?? c.status}
          <ChevronDown className="size-3 text-muted-foreground" aria-hidden />
        </button>
      }
      subtitle={<span>{c.client_name}</span>}
      onClose={onClose}
      tabs={[
        { value: "overview", label: "Przegląd" },
        { value: "docs", label: "Dokumenty", count: docs.length },
        { value: "history", label: "Historia", count: acts.length },
      ]}
      tab={tab}
      onTabChange={setTab}
      footer={
        <>
          <Button type="button" size="sm" variant="primary" asChild>
            <Link href={`/contracts/${c.id}/makieta?w=b`}>
              Otwórz kontrakt
              <ExternalLink className="ml-1.5 size-3.5" aria-hidden />
            </Link>
          </Button>
          <Button type="button" size="sm" variant="ghost" className="ml-auto">
            <MoreHorizontal className="mr-1.5 size-4" aria-hidden />
            Więcej
          </Button>
        </>
      }
    >
      {tab === "overview" ? (
        <>
          {happening.length ? (
            <ul className="space-y-1">
              {happening.map((h) => (
                <li
                  key={h.id}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-[12.5px] leading-4",
                    h.tone === "danger" ? "bg-destructive/8" : h.tone === "warning" ? "bg-warning/10" : "bg-info/10",
                  )}
                >
                  <span className="font-semibold text-foreground">{h.lead}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="grid grid-cols-3 gap-2 rounded-lg bg-muted/50 p-2.5">
            <div>
              <p className="text-[11px] text-muted-foreground">Klient · zł/h</p>
              <p className="text-[15px] font-semibold tabular-nums">{fmtNum(c.rate_client)}</p>
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">Konsultant</p>
              <p className="text-[15px] font-semibold tabular-nums">{fmtNum(c.rate_candidate)}</p>
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">Marża · {marginPct(c.rate_client, c.rate_candidate, c.rate_client_currency, c.rate_candidate_currency)}</p>
              <p className="text-[15px] font-semibold tabular-nums text-success">{fmtNum(c.margin)}</p>
            </div>
          </div>
          <DetailSection title="Umowa">
            <DetailFacts
              items={[
                ["Okres umowy", `${fmtDate(c.start_date)} – ${c.end_date ? fmtDate(c.end_date) : "bezterminowo"}`],
                ["Zamówienie", orderEnd ? `do ${fmtDate(orderEnd)} (${relDays(orderEnd)})` : "brak"],
                c.status === "ending" ? ["Koniec współpracy", `${fmtDate(end)} · ${terminationReasonLabel(c.termination_reason)?.toLowerCase() ?? ""}`] : null,
                c.status === "ending" ? ["Umowa B2B", c.agreement_termination_mode ? "rozwiązana" : "nierozwiązana"] : null,
                ["Marża / mies.", `≈ ${fmtPln(monthly)}`],
                ["Line manager", c.line_manager ?? "—"],
              ]}
            />
          </DetailSection>
          <DetailSection title="Kontakt">
            <DetailFacts
              items={[
                ["E-mail", c.candidate_email_effective ?? "—"],
                ["Telefon", fmtPhone(c.candidate_phone_effective)],
              ]}
            />
          </DetailSection>
        </>
      ) : null}
      {tab === "docs" ? (
        <ul className="space-y-1.5">
          {docs.map((d) => (
            <li key={d.id} className="flex items-center gap-2 text-[13px]">
              <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate text-primary">{d.filename}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {tab === "history" ? (
        <ol className="space-y-1.5">
          {acts.slice(0, 12).map((a) => (
            <li key={a.id} className={cn("grid grid-cols-[74px_minmax(0,1fr)] gap-2 text-[12.5px]", a.automatic && "text-muted-foreground")}>
              <span className="tabular-nums text-muted-foreground">{fmtDate(a.at)}</span>
              <span className="truncate">{a.title}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </DetailPanel>
  );
}
