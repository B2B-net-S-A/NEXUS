"use client";

import { useEffect, useState } from "react";
import { ListChecks } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  searchSkills,
  useResolveSkillReview,
  useSkillReview,
  type SkillReviewRow,
} from "@/lib/api/care";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn, formatDate } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

// Kategorie słownika, w których żyją technologie (jak w „Słowniku umiejętności”).
const CATEGORIES = [
  "language",
  "framework",
  "frontend",
  "backend",
  "database",
  "cloud",
  "devops",
  "data",
  "messaging",
  "api",
  "qa",
  "mobile",
  "security",
  "tools",
  "standards",
  "ai",
];
const NO_CATEGORY = "none";

const STATUS_LABELS: Record<SkillReviewRow["status"], string> = {
  open: "Do przejrzenia",
  mapped: "Zmapowana",
  created: "Dodana do słownika",
  dismissed: "Odrzucona",
};

function MapDialog({ row, onClose }: { row: SkillReviewRow; onClose: () => void }) {
  const { showToast } = useToast();
  const resolve = useResolveSkillReview();
  const [query, setQuery] = useState(row.name);
  const [options, setOptions] = useState<{ id: number; name: string }[]>([]);
  const [picked, setPicked] = useState<{ id: number; name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      searchSkills(q)
        .then((items) => {
          if (!cancelled) setOptions(items);
        })
        .catch(() => {
          if (!cancelled) setError("Nie udało się wyszukać w słowniku.");
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Zmapuj „${row.name}”`}
      description="Nazwa zostanie aliasem wybranej umiejętności — od razu w kartach, wyszukiwaniu i dopasowaniu."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={!picked || resolve.isPending}
            onClick={() =>
              picked &&
              resolve.mutate(
                { kind: "map", itemId: row.id, skillId: picked.id },
                {
                  onSuccess: () => {
                    showToast("Technologia zmapowana", "success");
                    onClose();
                  },
                  onError: (err) => setError(apiErrorMessage(err, "Nie udało się zmapować.")),
                },
              )
            }
          >
            Zmapuj
          </Button>
        </>
      }
    >
      <FormField label="Umiejętność ze słownika" htmlFor="care-review-search">
        <Input id="care-review-search" value={query} onChange={(event) => setQuery(event.target.value)} />
      </FormField>
      <ul className="mt-2 max-h-48 overflow-y-auto rounded-md border border-border text-sm">
        {options.map((option) => (
          <li key={option.id}>
            <button
              type="button"
              aria-pressed={picked?.id === option.id}
              className={cn(
                "w-full px-3 py-1.5 text-left hover:bg-muted",
                picked?.id === option.id && "bg-muted font-medium",
              )}
              onClick={() => setPicked(option)}
            >
              {option.name}
            </button>
          </li>
        ))}
        {!options.length ? (
          <li className="px-3 py-1.5 text-muted-foreground">Wpisz co najmniej 2 znaki.</li>
        ) : null}
      </ul>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

function CreateDialog({ row, onClose }: { row: SkillReviewRow; onClose: () => void }) {
  const { showToast } = useToast();
  const resolve = useResolveSkillReview();
  const [name, setName] = useState(row.name);
  const [category, setCategory] = useState(NO_CATEGORY);
  const [error, setError] = useState<string | null>(null);
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Dodaj do słownika umiejętności"
      description="Nowa umiejętność będzie dostępna w wymaganiach rekrutacji, profilach i na mapach klientów."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={!name.trim() || resolve.isPending}
            onClick={() =>
              resolve.mutate(
                {
                  kind: "create",
                  itemId: row.id,
                  canonicalName: name.trim(),
                  category: category === NO_CATEGORY ? null : category,
                },
                {
                  onSuccess: () => {
                    showToast("Umiejętność dodana", "success");
                    onClose();
                  },
                  onError: (err) => setError(apiErrorMessage(err, "Nie udało się dodać umiejętności.")),
                },
              )
            }
          >
            Dodaj
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px]">
        <FormField label="Nazwa" htmlFor="care-review-name">
          <Input
            id="care-review-name"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <FormField label="Kategoria" htmlFor="care-review-category">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger id="care-review-category">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_CATEGORY}>Bez kategorii</SelectItem>
              {CATEGORIES.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

/** Technologie wpisane na kartach, których nie ma w słowniku umiejętności. */
export function SkillReviewPanel() {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [state, setState] = useState<"open" | "closed">("open");
  const query = useSkillReview(state);
  const resolve = useResolveSkillReview();
  const [dialog, setDialog] = useState<{ kind: "map" | "create"; row: SkillReviewRow } | null>(null);
  const rows = query.data?.items ?? [];
  const canCurate = query.data?.can_curate ?? false;
  const view = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });

  const dismiss = async (row: SkillReviewRow) => {
    const ok = await askConfirm({
      title: `Odrzucić „${row.name}”?`,
      description: "Nazwa zostanie na kartach jako tekst i nie wróci do przejrzenia.",
      confirmLabel: "Odrzuć",
      variant: "destructive",
    });
    if (!ok) return;
    resolve.mutate(
      { kind: "dismiss", itemId: row.id },
      {
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się odrzucić nazwy."), "error"),
      },
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1" role="group" aria-label="Stan kolejki technologii">
        {(
          [
            ["open", "Do przejrzenia"],
            ["closed", "Rozstrzygnięte"],
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            size="sm"
            variant={state === value ? "secondary" : "ghost"}
            aria-pressed={state === value}
            onClick={() => setState(value)}
          >
            {label}
          </Button>
        ))}
      </div>
      {view === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : view === "forbidden" || view === "not_found" || view === "error" ? (
        <QueryStateNotice state={view} onRetry={() => query.refetch()} />
      ) : view === "empty" ? (
        <EmptyState
          icon={ListChecks}
          title={state === "open" ? "Nic nie czeka na przejrzenie" : "Brak rozstrzygniętych nazw"}
          description={
            state === "open"
              ? "Tu trafia technologia wpisana na karcie tekstem, której nie ma w słowniku umiejętności."
              : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className={CALM_ROW}>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Nazwa z karty</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-right")}>Wystąpienia</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Stan</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Decyzja</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={CALM_ROW}>
                  <td className="px-3 py-1.5">
                    <span className="font-medium">{row.name}</span>
                    <span className={CALM_SUBLINE}>
                      {row.reported_by ? `${row.reported_by.name} · ` : ""}
                      {formatDate(row.created_at)}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{row.occurrences}</td>
                  <td className="px-3 py-1.5">
                    {STATUS_LABELS[row.status]}
                    {row.skill ? <span className={CALM_SUBLINE}>→ {row.skill.name}</span> : null}
                  </td>
                  <td className="px-3 py-1.5">
                    {canCurate && row.status !== "mapped" && row.status !== "created" ? (
                      <span className="flex flex-wrap gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setDialog({ kind: "map", row })}>
                          Zmapuj
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDialog({ kind: "create", row })}>
                          Dodaj do słownika
                        </Button>
                        {row.status === "open" ? (
                          <Button variant="quiet" size="sm" onClick={() => dismiss(row)}>
                            Odrzuć
                          </Button>
                        ) : null}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">
                        {canCurate ? "—" : "Decyduje admin, Head of Recruitment albo TCM"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {dialog?.kind === "map" ? <MapDialog row={dialog.row} onClose={() => setDialog(null)} /> : null}
      {dialog?.kind === "create" ? <CreateDialog row={dialog.row} onClose={() => setDialog(null)} /> : null}
      {confirmDialog}
    </div>
  );
}
