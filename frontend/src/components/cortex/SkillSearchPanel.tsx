"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, RefreshCw, Search, Tags } from "lucide-react";
import {
  cortexApi,
  extractErrorMsg,
  type CortexSkillList,
  type CortexSkillListItem,
} from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { DataTable, type DataTableColumn } from "@/components/ds/DataTable";
import { EmptyState } from "@/components/ds/EmptyState";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SkillCandidatesDrawer } from "@/components/cortex/SkillCandidatesDrawer";

const PAGE_SIZE = 25;

const SOURCE_OPTIONS = [
  { value: "", label: "Wszystkie źródła" },
  { value: "traffit", label: "Traffit (technologie)" },
  { value: "cv_llm", label: "CV (ekstrakcja AI)" },
  { value: "screening", label: "Screening" },
];

export function SkillSearchPanel() {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<CortexSkillListItem | null>(null);

  const debouncedQ = useDebouncedValue(q.trim(), 300);

  // Search / filter change → back to first page.
  useEffect(() => {
    setOffset(0);
  }, [debouncedQ, source]);

  const { data, isLoading, isError, error, refetch, isFetching } =
    useQuery<CortexSkillList>({
      queryKey: ["cortex-skills", debouncedQ, source, offset],
      queryFn: async () =>
        (
          await cortexApi.skills({
            q: debouncedQ || undefined,
            source: source || undefined,
            limit: PAGE_SIZE,
            offset,
          })
        ).data,
      placeholderData: (prev) => prev,
    });

  const total = data?.total ?? 0;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + PAGE_SIZE, total);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  const columns: DataTableColumn<CortexSkillListItem>[] = useMemo(
    () => [
      {
        key: "canonical_name",
        header: "Technologia",
        render: (row) => (
          <span className="font-medium text-foreground">
            {row.canonical_name}
          </span>
        ),
      },
      {
        key: "category",
        header: "Kategoria",
        render: (row) =>
          row.category ? (
            <Badge variant="outline" size="sm">
              {row.category}
            </Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        key: "candidates",
        header: "Kandydaci",
        align: "right",
        render: (row) => (
          <span className="tabular-nums">
            {row.candidates.toLocaleString("pl-PL")}
          </span>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-4">
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[16rem]">
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Szukaj technologii (canonical lub alias)…"
              leadingIcon={<Search className="w-4 h-4" />}
              aria-label="Szukaj technologii"
            />
          </div>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="border border-border rounded-md bg-background px-2 py-1.5 text-xs h-10"
          >
            {SOURCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {isError ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm text-destructive">
              <AlertTriangle className="w-4 h-4" />
              Nie udało się załadować listy technologii.
            </p>
            <p className="text-xs text-muted-foreground">
              {extractErrorMsg(error)}
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="w-3.5 h-3.5" />
              Spróbuj ponownie
            </Button>
          </div>
        ) : isLoading || !data ? (
          <p className="text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
            Ładowanie technologii…
          </p>
        ) : data.skills.length === 0 ? (
          <EmptyState
            icon={Tags}
            title="Brak technologii"
            description={
              debouncedQ
                ? `Nic nie pasuje do „${debouncedQ}”. Spróbuj innej frazy lub sprawdź kolejkę kuracji.`
                : "Fact store nie ma jeszcze technologii z faktami."
            }
          />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data.skills}
              getRowKey={(row) => row.id}
              onRowClick={(row) => setSelected(row)}
              empty="Brak technologii."
            />
            <div className="flex items-center justify-between gap-3 pt-1">
              <p className="text-xs text-muted-foreground tabular-nums">
                {rangeStart.toLocaleString("pl-PL")}–
                {rangeEnd.toLocaleString("pl-PL")} z{" "}
                {total.toLocaleString("pl-PL")}
                {isFetching ? " · odświeżanie…" : ""}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasPrev || isFetching}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                >
                  Poprzednia
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasNext || isFetching}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                >
                  Następna
                </Button>
              </div>
            </div>
          </>
        )}
      </div>

      {selected ? (
        <SkillCandidatesDrawer
          skillId={selected.id}
          skillName={selected.canonical_name}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}
