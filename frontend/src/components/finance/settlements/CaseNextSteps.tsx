"use client";

// „Co dalej” na karcie rozliczenia (25.11.2026): powód, kto działa, gotowy mail,
// telefon ze skryptem i terminy (dzień 0 mail, +3 przypomnienie, +5 telefon,
// +7 eskalacja do DL/KAM). NEXUS przygotowuje, człowiek wysyła i dzwoni: „Wyślij”
// dopiero po potwierdzeniu w oknie, „Zadzwoniłem” zapisuje wynik. Nic nie
// wychodzi samo (decyzja Artura z 25.11.2026).
import { useState } from "react";
import { Briefcase, Building2, Calculator, Check, Copy, Mail, Phone, UserRound } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  useContractCases,
  useLogCaseCall,
  useSendCaseMail,
  type CallResult,
  type CaseActor,
  type CaseLogEntry,
  type CaseMail,
  type CaseStep,
  type SettlementCase,
} from "@/lib/api/settlement-cases";
import { cn } from "@/lib/utils";

import { STEP_CLASS, nowText, stepWhen } from "./case-format";
import { shortDay } from "./format";

const ACTOR_ICON: Record<CaseActor, typeof UserRound> = {
  consultant: UserRound,
  client: Building2,
  dl: Briefcase,
  finance: Calculator,
};

const CALL_OPTIONS: { value: CallResult; label: string }[] = [
  { value: "reached", label: "Rozmowa" },
  { value: "no_answer", label: "Nie odebrał(a)" },
  { value: "wrong_number", label: "Zły numer" },
];

interface CaseNextStepsProps {
  contractId: number;
  month: string;
  canWrite: boolean;
  /** Stan karty (status, MD, uwagi): zmiana liczy sprawę od nowa. */
  version: string;
}

export function CaseNextSteps({ contractId, month, canWrite, version }: CaseNextStepsProps) {
  const query = useContractCases(contractId, month, version);
  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać „Co dalej” dla tego rozliczenia.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess || query.data.cases.length === 0) return null;
  return (
    <section aria-label="Co dalej" className="rounded-xl border bg-card p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-sm font-semibold">Co dalej</h3>
        <p className="text-[11px] text-muted-foreground">NEXUS przygotował mail, telefon i skrypt. Wysyłasz i dzwonisz Ty, nic nie wychodzi samo.</p>
      </div>
      <div className="divide-y">
        {query.data.cases.map((item) => (
          <CaseBlock key={item.key} item={item} month={month} canWrite={canWrite} />
        ))}
      </div>
    </section>
  );
}

function CaseBlock({ item, month, canWrite }: { item: SettlementCase; month: string; canWrite: boolean }) {
  const Icon = ACTOR_ICON[item.actor];
  const current = item.current;
  return (
    <div className="py-2.5 first:pt-2 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold">
          <Icon aria-hidden className="size-3.5 text-muted-foreground" />
          Kto działa: {item.actor_label}
        </span>
        <span
          className={cn(
            "rounded-md px-2 py-0.5 text-[11px] font-medium",
            current ? STEP_CLASS[current.state] : STEP_CLASS.done,
          )}
        >
          Teraz: {nowText(current, item.overdue_days)}
        </span>
        {item.dl_card ? (
          <span className="text-[11px] text-muted-foreground">
            Karta DL od {shortDay(item.dl_card.created_on)}
            {item.dl_card.mail_sent ? " · mail do DL-a poszedł" : ""}
            {item.dl_card.handled ? " · odhaczona" : ""}
          </span>
        ) : null}
      </div>
      <ul className="mt-1 space-y-0.5 text-[13px]">
        {item.reasons.map((reason) => (
          <li key={`${reason.code}:${reason.title}`}>
            <span className="font-medium">{reason.title}</span>
            {reason.detail ? <span className="text-muted-foreground"> · {reason.detail}</span> : null}
          </li>
        ))}
      </ul>
      <StepStrip steps={item.steps} overdueDays={item.overdue_days} />
      {item.actor === "finance" ? (
        <p className="mt-2 rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-muted-foreground">
          Bez maila i telefonu: Finanse rozstrzygają na tej karcie (przyjmij z uwagami albo odeślij do poprawy).
        </p>
      ) : (
        <>
          <div className="mt-2 grid min-w-0 gap-2 lg:grid-cols-2">
            <MailPanel item={item} month={month} canWrite={canWrite} />
            <CallPanel item={item} month={month} canWrite={canWrite} />
          </div>
          <EscalationRow item={item} month={month} canWrite={canWrite} />
        </>
      )}
      {item.log.length > 0 ? <CaseHistory log={item.log} /> : null}
    </div>
  );
}

function StepStrip({ steps, overdueDays }: { steps: CaseStep[]; overdueDays: number }) {
  return (
    <ol aria-label="Terminy" className="mt-1.5 flex flex-wrap gap-1">
      {steps.map((step) => (
        <li
          key={step.key}
          data-state={step.state}
          className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px]", STEP_CLASS[step.state])}
        >
          {step.state === "done" ? <Check aria-hidden className="size-3" /> : null}
          <span className="font-medium">{step.label}</span>
          <span className="tabular-nums">{stepWhen(step, overdueDays, true)}</span>
        </li>
      ))}
    </ol>
  );
}

function mailAsText(mail: CaseMail): string {
  return [`Do: ${mail.to}`, mail.cc ? `DW: ${mail.cc}` : null, `Temat: ${mail.subject}`, "", mail.text]
    .filter((line) => line !== null)
    .join("\n");
}

function useSendWithConfirm(item: SettlementCase, month: string, escalation: boolean) {
  const send = useSendCaseMail();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  async function run(mail: CaseMail) {
    const ok = await askConfirm({
      title: `Wysłać mail do ${mail.to}?`,
      description: `Temat: „${mail.subject}”.${mail.cc ? ` W kopii: ${mail.cc}.` : ""} Mail wyjdzie z NEXUS-a zaraz po potwierdzeniu.`,
      confirmLabel: "Wyślij",
    });
    if (!ok) return;
    try {
      const result = await send.mutateAsync({
        settlementId: item.settlement_id,
        contractId: item.contract_id,
        month,
        actor: item.actor,
        escalation,
      });
      showSuccess(result.outcome === "simulated" ? "Zapisane jako wysłane (symulacja: nic nie wyszło)." : "Mail wysłany.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać maila."));
    }
  }
  return { run, pending: send.isPending, confirmDialog };
}

function CopyButton({ mail }: { mail: CaseMail }) {
  const { showSuccess, showError } = useToast();
  async function onCopy() {
    if (await copyTextToClipboard(mailAsText(mail))) showSuccess("Skopiowano adres, temat i treść.");
    else showError("Nie udało się skopiować. Zaznacz treść ręcznie.");
  }
  return (
    <Button size="sm" variant="ghost" onClick={onCopy}>
      <Copy aria-hidden className="size-3.5" /> Kopiuj
    </Button>
  );
}

const MAIL_LABEL: Record<NonNullable<SettlementCase["mail_step"]>, string> = {
  mail: "Wyślij mail",
  reminder: "Wyślij przypomnienie",
  extra: "Wyślij jeszcze raz",
};

function MailPanel({ item, month, canWrite }: { item: SettlementCase; month: string; canWrite: boolean }) {
  const { run, pending, confirmDialog } = useSendWithConfirm(item, month, false);
  const [open, setOpen] = useState(false);
  const mail = item.mail;
  const due = item.current && (item.current.key === "mail" || item.current.key === "reminder");
  return (
    <div className="min-w-0 rounded-lg bg-muted/40 p-2">
      {confirmDialog}
      <div className="flex flex-wrap items-center justify-between gap-1">
        <h4 className="inline-flex items-center gap-1.5 text-xs font-semibold">
          <Mail aria-hidden className="size-3.5 text-muted-foreground" /> Mail
        </h4>
        {mail ? (
          <div className="flex gap-1">
            {canWrite ? (
              <Button size="sm" variant={due ? "primary" : "outline"} disabled={pending} onClick={() => run(mail)}>
                {MAIL_LABEL[item.mail_step ?? "mail"]}
              </Button>
            ) : null}
            <CopyButton mail={mail} />
          </div>
        ) : null}
      </div>
      {mail ? (
        <>
          <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 text-xs">
            <dt className="text-muted-foreground">Do</dt>
            <dd className="truncate">
              {item.recipient?.label}
              {item.recipient?.name ? `: ${item.recipient.name}` : ""} · {mail.to}
            </dd>
            {mail.cc ? (
              <>
                <dt className="text-muted-foreground">DW</dt>
                <dd className="truncate">{mail.cc}</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">Temat</dt>
            <dd className="truncate" title={mail.subject}>
              {mail.subject}
            </dd>
          </dl>
          {item.recipient?.why_text ? <p className="mt-0.5 text-[11px] text-muted-foreground">{item.recipient.why_text}</p> : null}
          <button type="button" onClick={() => setOpen((v) => !v)} className="mt-0.5 text-[11px] font-medium text-primary hover:underline">
            {open ? "Zwiń treść" : "Pokaż treść"}
          </button>
          {open ? <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap font-sans text-xs">{mail.text}</pre> : null}
        </>
      ) : (
        <p className="mt-1 text-xs font-medium text-warning-muted-foreground">
          {item.recipient?.why_text ?? "Brak adresata: nie ma adresu ani opiekuna."}
        </p>
      )}
    </div>
  );
}

function CallPanel({ item, month, canWrite }: { item: SettlementCase; month: string; canWrite: boolean }) {
  const call = useLogCaseCall();
  const { showSuccess, showError } = useToast();
  const [form, setForm] = useState(false);
  const [result, setResult] = useState<CallResult>("reached");
  const [note, setNote] = useState("");
  const due = item.current?.key === "call";

  async function onSave() {
    try {
      await call.mutateAsync({
        settlementId: item.settlement_id,
        contractId: item.contract_id,
        month,
        actor: item.actor,
        result,
        note,
      });
      setForm(false);
      setNote("");
      showSuccess("Telefon zapisany w sprawie.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać telefonu."));
    }
  }

  return (
    <div className="min-w-0 rounded-lg bg-muted/40 p-2">
      <div className="flex flex-wrap items-center justify-between gap-1">
        <h4 className="inline-flex items-center gap-1.5 text-xs font-semibold">
          <Phone aria-hidden className="size-3.5 text-muted-foreground" /> Telefon
        </h4>
        {canWrite && !form ? (
          <Button size="sm" variant={due ? "primary" : "outline"} onClick={() => setForm(true)}>
            Zadzwoniłem
          </Button>
        ) : null}
      </div>
      <ul className="mt-1 space-y-0.5 text-xs">
        {item.phones.map((phone) => (
          <li key={`${phone.who}:${phone.name ?? ""}`} className="min-w-0">
            <span className="text-muted-foreground">{phone.who}</span>
            {phone.name ? <span>: {phone.name}</span> : null}
            {" · "}
            {phone.number ? (
              <a href={`tel:${phone.number.replace(/\s+/g, "")}`} className="font-medium tabular-nums text-primary hover:underline">
                {phone.number}
              </a>
            ) : (
              <span className="font-medium text-warning-muted-foreground">brak numeru</span>
            )}
            {phone.source ? <span className="text-muted-foreground"> ({phone.source})</span> : null}
          </li>
        ))}
      </ul>
      {item.script.length > 0 ? (
        <div className="mt-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Skrypt rozmowy</p>
          <ol className="list-decimal space-y-0.5 pl-4 text-xs">
            {item.script.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
        </div>
      ) : null}
      {form ? (
        <div className="mt-2 space-y-1.5 border-t pt-2">
          <div role="radiogroup" aria-label="Wynik rozmowy" className="flex flex-wrap gap-1">
            {CALL_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={result === option.value}
                onClick={() => setResult(option.value)}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs font-medium pointer-coarse:min-h-10",
                  result === option.value ? "border-primary bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <Input
            aria-label="Notatka z rozmowy"
            placeholder="Notatka, np. obiecał poprawkę do piątku"
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="h-8 text-xs"
          />
          <div className="flex gap-1">
            <Button size="sm" disabled={call.isPending} onClick={onSave}>
              Zapisz telefon
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setForm(false)}>
              Anuluj
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EscalationRow({ item, month, canWrite }: { item: SettlementCase; month: string; canWrite: boolean }) {
  const { run, pending, confirmDialog } = useSendWithConfirm(item, month, true);
  const [open, setOpen] = useState(false);
  const to = item.escalation.to;
  const mail = item.escalation.mail;
  const step = item.steps.find((s) => s.key === "escalation");
  if (!to) {
    return <p className="mt-1.5 text-[11px] text-muted-foreground">Eskalacja: brak opiekuna (DL/KAM) innego niż adresat sprawy.</p>;
  }
  return (
    <div className="mt-1.5 text-xs">
      {confirmDialog}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-muted-foreground">
          Eskalacja{step && step.state !== "done" ? ` (termin ${shortDay(step.due)})` : ""}:
        </span>
        <span className="font-medium">{to.name}</span>
        <span className="text-muted-foreground">{to.label}</span>
        {mail ? (
          <>
            {canWrite ? (
              <Button
                size="sm"
                variant={item.current?.key === "escalation" ? "primary" : "outline"}
                disabled={pending}
                onClick={() => run(mail)}
              >
                Wyślij eskalację
              </Button>
            ) : null}
            <button type="button" onClick={() => setOpen((v) => !v)} className="text-[11px] font-medium text-primary hover:underline">
              {open ? "Zwiń treść" : "Pokaż treść"}
            </button>
          </>
        ) : (
          <span className="text-warning-muted-foreground">brak adresu</span>
        )}
      </div>
      {open && mail ? (
        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/40 p-2 font-sans text-xs">{mail.text}</pre>
      ) : null}
    </div>
  );
}

const STEP_NAME: Record<string, string> = {
  mail: "mail",
  reminder: "przypomnienie",
  extra: "mail",
  escalation: "eskalacja",
  call: "telefon",
};

function CaseHistory({ log }: { log: CaseLogEntry[] }) {
  return (
    <div className="mt-1.5 text-[11px] text-muted-foreground">
      <span className="font-semibold uppercase tracking-wide">Historia: </span>
      {log
        .map((entry) => {
          const what =
            entry.action === "call"
              ? `telefon (${entry.result_label ?? "wynik nieznany"})${entry.note ? `: ${entry.note}` : ""}`
              : `${STEP_NAME[entry.step] ?? "mail"} do: ${entry.to ?? "adresata"}${
                  entry.outcome === "simulated" ? " (symulacja)" : entry.outcome === "failed" ? " (nie wyszedł)" : ""
                }`;
          return `${shortDay(entry.on)} ${entry.by ?? ""}: ${what}`;
        })
        .join(" · ")}
    </div>
  );
}
