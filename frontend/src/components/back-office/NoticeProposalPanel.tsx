"use client";

// Wypowiedzenia z poczty na karcie sprawy (decyzje Artura 23.11.2026, makiety 2–4):
// co przyszło, jak NEXUS doszedł do kontraktu, daty, które się rozjechały,
// i jeden przycisk, który woła istniejącą trasę, a potem zapisuje decyzję.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Paperclip } from "lucide-react";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDecideNotice,
  useNoticeProposal,
  useRefreshCard,
  type NoticeDetail,
} from "@/lib/api/back-office";
import { cn } from "@/lib/utils";

import { REJECT_LABELS, dayLabel, noticeActions, type NoticeAction } from "./notice-model";

interface NoticeProposalPanelProps {
  noticeId: number;
  cardId: number;
  canAct: boolean;
}

function received(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    weekday: "short",
  });
}

function MailBox({ detail }: { detail: NoticeDetail }) {
  const message = detail.message;
  if (!message) return null;
  return (
    <div className="space-y-1.5 rounded-lg border border-border bg-muted/40 p-2.5 text-[13px]">
      <div className="flex flex-wrap gap-x-3 text-[11.5px] text-muted-foreground">
        <span>od: {message.sender_name ? `${message.sender_name} <${message.sender_email}>` : message.sender_email}</span>
        <span>{received(message.received_at)}</span>
      </div>
      <p className="font-medium">{message.subject || "(bez tematu)"}</p>
      {message.excerpt ? (
        <p className="line-clamp-6 whitespace-pre-line text-muted-foreground">{message.excerpt}</p>
      ) : null}
      {message.attachments.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {message.attachments.map((name) => (
            <li
              key={name}
              className="inline-flex max-w-full items-center gap-1 truncate rounded-md border border-border bg-card px-1.5 text-[11.5px]"
            >
              <Paperclip aria-hidden className="size-3 shrink-0" />
              <span className="truncate">{name}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,40%)_minmax(0,1fr)] gap-2 text-[13px]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

export function NoticeProposalPanel({ noticeId, cardId, canAct }: NoticeProposalPanelProps) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useNoticeProposal(noticeId);
  const decide = useDecideNotice();
  const refresh = useRefreshCard();
  const detail = query.data;
  const [lastDay, setLastDay] = useState<string | null>(null);
  const [contractId, setContractId] = useState<number | null>(null);
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);

  // Raz na propozycję (komponent ma `key` = id propozycji): odświeżenie danych
  // po powrocie do okna nie nadpisuje wyboru człowieka.
  const [initialized, setInitialized] = useState(false);
  useEffect(() => {
    if (!detail || initialized) return;
    setLastDay(detail.proposed_last_day);
    setContractId(detail.contract?.id ?? null);
    setRemember(detail.can_remember_sender && !detail.sender_known);
    setInitialized(true);
  }, [detail, initialized]);

  const chosen = useMemo<NoticeDetail | undefined>(() => {
    if (!detail) return undefined;
    if (detail.contract || contractId == null) return detail;
    const picked = detail.alternatives.find((row) => row.id === contractId) ?? null;
    return { ...detail, contract: picked };
  }, [detail, contractId]);

  if (query.isError) {
    return (
      <p className="text-sm text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać propozycji z maila.")}
      </p>
    );
  }
  if (!detail || !chosen) {
    return <p className="text-sm text-muted-foreground">Wczytuję propozycję z maila…</p>;
  }

  const actions = noticeActions(chosen, lastDay);
  const pending = detail.status === "pending";

  const finish = async (decision: "confirmed" | "rejected", action?: NoticeAction) => {
    await decide.mutateAsync({
      id: detail.id,
      decision,
      contract_id: chosen.contract?.id ?? null,
      remember_sender: decision === "confirmed" && remember,
      applied: action?.applied ?? {},
    });
    await refresh.mutateAsync({ id: cardId });
  };

  const run = async (action: NoticeAction) => {
    if (action.request?.url.endsWith("/terminate")) {
      const ok = await askConfirm({
        title: action.label,
        description: `Kontrakt #${chosen.contract?.id} przejdzie na „Kończący się” z ostatnim dniem ${dayLabel(lastDay)}.`,
        confirmLabel: "Potwierdź",
        cancelLabel: "Wróć",
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      if (action.request) {
        await api.request({ method: action.request.method, url: action.request.url, data: action.request.body });
      }
      await finish("confirmed", action);
      showToast("Zapisane. Sprawa z maila zamknięta z notatką.", "success");
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zapisać. Sprawdź kontrakt i spróbuj ponownie."), "error");
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    setBusy(true);
    try {
      await finish("rejected");
      showToast("Odrzucone. Sprawa zostaje jako zwykła sprawa.", "success");
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zapisać decyzji."), "error");
    } finally {
      setBusy(false);
    }
  };

  const differs = detail.dates.some((row) => row.differs);

  return (
    <section aria-label="Propozycja z maila" className="space-y-3 rounded-lg border border-primary/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{detail.label} z maila</h3>
        <span className="text-[11px] text-muted-foreground">
          {pending ? "do potwierdzenia" : detail.status === "confirmed" ? "potwierdzone" : "rozstrzygnięte"}
        </span>
      </div>

      <MailBox detail={detail} />

      <dl className="space-y-1.5">
        <Row label="Rozpoznane po">{detail.evidence.join(", ") || "—"}</Row>
        <Row label="Kontrakt">
          {chosen.contract ? (
            <Link href={`/contracts/${chosen.contract.id}`} className="inline-flex items-center gap-1 hover:underline">
              #{chosen.contract.id} {chosen.contract.person ?? ""} · {chosen.contract.client ?? ""}
              <ArrowUpRight aria-hidden className="size-3" />
            </Link>
          ) : detail.alternatives.length > 0 ? (
            <span className="text-warning-muted-foreground">wybierz niżej, kogo dotyczy</span>
          ) : (
            <span className="text-destructive">nie znaleziono — przypnij kontrakt w sprawie</span>
          )}
          {detail.reasons.length > 0 ? (
            <span className="block text-[11.5px] text-muted-foreground">
              {detail.reasons.map((reason) => reason.label).join(", ")}
            </span>
          ) : null}
        </Row>
        {detail.kind === "consultant_notice" ? (
          <>
            <Row label="Doręczone">{dayLabel(detail.delivered_on)}</Row>
            <Row label="Okres">
              {detail.agreement
                ? "porozumienie — ostatni dzień z dokumentu"
                : detail.period_source === "template"
                  ? "z wzoru umowy kontraktu"
                  : "wzór 2026 (1 miesiąc na koniec miesiąca) — sprawdź w umowie"}
            </Row>
          </>
        ) : null}
        {detail.kind === "client_termination" && detail.client_reason ? (
          <Row label="Powód u klienta">{detail.client_reason}</Row>
        ) : null}
      </dl>

      {!detail.contract && detail.alternatives.length > 0 ? (
        <fieldset className="space-y-1">
          <legend className="text-[12px] text-muted-foreground">Kogo dotyczy mail?</legend>
          {detail.alternatives.map((row) => (
            <label key={row.id} className="flex items-center gap-2 text-[13px]">
              <input
                type="radio"
                name={`notice-contract-${detail.id}`}
                checked={contractId === row.id}
                onChange={() => setContractId(row.id)}
              />
              #{row.id} {row.person} · {row.client} ({row.status})
            </label>
          ))}
        </fieldset>
      ) : null}

      {detail.dates.length > 0 ? (
        <div>
          <p className="mb-1 text-[12px] font-medium">
            {differs ? "Daty, które się nie zgadzają" : "Daty"}
          </p>
          <table className="w-full text-[12.5px]">
            <tbody>
              {detail.dates.map((row) => (
                <tr key={row.key} className={cn("border-b border-border last:border-0", row.differs && "bg-destructive/5")}>
                  <td className="py-1 pr-2">{row.label}</td>
                  <td className="py-1 text-right font-medium tabular-nums">{dayLabel(row.date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {detail.thread.length > 1 ? (
        <div>
          <p className="mb-1 text-[12px] font-medium">Poczta w tej sprawie</p>
          <ol className="space-y-1 text-[12.5px]">
            {detail.thread.map((row) => (
              <li key={row.id} className={cn(row.id === detail.id && "font-medium")}>
                <span className="tabular-nums text-muted-foreground">{received(row.received_at)}</span> · {row.label}
                {row.proposed_last_day ? ` → ${dayLabel(row.proposed_last_day)}` : ""}
                <span className="text-muted-foreground"> ({row.status === "pending" ? "czeka" : row.status === "confirmed" ? "potwierdzone" : row.status === "superseded" ? "zastąpione" : "odrzucone"})</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {pending && canAct ? (
        <div className="space-y-2 border-t border-border pt-2">
          {detail.kind === "consultant_notice" && !detail.agreement ? (
            <fieldset className="space-y-1">
              <legend className="text-[12px] text-muted-foreground">Ostatni dzień umowy</legend>
              {[detail.proposed_last_day, detail.alternative_last_day].filter(Boolean).map((value, index) => (
                <label key={value} className="flex items-center gap-2 text-[13px]">
                  <input
                    type="radio"
                    name={`notice-day-${detail.id}`}
                    checked={lastDay === value}
                    onChange={() => setLastDay(value)}
                  />
                  {dayLabel(value)}
                  <span className="text-muted-foreground">
                    {index === 0 ? "doręczenie w dniu maila" : "doręczenie od następnego dnia roboczego"}
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}
          {detail.kind === "consultant_notice" || detail.kind === "date_change" ? (
            <label className="flex items-center gap-2 text-[13px]">
              <span className="text-muted-foreground">Inna data:</span>
              <Input
                type="date"
                className="h-8 w-40"
                value={lastDay ?? ""}
                onChange={(event) => setLastDay(event.target.value || null)}
              />
            </label>
          ) : null}
          {detail.message?.sender_email && detail.can_remember_sender && !detail.sender_known && chosen.contract ? (
            <label className="flex items-center gap-2 text-[12.5px]">
              <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
              Zapamiętaj {detail.message.sender_email} przy tym konsultancie
            </label>
          ) : null}
          {actions.map((action) => (
            <div key={action.choice} className="space-y-1">
              <ul className="list-disc space-y-0.5 pl-4 text-[12px] text-muted-foreground">
                {action.effects.map((effect) => (
                  <li key={effect}>{effect}</li>
                ))}
              </ul>
              <Button
                size="sm"
                variant={action.primary ? "primary" : "outline"}
                disabled={busy || !chosen.contract}
                onClick={() => run(action)}
              >
                {action.label}
              </Button>
            </div>
          ))}
          <Button size="sm" variant="ghost" disabled={busy} onClick={reject}>
            {REJECT_LABELS[detail.kind]}
          </Button>
        </div>
      ) : null}
      {confirmDialog}
    </section>
  );
}
