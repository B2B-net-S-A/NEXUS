"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Link2,
} from "lucide-react";
import {
  cortexApi,
  extractErrorMsg,
  type CortexSkillList,
  type CortexUnmatchedTerm,
} from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useToast } from "@/components/Toast";
import { RequireRole } from "@/components/RequireRole";
import { DataTable, type DataTableColumn } from "@/components/ds/DataTable";
import { AppModal } from "@/components/ds/AppModal";
import { EmptyState } from "@/components/ds/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

const UNMATCHED_QUERY_KEY = ["cortex-unmatched-terms"] as const;

export function CurationPanel() {
  return (
    <RequireRole
      roles={["admin"]}
      fallback={
        <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6">
          <EmptyState
            icon={Ban}
            title="Brak dostępu"
            description="Kuracja taksonomii jest dostępna tylko dla administratorów."
          />
        </div>
      }
    >
      <CurationPanelInner />
    </RequireRole>
  );
}

function CurationPanelInner() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [mapTarget, setMapTarget] = useState<CortexUnmatchedTerm | null>(null);
  const [createTarget, setCreateTarget] =
    useState<CortexUnmatchedTerm | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery<
    CortexUnmatchedTerm[]
  >({
    queryKey: UNMATCHED_QUERY_KEY,
    queryFn: async () =>
      (await cortexApi.unmatchedTerms({ status: "new", limit: 100 })).data,
  });

  // After any curation action the unmatched queue + coverage aggregate + skill
  // list are stale — refresh all three (prefix-match catches every variant).
  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: UNMATCHED_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: ["cortex-coverage"] });
    queryClient.invalidateQueries({ queryKey: ["cortex-skills"] });
  };

  const ignoreMutation = useMutation({
    mutationFn: (termId: number) => cortexApi.ignoreTerm(termId),
    onSuccess: () => {
      toast.showSuccess("Termin oznaczony jako ignorowany");
      invalidateAll();
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const columns: DataTableColumn<CortexUnmatchedTerm>[] = [
    {
      key: "term",
      header: "Termin",
      render: (row) => (
        <span className="font-medium text-foreground">{row.term}</span>
      ),
    },
    {
      key: "occurrences",
      header: "Wystąpienia",
      align: "right",
      render: (row) => (
        <span className="tabular-nums">
          {row.occurrences.toLocaleString("pl-PL")}
        </span>
      ),
    },
    {
      key: "last_seen_at",
      header: "Ostatnio widziany",
      render: (row) =>
        row.last_seen_at
          ? new Date(row.last_seen_at).toLocaleDateString("pl-PL")
          : "—",
    },
    {
      key: "actions",
      header: "Akcje",
      align: "right",
      render: (row) => (
        <div className="flex items-center justify-end gap-1.5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setMapTarget(row)}
          >
            <Link2 className="w-3.5 h-3.5" />
            Mapuj
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCreateTarget(row)}
          >
            <Plus className="w-3.5 h-3.5" />
            Utwórz skill
          </Button>
          <Button
            variant="ghost"
            size="sm"
            loading={
              ignoreMutation.isPending && ignoreMutation.variables === row.id
            }
            disabled={ignoreMutation.isPending}
            onClick={() => ignoreMutation.mutate(row.id)}
          >
            <Ban className="w-3.5 h-3.5" />
            Ignoruj
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <h3 className="font-semibold text-sm">Kuracja taksonomii</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Terminy poza słownikiem — zmapuj na istniejący skill, utwórz nowy
              lub zignoruj. Fakty dla zmapowanych terminów powstaną przy
              najbliższym backfillu.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            onClick={() => refetch()}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Odśwież
          </Button>
        </div>

        {isError ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm text-destructive">
              <AlertTriangle className="w-4 h-4" />
              Nie udało się załadować kolejki kuracji.
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
            Ładowanie kolejki kuracji…
          </p>
        ) : (
          <DataTable
            columns={columns}
            rows={data}
            getRowKey={(row) => row.id}
            empty="Brak niedopasowanych terminów — taksonomia pokrywa surowiec."
          />
        )}
      </div>

      {mapTarget ? (
        <MapTermModal
          term={mapTarget}
          onClose={() => setMapTarget(null)}
          onDone={() => {
            invalidateAll();
            setMapTarget(null);
          }}
        />
      ) : null}

      {createTarget ? (
        <CreateSkillModal
          term={createTarget}
          onClose={() => setCreateTarget(null)}
          onDone={() => {
            invalidateAll();
            setCreateTarget(null);
          }}
        />
      ) : null}
    </div>
  );
}

// ── Map term → existing skill ─────────────────────────────────────────────────

function MapTermModal({
  term,
  onClose,
  onDone,
}: {
  term: CortexUnmatchedTerm;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [q, setQ] = useState(term.term);
  const debouncedQ = useDebouncedValue(q.trim(), 300);

  const { data, isLoading, isError, error, refetch } = useQuery<CortexSkillList>(
    {
      queryKey: ["cortex-skill-picker", debouncedQ],
      queryFn: async () =>
        (await cortexApi.skills({ q: debouncedQ || undefined, limit: 20 })).data,
      enabled: debouncedQ.length > 0,
    }
  );

  const mapMutation = useMutation({
    mutationFn: (skillId: number) => cortexApi.mapTerm(term.id, skillId),
    onSuccess: () => {
      toast.showSuccess(`„${term.term}” zmapowany`);
      onDone();
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Mapuj termin na skill"
      description={`„${term.term}” zostanie dodany jako alias wybranego skilla.`}
      size="md"
    >
      <div className="space-y-3">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Szukaj istniejącego skilla…"
          leadingIcon={<Search className="w-4 h-4" />}
          aria-label="Szukaj skilla"
        />

        {debouncedQ.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Wpisz frazę, by znaleźć skill.
          </p>
        ) : isError ? (
          <div className="space-y-2">
            <p className="text-sm text-destructive">{extractErrorMsg(error)}</p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="w-3.5 h-3.5" />
              Spróbuj ponownie
            </Button>
          </div>
        ) : isLoading || !data ? (
          <p className="text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
            Szukanie…
          </p>
        ) : data.skills.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Brak dopasowań. Rozważ „Utwórz skill”.
          </p>
        ) : (
          <ul className="max-h-72 overflow-y-auto divide-y divide-border rounded-lg border border-border">
            {data.skills.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between gap-3 px-3 py-2"
              >
                <div className="min-w-0">
                  <span className="text-sm font-medium text-foreground">
                    {s.canonical_name}
                  </span>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    {s.category ? (
                      <Badge variant="outline" size="sm">
                        {s.category}
                      </Badge>
                    ) : null}
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {s.candidates.toLocaleString("pl-PL")} kandydatów
                    </span>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  loading={
                    mapMutation.isPending && mapMutation.variables === s.id
                  }
                  disabled={mapMutation.isPending}
                  onClick={() => mapMutation.mutate(s.id)}
                >
                  Wybierz
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppModal>
  );
}

// ── Create new skill (optionally from term) ──────────────────────────────────

function CreateSkillModal({
  term,
  onClose,
  onDone,
}: {
  term: CortexUnmatchedTerm;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [canonicalName, setCanonicalName] = useState(term.term);
  const [category, setCategory] = useState("");

  const createMutation = useMutation({
    mutationFn: () =>
      cortexApi.createSkill({
        canonical_name: canonicalName.trim(),
        category: category.trim() || undefined,
        from_term_id: term.id,
      }),
    onSuccess: (res) => {
      toast.showSuccess(`Skill „${res.data.canonical_name}” utworzony`);
      onDone();
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const canSubmit = canonicalName.trim().length > 0 && !createMutation.isPending;

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Utwórz nowy skill"
      description={`Termin „${term.term}” zostanie dodany jako alias nowego skilla.`}
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            variant="primary"
            loading={createMutation.isPending}
            disabled={!canSubmit}
            onClick={() => createMutation.mutate()}
          >
            Utwórz skill
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) createMutation.mutate();
        }}
      >
        <div className="space-y-1">
          <label
            htmlFor="cortex-new-skill-name"
            className="text-xs font-medium text-muted-foreground"
          >
            Nazwa kanoniczna
          </label>
          <Input
            id="cortex-new-skill-name"
            value={canonicalName}
            onChange={(e) => setCanonicalName(e.target.value)}
            placeholder="np. SAP EWM"
            autoFocus
          />
        </div>
        <div className="space-y-1">
          <label
            htmlFor="cortex-new-skill-category"
            className="text-xs font-medium text-muted-foreground"
          >
            Kategoria (opcjonalnie)
          </label>
          <Input
            id="cortex-new-skill-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="np. ERP, Backend, DevOps"
          />
        </div>
      </form>
    </AppModal>
  );
}
