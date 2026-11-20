"use client";

// Zakładka „Start i sprzęt” kontraktu (wariant A, 20.11.2026): jedna
// checklista zamiast trzech kart. Nagłówek z postępem listy startowej, potem
// „Formalności” (umowa w dokumentach, dokumenty do startu), „Lista startowa”
// (lista wejścia albo — przy wyłączonym module — stara lista onboardingu),
// „Sprzęt u konsultanta” i „Panel konsultanta” jednym wierszem. Każda akcja
// i bramka zostaje w swoim komponencie; ta karta tylko je układa i liczy
// nagłówek z tych samych odczytów (wspólny cache).

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleHelp, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { ContractEquipmentTab } from "@/components/contracts/ContractEquipmentTab";
import { ConsultantPanelCard } from "@/components/hr/onboarding/ConsultantPanelCard";
import { ContractEntryTab } from "@/components/hr/onboarding/ContractEntryTab";
import api from "@/lib/api";
import { useContractEntry } from "@/lib/api/hr-lifecycle";
import { useClientStartDocs, usePairStartDocs } from "@/lib/api/start-documents";
import type { ContractDocument } from "@/lib/contract-document-folders";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { isForbiddenError, isNotFoundError } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import {
  agreementDocument,
  entryProgress,
  legacyProgress,
  ofSteps,
  percentOf,
  startDocsCheck,
  startListSource,
  startSubtitle,
  type CheckState,
  type LegacyItem,
  type StartProgress,
} from "./start-progress";

const CHECK_ICON: Record<CheckState, { icon: LucideIcon; tone: string; label: string }> = {
  ok: { icon: CircleCheck, tone: "text-success", label: "jest" },
  check: { icon: CircleHelp, tone: "text-warning", label: "do sprawdzenia" },
  missing: { icon: CircleAlert, tone: "text-destructive", label: "brak" },
};

function Section({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="space-y-1.5 px-4 py-3">
      <h3 className="flex min-h-8 items-center gap-2 text-[13.5px] font-semibold text-foreground">
        {title}
        {meta ? (
          <>
            {" "}
            <span className="text-[12px] font-normal tabular-nums text-muted-foreground">{meta}</span>
          </>
        ) : null}
      </h3>
      {children}
    </section>
  );
}

function CheckRow({
  state,
  title,
  detail,
  action,
}: {
  state: CheckState;
  title: string;
  detail: ReactNode;
  action?: ReactNode;
}) {
  const { icon: Icon, tone, label } = CHECK_ICON[state];
  return (
    <li className="flex items-start gap-3 py-1">
      <Icon aria-label={label} className={cn("mt-0.5 size-[18px] shrink-0", tone)} />
      <div className="min-w-0 flex-1">
        <p className="flex items-baseline justify-between gap-3 text-[13px] font-medium leading-5 text-foreground">
          {title}
          {action ? <span className="shrink-0 font-normal">{action}</span> : null}
        </p>
        <p className="line-clamp-2 text-[12px] leading-4 text-muted-foreground">{detail}</p>
      </div>
    </li>
  );
}

const LINK = "text-[12.5px] font-medium text-primary hover:underline";

function Formalities({
  clientId,
  candidateId,
  jobId,
  documents,
  canViewDocuments,
  onOpenDocuments,
}: {
  clientId: number;
  candidateId: number | null;
  jobId: number | null;
  documents: ContractDocument[] | undefined;
  canViewDocuments: boolean;
  onOpenDocuments: () => void;
}) {
  const hasPair = candidateId != null && jobId != null;
  const pair = usePairStartDocs(candidateId ?? 0, jobId ?? 0, hasPair);
  // Bez listy u klienta para jest `null` — wtedy liczy się jawna decyzja klienta.
  const clientList = useClientStartDocs(clientId, hasPair && pair.isSuccess && pair.data === null);
  const agreement = agreementDocument(documents);
  // Stan pary widzą role rekrutacji z dostępem, DL klienta, HoR i admin — inni nie dostają wiersza.
  const pairHidden = hasPair && pair.isError && isForbiddenError(pair.error);
  const docs = startDocsCheck({
    hasJob: hasPair,
    pair: pair.data,
    clientList: clientList.data,
    today: warsawToday(),
  });
  const docsLink =
    docs.target === "documents" ? (
      <button type="button" className={LINK} onClick={onOpenDocuments}>
        Dokumenty
      </button>
    ) : (
      <Link href={`/clients/${clientId}?tab=wejscie`} className={LINK}>
        Wejście u klienta
      </Link>
    );
  return (
    <ul className="grid gap-x-8 sm:grid-cols-2">
      {canViewDocuments ? (
        documents == null ? (
          <CheckRow state="check" title="Umowa w dokumentach" detail="Wczytywanie dokumentów…" />
        ) : agreement ? (
          <CheckRow
            state="ok"
            title="Umowa w dokumentach"
            detail={
              <>
                <span title={agreement.filename}>„{agreement.filename}”</span> · dodano{" "}
                {formatIsoDatePl(agreement.created_at)}
              </>
            }
            action={
              <button type="button" className={LINK} onClick={onOpenDocuments}>
                Dokumenty
              </button>
            }
          />
        ) : (
          <CheckRow
            state="missing"
            title="Brak umowy w dokumentach"
            detail="Bez podpisanej umowy w dokumentach nie wiadomo, co obowiązuje."
            action={
              <button type="button" className={LINK} onClick={onOpenDocuments}>
                Dodaj w „Dokumentach”
              </button>
            }
          />
        )
      ) : null}
      {pairHidden ? null : hasPair && pair.isLoading ? (
        <CheckRow state="check" title="Dokumenty do startu" detail="Wczytywanie dokumentów do startu…" />
      ) : hasPair && pair.isError ? (
        <CheckRow state="check" title="Dokumenty do startu" detail="Nie udało się pobrać dokumentów do startu." />
      ) : (
        <CheckRow state={docs.state} title="Dokumenty do startu" detail={docs.detail} action={docsLink} />
      )}
    </ul>
  );
}

interface ContractStartTabProps {
  contractId: number;
  clientId: number;
  candidateId: number | null;
  jobId: number | null;
  startDate: string | null;
  /** Brak edycji kontraktu — stara lista i wpisy sprzętu tylko do odczytu. */
  readOnly: boolean;
  /** Dokumenty kontraktu (ten sam odczyt co zakładka „Dokumenty”). */
  documents: ContractDocument[] | undefined;
  canViewDocuments: boolean;
  onOpenDocuments: () => void;
}

/**
 * „Start i sprzęt” jako checklista. Komentarz dla spisu funkcji: dawne
 * „Wejście” (dawniej „Onboarding”) i „Sprzęt” to sekcje tej karty.
 */
export function ContractStartTab({
  contractId,
  clientId,
  candidateId,
  jobId,
  startDate,
  readOnly,
  documents,
  canViewDocuments,
  onOpenDocuments,
}: ContractStartTabProps) {
  const entry = useContractEntry(contractId);
  const source = startListSource({ notFound: isNotFoundError(entry.error), view: entry.data });
  const legacy = useQuery<LegacyItem[]>({
    queryKey: ["contract-onboarding", contractId],
    queryFn: () => api.get(`/api/contracts/${contractId}/onboarding`).then((r) => r.data),
    enabled: source === "legacy",
  });
  const progress: StartProgress | null =
    source === "entry" && entry.data?.case
      ? entryProgress(entry.data.case.tasks, entry.data.case.started_at)
      : source === "legacy" && legacy.isSuccess
        ? legacyProgress(legacy.data)
        : null;
  const known = source === "entry" ? entry.isSuccess : source === "legacy" ? legacy.isSuccess : false;
  const subtitle = known ? startSubtitle({ startDate, today: warsawToday(), progress }) : null;
  const pct = progress ? percentOf(progress) : 0;
  const listed = progress != null && progress.total > 0;

  return (
    <div className="rounded-xl border border-border bg-card shadow-xs">
      <header
        data-tour="contract.start.progress"
        className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border px-4 py-3.5"
      >
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-foreground">
            Start u klienta
            {listed ? <span className="font-normal text-muted-foreground"> · {ofSteps(progress.done, progress.total)}</span> : null}
          </h2>
          {subtitle ? <p className="text-[12.5px] text-muted-foreground">{subtitle}</p> : null}
        </div>
        {listed ? (
          <div className="flex w-full items-center gap-3 sm:w-[300px]">
            <div
              className="h-2 flex-1 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Postęp listy startowej"
            >
              <div className="h-full rounded-full bg-success transition-all" style={{ width: `${pct}%` }} />
            </div>
            <span className="w-10 text-right text-[12.5px] font-medium tabular-nums text-foreground">{pct} %</span>
          </div>
        ) : null}
      </header>

      <div className="divide-y divide-border/70">
        <Section title="Formalności">
          <Formalities
            clientId={clientId}
            candidateId={candidateId}
            jobId={jobId}
            documents={documents}
            canViewDocuments={canViewDocuments}
            onOpenDocuments={onOpenDocuments}
          />
        </Section>

        <Section title="Lista startowa" meta={source === "entry" ? "ze ścieżki wejścia" : null}>
          {/* Lista wejścia albo — przy wyłączonym module — stara lista onboardingu (decyduje `ContractEntryTab`). */}
          <ContractEntryTab contractId={contractId} readOnly={readOnly} />
        </Section>

        <ContractEquipmentTab
          contractId={contractId}
          readOnly={readOnly}
          clientId={clientId}
          documentNames={(documents ?? []).map((doc) => doc.filename)}
        />

        <ConsultantPanelCard contractId={contractId} />
      </div>
    </div>
  );
}
