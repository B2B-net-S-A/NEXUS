"use client";

/**
 * Zakładka „Pliki i umowy” — jedna strona bez podzakładek: najpierw pliki
 * kandydata (upload bez zmian), potem umowy (aktualne, draft, historia).
 * `?documents=contracts` (np. stary link `?tab=umowa`) przewija do umów.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
} from "lucide-react";

import { contractsApi } from "@/lib/api";
import { ContractTerminationSummary } from "@/components/contracts/ContractTerminationSummary";
import { downloadContractDocument } from "@/lib/contract-documents";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CandidateFilesTab } from "@/components/v2/files/CandidateFilesTab";
import { AutentiEnvelopeCard } from "@/components/v2/contract/AutentiEnvelopeCard";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { CandidateDocumentView } from "@/components/v2/pages/candidate-profile-navigation";
import { formatDate } from "@/lib/utils";
import {
  SectionError,
  SectionHeading,
  SectionLoading,
  formatRate,
} from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- koperta kontraktów jest luźno typowana */

// TipTap/ProseMirror ładowany dopiero, gdy edytor draftu ma się faktycznie
// pokazać (istniejący draft umowy). Statyczny import trzymał całe drzewo
// ProseMirror w chunku trasy `/candidates/[id]` — koszcie KAŻDEGO otwarcia
// profilu. Pilnuje tego `heavy-bundle-boundaries.test.ts`.
const DraftEditor = dynamic(
  () => import("@/components/v2/pages/ContractDraftEditor").then((m) => m.DraftEditor),
  {
    ssr: false,
    loading: () => (
      <Card variant="default" size="md">
        <CardContent className="py-6 text-center text-sm text-muted-foreground">
          Ładowanie edytora…
        </CardContent>
      </Card>
    ),
  },
);

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  active: "Aktywna",
  ending: "Wygasa",
  ended: "Zakończona",
};

export interface FilesContractsTabProps {
  candidateId: number;
  candidateName: string;
  candidatePhone: string | null;
  jdgComplete: boolean;
  focus: CandidateDocumentView;
  /** Otwiera edycję danych do umowy (JDG). Brak = brak prawa zapisu. */
  onFillJdg?: () => void;
}

export function FilesContractsTab({
  candidateId,
  candidateName,
  candidatePhone,
  jdgComplete,
  focus,
  onFillJdg,
}: FilesContractsTabProps) {
  const contractsRef = useRef<HTMLElement | null>(null);
  const contractsQuery = useQuery<{ items?: any[] } | any[]>({
    queryKey: candidateQueryKeys.contracts(candidateId),
    queryFn: () =>
      contractsApi.byCandidate(candidateId).then((r: any) => r.data),
    enabled: candidateId > 0,
  });
  const contracts: any[] = Array.isArray(contractsQuery.data)
    ? contractsQuery.data
    : (contractsQuery.data?.items ?? []);

  useEffect(() => {
    if (focus !== "contracts") return;
    // Po klatce — lista plików nad umowami dorysowuje się i przesuwa układ.
    const timer = window.setTimeout(
      () => contractsRef.current?.scrollIntoView?.({ block: "start" }),
      120,
    );
    return () => window.clearTimeout(timer);
  }, [focus, contractsQuery.isSuccess]);

  return (
    <div className="space-y-6">
      <section id="candidate-files-section" aria-labelledby="candidate-files-heading">
        <SectionHeading id="candidate-files-heading">Pliki</SectionHeading>
        <CandidateFilesTab candidateId={candidateId} />
      </section>

      <section
        ref={contractsRef}
        id="candidate-contracts-section"
        aria-labelledby="candidate-contracts-heading"
        className="scroll-mt-4"
      >
        <SectionHeading id="candidate-contracts-heading">Umowy</SectionHeading>
        {contractsQuery.error ? (
          <SectionError
            title="Nie udało się pobrać umów"
            onRetry={() => contractsQuery.refetch()}
          />
        ) : contractsQuery.isPending ? (
          <SectionLoading label="Ładowanie umów…" />
        ) : (
          <ContractsSection
            candidateName={candidateName}
            candidatePhone={candidatePhone}
            contracts={contracts}
            jdgComplete={jdgComplete}
            onFillJdg={onFillJdg}
          />
        )}
      </section>
    </div>
  );
}

function ContractsSection({
  candidateName,
  candidatePhone,
  contracts,
  jdgComplete,
  onFillJdg,
}: {
  candidateName: string;
  candidatePhone: string | null;
  contracts: any[];
  jdgComplete: boolean;
  onFillJdg?: () => void;
}) {
  const sorted = useMemo(() => {
    const order: Record<string, number> = { active: 0, ending: 1, draft: 2, ended: 3 };
    return [...contracts].sort((a, b) => {
      const so = (order[a.status] ?? 9) - (order[b.status] ?? 9);
      if (so !== 0) return so;
      return (b.start_date ?? "").localeCompare(a.start_date ?? "");
    });
  }, [contracts]);

  // Konsolidacja wieloklientowa: `.filter`, nie `.find` — osoba z dwiema
  // równoległymi umowami (dwóch klientów) ma dwie karty.
  const currentContracts = sorted.filter(
    (c) => c.status === "active" || c.status === "ending",
  );
  const draft = sorted.find((c) => c.status === "draft");
  const history = sorted.filter((c) => c.status === "ended");
  const [historyOpen, setHistoryOpen] = useState(false);

  // Dane JDG trafiają do szablonu umowy — ostrzeżenie ma sens tylko, gdy jest
  // draft do wyrenderowania.
  const jdgWarning =
    !jdgComplete && draft ? (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
        <span className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Brak danych do umowy (nazwa prawna / NIP) — szablon wyrenderuje puste
          pola.
        </span>
        {onFillJdg ? (
          <Button size="sm" variant="outline" onClick={onFillJdg}>
            Uzupełnij dane do umowy
          </Button>
        ) : null}
      </div>
    ) : null;

  if (currentContracts.length === 0 && !draft && history.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Brak umowy z tym kandydatem.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {jdgWarning}

      {currentContracts.length > 0 ? (
        <div className="space-y-3">
          {currentContracts.length > 1 ? (
            <p className="text-sm text-foreground">
              <span className="font-medium">Pracuje u:</span>{" "}
              {currentContracts
                .map((c) => c.client_name ?? `Klient #${c.client_id}`)
                .join(", ")}
            </p>
          ) : null}
          {currentContracts.map((c) => (
            <CurrentContractCard
              key={c.id}
              contract={c}
              candidateName={candidateName}
              candidatePhone={candidatePhone}
            />
          ))}
        </div>
      ) : null}

      {draft ? (
        <div>
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Draft umowy do edycji
          </p>
          <DraftEditor
            contractId={draft.id}
            candidateName={candidateName}
            contractMeta={draft}
          />
        </div>
      ) : null}

      {history.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => setHistoryOpen((v) => !v)}
            aria-expanded={historyOpen}
            className="flex min-h-9 items-center gap-1 text-xs font-medium text-muted-foreground hover:text-primary"
          >
            {historyOpen ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            Historia umów ({history.length})
          </button>
          {historyOpen ? (
            <div className="mt-2 space-y-2">
              {history.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-sm"
                >
                  <div>
                    <div className="font-medium">
                      {c.client_name ?? `Klient #${c.client_id}`}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {formatDate(c.start_date)} —{" "}
                      {c.end_date ? formatDate(c.end_date) : "?"} ·{" "}
                      {c.contract_type?.toUpperCase()}
                    </div>
                    {c.agreement_termination_mode ? (
                      <ContractTerminationSummary contract={c} compact />
                    ) : null}
                  </div>
                  {c.termination_reason ? (
                    <Badge variant="neutral" size="sm">
                      {c.termination_reason}
                    </Badge>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-background/60 px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 text-sm font-bold text-foreground">{value}</div>
    </div>
  );
}

function CurrentContractCard({
  contract,
  candidateName,
  candidatePhone,
}: {
  contract: any;
  candidateName: string;
  candidatePhone: string | null;
}) {
  const { showError } = useToast();
  // `isError`/`isSuccess`, nie samo `data`: padnięte pobranie dokumentów NIE
  // może renderować się jako „Brak załączników” — rekruter wysyłał wtedy
  // umowę do podpisu drugi raz.
  const docsQuery = useQuery<any[]>({
    queryKey: ["contract-docs", contract.id],
    queryFn: () => contractsApi.documents(contract.id).then((r: any) => r.data),
  });
  const documents = docsQuery.data ?? [];
  const legacyCurrency = contract.currency ?? "PLN";
  const clientRateCurrency = contract.rate_client_currency ?? legacyCurrency;
  const candidateRateCurrency = contract.rate_candidate_currency ?? legacyCurrency;
  const hasComparableCurrencies =
    clientRateCurrency.toUpperCase() === candidateRateCurrency.toUpperCase();

  const handleDownload = async (d: any) => {
    try {
      await downloadContractDocument(contract.id, d);
    } catch {
      showError(`Nie udało się pobrać pliku "${d.filename}".`);
    }
  };

  return (
    <Card variant="default" size="md">
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="font-semibold text-foreground">
              {contract.client_name ?? `Klient #${contract.client_id}`}
              {contract.project_name ? ` · ${contract.project_name}` : ""}
            </div>
            <div className="text-xs text-muted-foreground">
              {formatDate(contract.start_date)} —{" "}
              {contract.end_date ? formatDate(contract.end_date) : "bezterminowo"}
            </div>
            {/* Zaplanowane zakończenie (status „Kończący się"): koniec
                zamówienia i — przy rozwiązaniu — ostatni dzień umowy. */}
            {contract.terminated_at ? (
              <ContractTerminationSummary contract={contract} compact />
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <Badge
              variant={contract.status === "ending" ? "warning" : "success"}
              size="md"
            >
              {STATUS_LABEL[contract.status] ?? contract.status}
            </Badge>
            <Link
              href={`/contracts/${contract.id}`}
              className="text-xs text-primary underline"
            >
              Zarządzaj kontraktem →
            </Link>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <StatTile
            label="Stawka kandydata"
            value={formatRate(
              contract.rate_candidate,
              candidateRateCurrency,
              contract.rate_unit,
            )}
          />
          <StatTile
            label="Stawka klienta"
            value={formatRate(contract.rate_client, clientRateCurrency, contract.rate_unit)}
          />
          <StatTile
            label="Marża"
            value={formatRate(
              hasComparableCurrencies ? contract.margin : null,
              clientRateCurrency,
              contract.rate_unit,
            )}
          />
          <StatTile label="Tryb pracy" value={contract.work_mode ?? "—"} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Dokumenty
          </div>
          {docsQuery.isError ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-destructive">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span>
                Nie udało się wczytać listy załączników — nie wiemy, czy umowa je
                ma.
              </span>
              <button
                type="button"
                onClick={() => docsQuery.refetch()}
                className="underline"
              >
                Ponów
              </button>
            </div>
          ) : !docsQuery.isSuccess ? (
            <div className="text-xs text-muted-foreground">Wczytywanie…</div>
          ) : documents.length === 0 ? (
            <div className="text-xs text-muted-foreground">
              Brak załączników. Dodasz je z poziomu strony kontraktu.
            </div>
          ) : (
            <ul className="space-y-1">
              {documents.map((d: any) => (
                <li key={d.id} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2">
                    <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                    {d.filename}
                    <Badge variant="neutral" size="sm">
                      {d.doc_type}
                    </Badge>
                  </span>
                  <button
                    type="button"
                    onClick={() => handleDownload(d)}
                    className="inline-flex items-center gap-1 text-xs text-primary"
                  >
                    <Download className="h-3 w-3" /> pobierz
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <AutentiEnvelopeCard
          contractId={contract.id}
          candidateName={candidateName}
          candidatePhone={candidatePhone}
        />
      </CardContent>
    </Card>
  );
}
