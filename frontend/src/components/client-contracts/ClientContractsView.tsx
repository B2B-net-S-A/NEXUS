"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { useToast } from "@/components/Toast";
import { DataTable, type DataTableColumn } from "@/components/ds/DataTable";
import { FilterBar } from "@/components/ds/FilterBar";
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
import { formatIsoDatePl } from "@/lib/date-pl";

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
  clientName: string | null;
  name: string;
  isAmendment: boolean;
  status: ClientContractStatus | null;
  period: string;
  filename: string | null;
  filePath: string | null;
};

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

function toRows(contracts: ClientContractRow[]): DocumentRow[] {
  return contracts.flatMap((contract, index) => [
    {
      key: `contract-${contract.id}`,
      // Nazwa klienta tylko przy jego pierwszej umowie: lista czyta się grupami.
      clientName:
        contracts[index - 1]?.client_id === contract.client_id
          ? null
          : contract.client_name,
      name: contract.name,
      isAmendment: false,
      status: contract.status,
      period: periodLabel(contract.effective_date, contract.expiry_date),
      filename: contract.filename,
      filePath: contract.has_file
        ? clientContractDocumentsApi.contractFilePath(contract.id)
        : null,
    },
    ...contract.amendments.map((amendment) => ({
      key: `amendment-${amendment.id}`,
      clientName: null,
      name: amendment.name,
      isAmendment: true,
      status: null,
      period: periodLabel(amendment.effective_date, null),
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

  const query = search.trim().toLocaleLowerCase("pl");
  const rows = useMemo(() => {
    const all = contracts.data ?? [];
    return toRows(query ? all.filter((contract) => matches(contract, query)) : all);
  }, [contracts.data, query]);

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
      render: (row) => (
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
        <span className="whitespace-nowrap text-muted-foreground">{row.period}</span>
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
      <FilterBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: "Szukaj klienta, umowy lub aneksu",
          ariaLabel: "Szukaj w umowach klientów",
          onClear: () => setSearch(""),
        }}
      />
      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(row) => row.key}
        empty={
          query
            ? "Żadna umowa nie pasuje do wyszukiwania."
            : "Nie ma jeszcze żadnych umów klientów."
        }
      />
    </div>
  );
}
