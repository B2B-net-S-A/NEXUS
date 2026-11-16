"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, FileText } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  PAGE_SIZE,
  archivePaths,
  useArchiveList,
  useArchiveSummary,
  type ArchiveDocument,
  type ArchiveFilters,
  type ArchiveKind,
} from "@/lib/api/finance-archive";
import { downloadAuthenticatedFile, openAuthenticatedFile } from "@/lib/authenticated-files";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const SELECT = "h-9 rounded-md border border-border bg-card px-2 text-sm text-foreground";
const MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"];
const KIND_TONE: Record<ArchiveKind, "info" | "warning" | "neutral"> = {
  sale: "info",
  cost: "warning",
  other: "neutral",
};

/**
 * Finanse → „Archiwum eBI24” (E5): dokumenty z archiwum eBI24 po jego
 * wyłączeniu — wyszukiwanie po numerze, kontrahencie, NIP-ie i numerze KSeF,
 * filtr rodzaju i miesiąca, otwarcie pliku. Faktura wystawiona w eBI24 otwiera
 * się jako podgląd z danych (HTML), wgrany dokument jako oryginalny PDF.
 */
export function Ebi24ArchiveTab() {
  const { showToast } = useToast();
  const [filters, setFilters] = useState<ArchiveFilters>({ q: "", kind: "", year: "", month: "", page: 0 });
  const q = useDebouncedValue(filters.q, 300);
  const summary = useArchiveSummary();
  const list = useArchiveList({ ...filters, q });
  const documents = list.data?.documents ?? [];
  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const set = (patch: Partial<ArchiveFilters>) => setFilters((current) => ({ ...current, page: 0, ...patch }));

  const open = async (doc: ArchiveDocument) => {
    try {
      if (doc.file_type === "pdf") {
        await openAuthenticatedFile(archivePaths.file(doc.id), "application/pdf", `ebi24-${doc.source_id}.pdf`);
      } else if (doc.file_type === "ebi") {
        // Podgląd składa NEXUS z danych (wszystko escapowane) — można go otworzyć jako stronę.
        await openAuthenticatedFile(archivePaths.file(doc.id), "text/html", `ebi24-${doc.source_id}.html`);
      } else {
        // Plik z obcego systemu (np. HTML) — tylko pobranie, bez otwierania w domenie NEXUSA.
        await downloadAuthenticatedFile(archivePaths.file(doc.id), `ebi24-${doc.source_id}.${doc.file_type}`);
      }
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się otworzyć dokumentu."), "error");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2">
        <p className="text-sm text-muted-foreground">
          {summary.data
            ? summary.data.total
              ? `${countPl(summary.data.total, "dokument", "dokumenty", "dokumentów")} z eBI24 · ` +
                summary.data.years.map((y) => `${y.year}: ${y.sale + y.cost + y.other}`).join(" · ")
              : "Archiwum eBI24 nie jest jeszcze wgrane."
            : "Wczytywanie archiwum…"}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Szukaj w archiwum"
          placeholder="Numer, kontrahent, NIP, numer KSeF…"
          className="h-9 w-72"
          value={filters.q}
          onChange={(event) => set({ q: event.target.value })}
        />
        <select aria-label="Rodzaj dokumentu" className={SELECT} value={filters.kind} onChange={(e) => set({ kind: e.target.value as ArchiveKind | "" })}>
          <option value="">Wszystkie rodzaje</option>
          <option value="sale">Sprzedaż</option>
          <option value="cost">Koszty</option>
          <option value="other">Inne</option>
        </select>
        <select aria-label="Rok" className={SELECT} value={filters.year} onChange={(e) => set({ year: e.target.value, month: "" })}>
          <option value="">Wszystkie lata</option>
          {(summary.data?.years ?? [])
            .filter((y) => /^\d{4}$/.test(y.year))
            .map((y) => (
              <option key={y.year} value={y.year}>
                {y.year}
              </option>
            ))}
        </select>
        <select aria-label="Miesiąc" className={SELECT} value={filters.month} disabled={!filters.year} onChange={(e) => set({ month: e.target.value })}>
          <option value="">Cały rok</option>
          {MONTHS.map((name, index) => (
            <option key={name} value={String(index + 1)}>
              {name}
            </option>
          ))}
        </select>
        {list.data ? (
          <span className="text-sm text-muted-foreground">{countPl(total, "wynik", "wyniki", "wyników")}</span>
        ) : null}
      </div>

      {list.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie dokumentów…</p>
      ) : list.isError ? (
        <QueryStateNotice state="error" onRetry={() => list.refetch()} />
      ) : list.isSuccess && documents.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {summary.data?.total ? "Brak dokumentów dla tych filtrów." : "Archiwum eBI24 nie jest jeszcze wgrane."}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <Table density="compact" className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} w-[11%]`}>Data</TableHead>
                <TableHead className={`${CALM_HEAD} w-[20%]`}>Numer</TableHead>
                <TableHead className={`${CALM_HEAD} w-[10%]`}>Rodzaj</TableHead>
                <TableHead className={`${CALM_HEAD} w-[31%]`}>Kontrahent</TableHead>
                <TableHead className={`${CALM_HEAD} w-[15%] text-right`}>Brutto</TableHead>
                <TableHead className={`${CALM_HEAD} w-[13%]`}>
                  <span className="sr-only">Plik</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => (
                <TableRow key={doc.id} className={`${CALM_ROW} align-top`} data-testid={`archive-${doc.id}`}>
                  <TableCell className="text-sm tabular-nums">{doc.issue_date ? formatIsoDatePl(doc.issue_date) : "—"}</TableCell>
                  <TableCell className="min-w-0">
                    <span className="block truncate" title={doc.invoice_number ?? ""}>
                      {doc.invoice_number ?? "bez numeru"}
                    </span>
                    {doc.ksef_number ? (
                      <span className={`${CALM_SUBLINE} truncate`} title={doc.ksef_number}>
                        KSeF {doc.ksef_number}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <StatusDot tone={KIND_TONE[doc.kind]}>{doc.kind_label}</StatusDot>
                  </TableCell>
                  <TableCell className="min-w-0">
                    <span className="block truncate" title={doc.partner_name ?? ""}>
                      {doc.partner_name ?? "—"}
                    </span>
                    <span className={CALM_SUBLINE}>{doc.partner_id ?? ""}</span>
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {doc.gross ? formatMoney(doc.gross, doc.currency ?? "PLN") : "—"}
                  </TableCell>
                  <TableCell>
                    <Button size="sm" variant="ghost" onClick={() => open(doc)} aria-label={`Otwórz dokument ${doc.invoice_number ?? doc.source_id}`}>
                      <FileText className="h-4 w-4" aria-hidden />
                      {doc.file_type === "ebi" ? "Podgląd" : doc.file_type === "pdf" ? "PDF" : "Pobierz"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {total > PAGE_SIZE ? (
        <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
          <Button size="sm" variant="ghost" aria-label="Poprzednia strona" disabled={filters.page === 0} onClick={() => setFilters((c) => ({ ...c, page: c.page - 1 }))}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
          <span>
            Strona {filters.page + 1} z {pages}
          </span>
          <Button size="sm" variant="ghost" aria-label="Następna strona" disabled={filters.page + 1 >= pages} onClick={() => setFilters((c) => ({ ...c, page: c.page + 1 }))}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
