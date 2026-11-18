"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { useToast } from "@/components/Toast";
import { DataTable, type DataTableColumn } from "@/components/ds/DataTable";
import { FilterBar } from "@/components/ds/FilterBar";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import {
  clientContractDocumentsApi,
  type ClientContractRow,
  type ClientContractStatus,
} from "@/lib/api/clientContractDocuments";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { hasCapability } from "@/lib/capabilities";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";
import { useAuthStore } from "@/store/auth";

const STATUS_LABELS: Record<ClientContractStatus, string> = {
  draft: "Szkic",
  pending_signature: "Czeka na podpis",
  active: "Aktywna",
  expired: "Wygasła",
  terminated: "Rozwiązana",
  superseded: "Zastąpiona",
};

const STATUS_TONES: Record<ClientContractStatus, StatusDotTone> = {
  draft: "neutral",
  pending_signature: "warning",
  active: "success",
  expired: "danger",
  terminated: "warning",
  superseded: "neutral",
};

type DocumentRow = {
  key: string;
  clientId: number;
  clientName: string | null;
  name: string;
  isAmendment: boolean;
  status: ClientContractStatus | null;
  period: string;
  /** Dni do końca umowy (makieta 18.11.2026): ostrzeżenie przy ≤ 90. */
  daysLeft: number | null;
  filename: string | null;
  filePath: string | null;
};

/** „Obowiązujące” to aktywne i czekające na podpis — reszta to historia. */
const LIVE: ReadonlySet<ClientContractStatus> = new Set(["active", "pending_signature"]);
const ENDING_DAYS = 90;
type Scope = "live" | "ending" | "all";
const SCOPES: { value: Scope; label: string }[] = [
  { value: "live", label: "Obowiązujące" },
  { value: "ending", label: `Kończą się w ${ENDING_DAYS} dni` },
  { value: "all", label: "Wszystkie" },
];

function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(`${toIso}T00:00:00Z`) - Date.parse(`${fromIso}T00:00:00Z`)) / 86_400_000);
}

function daysLeftOf(contract: ClientContractRow, today: string): number | null {
  return contract.expiry_date ? daysBetween(today, contract.expiry_date) : null;
}

function inScope(contract: ClientContractRow, scope: Scope, today: string): boolean {
  if (scope === "all") return true;
  if (!LIVE.has(contract.status)) return false;
  if (scope === "live") return true;
  const days = daysLeftOf(contract, today);
  return days !== null && days <= ENDING_DAYS;
}

function periodLabel(from: string | null, to: string | null): string {
  return [
    from ? `od ${formatIsoDatePl(from)}` : null,
    to ? `do ${formatIsoDatePl(to)}` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

function matches(contract: ClientContractRow, query: string): boolean {
  return [
    contract.client_name,
    contract.name,
    contract.filename,
    ...contract.amendments.flatMap((amendment) => [amendment.name, amendment.filename]),
  ].some((value) => value?.toLocaleLowerCase("pl").includes(query));
}

function toRows(contracts: ClientContractRow[], today: string): DocumentRow[] {
  return contracts.flatMap((contract, index) => [
    {
      key: `contract-${contract.id}`,
      clientId: contract.client_id,
      // Nazwa klienta tylko przy jego pierwszej umowie: lista czyta się grupami.
      clientName:
        contracts[index - 1]?.client_id === contract.client_id
          ? null
          : contract.client_name,
      name: contract.name,
      isAmendment: false,
      status: contract.status,
      period: periodLabel(contract.effective_date, contract.expiry_date),
      daysLeft: LIVE.has(contract.status) ? daysLeftOf(contract, today) : null,
      filename: contract.filename,
      filePath: contract.has_file
        ? clientContractDocumentsApi.contractFilePath(contract.id)
        : null,
    },
    ...contract.amendments.map((amendment) => ({
      key: `amendment-${amendment.id}`,
      clientId: contract.client_id,
      clientName: null,
      name: amendment.name,
      isAmendment: true,
      status: null,
      period: periodLabel(amendment.effective_date, null),
      daysLeft: null,
      filename: amendment.filename,
      filePath: amendment.has_file
        ? clientContractDocumentsApi.amendmentFilePath(contract.id, amendment.id)
        : null,
    })),
  ]);
}

export function ClientContractsView() {
  const { showToast } = useToast();
  const [search, setSearch] = useState("");
  const contracts = useQuery({
    queryKey: ["client-contract-documents"],
    queryFn: clientContractDocumentsApi.list,
  });

  const user = useAuthStore((state) => state.user);
  // Nazwa klienta prowadzi do jego „Umów” tylko u osoby, która otwiera profil
  // klienta — samo „Umowy klientów: lista i pliki” go nie otwiera.
  const canOpenClient = hasCapability(user, "nav.clients");
  const [scope, setScope] = useState<Scope>("live");
  const today = warsawToday();
  const query = search.trim().toLocaleLowerCase("pl");
  const rows = useMemo(() => {
    const all = (contracts.data ?? []).filter((contract) => inScope(contract, scope, today));
    return toRows(query ? all.filter((contract) => matches(contract, query)) : all, today);
  }, [contracts.data, query, scope, today]);
  const stats = useMemo(() => {
    const all = contracts.data ?? [];
    const live = all.filter((contract) => LIVE.has(contract.status));
    const ending = live.filter((contract) => {
      const days = daysLeftOf(contract, today);
      return days !== null && days <= ENDING_DAYS;
    });
    return [
      { id: "clients", label: "klientów z umową", value: new Set(live.map((c) => c.client_id)).size },
      { id: "live", label: "umów obowiązujących", value: live.length },
      { id: "ending", label: `kończy się w ${ENDING_DAYS} dni`, value: ending.length },
      {
        id: "amendments",
        label: "aneksów",
        value: live.reduce((sum, contract) => sum + contract.amendments.length, 0),
      },
      { id: "nofile", label: "bez pliku", value: live.filter((contract) => !contract.has_file).length },
    ];
  }, [contracts.data, today]);

  const download = async (row: DocumentRow) => {
    if (!row.filePath) return;
    try {
      await downloadAuthenticatedFile(row.filePath, row.filename ?? `${row.name}.pdf`);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać pliku."), "error");
    }
  };

  const columns: Array<DataTableColumn<DocumentRow>> = [
    {
      key: "client",
      header: "Klient",
      render: (row) =>
        row.clientName && canOpenClient ? (
          <Link
            href={`/clients/${row.clientId}?tab=umowy-ramowe`}
            className="block max-w-[11rem] whitespace-normal font-medium hover:text-primary hover:underline"
          >
            {row.clientName}
          </Link>
        ) : (
          <span className="block max-w-[11rem] whitespace-normal font-medium">
            {row.clientName}
          </span>
        ),
    },
    {
      key: "document",
      header: "Dokument",
      render: (row) =>
        row.isAmendment ? (
          <span className="block max-w-[22rem] whitespace-normal pl-4 text-muted-foreground">
            Aneks: {row.name}
          </span>
        ) : (
          <span className="block max-w-[22rem] whitespace-normal">{row.name}</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      render: (row) =>
        row.status ? (
          <StatusDot tone={STATUS_TONES[row.status]}>{STATUS_LABELS[row.status]}</StatusDot>
        ) : null,
    },
    {
      key: "period",
      header: "Obowiązuje",
      render: (row) => (
        <span className="flex flex-col whitespace-nowrap text-muted-foreground">
          {row.period}
          {row.daysLeft !== null && row.daysLeft <= ENDING_DAYS ? (
            <span className={cn("text-[11px] font-medium", row.daysLeft < 0 ? "text-destructive" : "text-warning")}>
              {row.daysLeft < 0
                ? `po terminie ${countPl(-row.daysLeft, "dzień", "dni", "dni")}`
                : `kończy się za ${countPl(row.daysLeft, "dzień", "dni", "dni")}`}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "file",
      header: "Plik",
      align: "right",
      render: (row) =>
        row.filePath ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void download(row)}
            aria-label={`Pobierz: ${row.name}`}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            Pobierz
          </Button>
        ) : (
          <span className="text-sm text-muted-foreground">Brak pliku</span>
        ),
    },
  ];

  if (contracts.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(
          contracts.error,
          "Nie udało się pobrać listy umów. Spróbuj ponownie za chwilę.",
        )}
        onRetry={() => void contracts.refetch()}
      />
    );
  }

  if (!contracts.isSuccess) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie umów…</p>;
  }

  return (
    <div className="space-y-4">
      <InlineStats stats={stats} />
      <FilterBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: "Szukaj klienta, umowy lub aneksu",
          ariaLabel: "Szukaj w umowach klientów",
          onClear: () => setSearch(""),
        }}
        filters={
          <div className="inline-flex gap-0.5 rounded-lg bg-muted/70 p-0.5" role="group" aria-label="Które umowy">
            {SCOPES.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={scope === item.value}
                onClick={() => setScope(item.value)}
                className={cn(
                  "whitespace-nowrap rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors",
                  scope === item.value
                    ? "bg-card text-foreground shadow-xs ring-1 ring-border/70"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        }
      />
      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(row) => row.key}
        empty={
          query
            ? "Żadna umowa nie pasuje do wyszukiwania."
            : scope === "ending"
              ? `Żadna obowiązująca umowa nie kończy się w ciągu ${ENDING_DAYS} dni.`
              : "Nie ma jeszcze żadnych umów klientów."
        }
      />
    </div>
  );
}
