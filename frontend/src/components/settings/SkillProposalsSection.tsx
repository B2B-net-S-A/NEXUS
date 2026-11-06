"use client";

/**
 * Słownik umiejętności → „Propozycje” (06.11.2026, audyt słownika, makieta S1).
 *
 * Nazwy, których słownik nie zna, z profili, CV i wymagań, pogrupowane w
 * rodziny zapisów. Decyzję proponuje co noc model (`/api/skills-admin/proposals`),
 * ale do słownika wchodzi tylko to, co zatwierdzi Head of Recruitment albo admin
 * (D7: nic nie mapuje się samo). „Zatwierdź pewne” bierze wyłącznie propozycje
 * z pewnością „high”, bez uwagi i z kategorią.
 */

import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  skillsAdminApi,
  type SkillDictionaryItem,
  type SkillProposal,
  type SkillProposalFix,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { pluralPl } from "@/lib/plural-pl";
import { skillCategoryLabel } from "@/lib/skill-categories";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

const PAGE_SIZE = 50;
/** Zapisy rodziny w wierszu; reszta jako liczba (Excel ma ich kilkadziesiąt). */
const NAMES_SHOWN = 6;

export const skillProposalsQueryKey = ["skills-admin", "proposals"] as const;

const DECISION: Record<string, { label: string; tone: string }> = {
  new: { label: "Nowe hasło", tone: "bg-success-muted text-success-muted-foreground" },
  alias: { label: "Wariant znanego hasła", tone: "bg-primary/10 text-primary" },
  generic: { label: "Ogólnik, nie dodawać", tone: "bg-muted text-muted-foreground" },
  soft: { label: "Język albo cecha, nie dodawać", tone: "bg-muted text-muted-foreground" },
  noise: { label: "Śmieć, nie dodawać", tone: "bg-muted text-muted-foreground" },
};

function fmt(n: number): string {
  return n.toLocaleString("pl-PL");
}

/** Liczba otwartych propozycji do etykiety zakładki; `null` = jeszcze nie wiadomo. */
export function useOpenProposalCount(): number | null {
  const query = useQuery({
    queryKey: [...skillProposalsQueryKey, "count"],
    queryFn: () => skillsAdminApi.proposals({ limit: 1 }),
    staleTime: 60_000,
  });
  return query.isSuccess ? query.data.totals.open : null;
}

function SkillPicker({ onPick }: { onPick: (skill: SkillDictionaryItem) => void }) {
  const [q, setQ] = useState("");
  const debounced = useDebouncedValue(q.trim(), 300);
  const matches = useQuery({
    queryKey: ["skills-admin", "skills", "picker", debounced],
    queryFn: () => skillsAdminApi.list({ q: debounced, kind: "skills", limit: 8 }),
    enabled: debounced.length > 0,
  });
  return (
    <div className="space-y-1.5">
      <Input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Szukaj hasła w słowniku…"
        aria-label="Hasło słownika"
        className="h-8"
      />
      {matches.isError ? (
        <p className="text-xs text-destructive">Nie udało się wyszukać haseł.</p>
      ) : null}
      {matches.isSuccess && matches.data.items.length === 0 ? (
        <p className="text-xs text-muted-foreground">Nic nie pasuje.</p>
      ) : null}
      {matches.isSuccess && matches.data.items.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {matches.data.items.map((skill) => (
            <Button key={skill.id} type="button" size="sm" variant="outline" onClick={() => onPick(skill)}>
              {skill.name}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FixForm({
  row,
  categories,
  busy,
  onSubmit,
  onCancel,
}: {
  row: SkillProposal;
  categories: string[];
  busy: boolean;
  onSubmit: (fix: SkillProposalFix) => void;
  onCancel: () => void;
}) {
  const [decision, setDecision] = useState<"new" | "alias">(row.decision === "alias" ? "alias" : "new");
  const [canonical, setCanonical] = useState(row.canonical ?? row.display_name);
  const [category, setCategory] = useState(row.category ?? "");
  const [target, setTarget] = useState<{ id: number; name: string } | null>(
    row.target_skill_id && row.target_name ? { id: row.target_skill_id, name: row.target_name } : null,
  );
  const ready = decision === "new" ? canonical.trim().length > 0 : target !== null;
  return (
    <div className="mt-2 space-y-2 rounded-md border border-border bg-muted/30 p-2" data-testid="proposal-fix">
      <div className="flex gap-1" role="radiogroup" aria-label="Decyzja">
        {(["new", "alias"] as const).map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={decision === value ? "primary" : "outline"}
            role="radio"
            aria-checked={decision === value}
            onClick={() => setDecision(value)}
          >
            {value === "new" ? "Nowe hasło" : "Wariant hasła"}
          </Button>
        ))}
      </div>
      {decision === "new" ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <Input
            value={canonical}
            onChange={(e) => setCanonical(e.target.value)}
            aria-label="Nazwa hasła"
            className="h-8"
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            aria-label="Kategoria"
            className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground"
          >
            <option value="">Bez kategorii</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {skillCategoryLabel(c)}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <div className="space-y-1">
          {target ? (
            <p className="text-xs text-foreground">
              Warianty dopiszę do „{target.name}”.
            </p>
          ) : null}
          <SkillPicker onPick={(skill) => setTarget({ id: skill.id, name: skill.name })} />
        </div>
      )}
      <div className="flex gap-1">
        <Button
          type="button"
          size="sm"
          disabled={!ready || busy}
          onClick={() =>
            onSubmit(
              decision === "new"
                ? { decision, canonical: canonical.trim(), category }
                : { decision, target_skill_id: target?.id },
            )
          }
        >
          Zatwierdź
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}

function ProposalRow({ row, categories }: { row: SkillProposal; categories: string[] }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [fixing, setFixing] = useState(false);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["skills-admin"] });
  const accept = useMutation({
    mutationFn: (fix: SkillProposalFix) => skillsAdminApi.acceptProposal(row.id, fix),
    onSuccess: () => {
      toast.showSuccess(`„${row.canonical || row.display_name}” jest w słowniku`);
      setFixing(false);
      refresh();
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się zatwierdzić propozycji")),
  });
  const reject = useMutation({
    mutationFn: () => skillsAdminApi.rejectProposal(row.id),
    onSuccess: () => {
      toast.showSuccess(`Pominięto „${row.display_name}”`);
      refresh();
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się pominąć propozycji")),
  });
  const busy = accept.isPending || reject.isPending;
  const decision = DECISION[row.decision ?? ""] ?? {
    label: "Bez propozycji modelu",
    tone: "bg-muted text-muted-foreground",
  };
  const addable = row.decision === "new" || row.decision === "alias";
  const title = row.decision === "alias" ? row.target_name ?? row.canonical : row.canonical;
  return (
    <tr className="border-t border-border align-top" data-testid="skill-proposal-row">
      <td className="px-3 py-2">
        <p className="text-sm font-medium text-foreground">{title || row.display_name}</p>
        <p className="text-[11px] text-muted-foreground">
          {row.names
            .slice(0, NAMES_SHOWN)
            .map((n) => n.name)
            .join(" · ")}
          {row.names.length > NAMES_SHOWN
            ? ` · i ${row.names.length - NAMES_SHOWN} ${pluralPl(row.names.length - NAMES_SHOWN, "inny zapis", "inne zapisy", "innych zapisów")}`
            : ""}
        </p>
      </td>
      <td className="px-3 py-2 text-xs tabular-nums text-muted-foreground">
        <span className="block">profile {fmt(row.cand_count)}</span>
        <span className="block">CV {fmt(row.cv_count)}</span>
        <span className={cn("block", row.job_count > 0 && "font-medium text-foreground")}>
          wymagania {fmt(row.job_count)}
        </span>
      </td>
      <td className="px-3 py-2">
        <span className={cn("inline-block rounded-xl px-2 py-0.5 text-[11px] font-medium", decision.tone)}>
          {decision.label}
        </span>
        {row.confidence === "low" && !row.review_note ? (
          <p className="mt-1 text-[11px] text-warning-muted-foreground">Model nie jest pewny: sprawdź</p>
        ) : null}
        {row.review_note ? (
          <p className="mt-1 text-[11px] text-warning-muted-foreground">{row.review_note}</p>
        ) : null}
        {row.decision === "generic" && row.replacements.length > 0 ? (
          <p className="mt-1 text-[11px] text-muted-foreground">Zamiast: {row.replacements.join(", ")}</p>
        ) : null}
      </td>
      <td className="px-3 py-2 text-xs text-foreground">{skillCategoryLabel(row.category)}</td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {addable ? (
            <Button
              size="sm"
              variant={row.sure ? "primary" : "outline"}
              disabled={busy}
              onClick={() => accept.mutate({})}
            >
              {row.decision === "new" ? "Dodaj" : "Zmapuj"}
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setFixing((v) => !v)}>
            Zmień
          </Button>
          <Button size="sm" variant={addable ? "ghost" : "outline"} disabled={busy} onClick={() => reject.mutate()}>
            Pomiń
          </Button>
        </div>
        {fixing ? (
          <FixForm
            row={row}
            categories={categories}
            busy={busy}
            onSubmit={(fix) => accept.mutate(fix)}
            onCancel={() => setFixing(false)}
          />
        ) : null}
      </td>
    </tr>
  );
}

export function SkillProposalsSection() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const debounced = useDebouncedValue(search.trim(), 300);
  const query = useQuery({
    queryKey: [...skillProposalsQueryKey, debounced, page],
    queryFn: () => skillsAdminApi.proposals({ q: debounced, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const acceptSure = useMutation({
    mutationFn: () => skillsAdminApi.acceptSureProposals(),
    onSuccess: (result) => {
      const skipped = result.skipped.length;
      toast.showSuccess(
        `Zatwierdzono ${result.accepted} ${pluralPl(result.accepted, "propozycję", "propozycje", "propozycji")}` +
          (skipped ? `, ${skipped} z konfliktem zostało do decyzji` : ""),
      );
      void queryClient.invalidateQueries({ queryKey: ["skills-admin"] });
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się zatwierdzić propozycji")),
  });
  const data = query.data;
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: (data?.items.length ?? 0) === 0,
    isSuccess: query.isSuccess,
  });
  const totals = data?.totals;
  const lastPage = Math.max(0, Math.ceil((data?.total ?? 0) / PAGE_SIZE) - 1);

  const confirmSure = async () => {
    if (!totals) return;
    const ok = await askConfirm({
      title: `Zatwierdzić ${totals.sure} ${pluralPl(totals.sure, "pewną propozycję", "pewne propozycje", "pewnych propozycji")}?`,
      description:
        "Nowe hasła i warianty, których model jest pewny, bez uwag i z kategorią, trafią do słownika " +
        "całej aplikacji. Wyszukiwanie i dopasowanie zobaczą je od razu.",
      confirmLabel: "Zatwierdź",
    });
    if (ok) acceptSure.mutate();
  };

  return (
    <section aria-label="Propozycje do słownika" className="space-y-3" data-testid="skill-proposals">
      {confirmDialog}
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
        <div className="space-y-0.5">
          <p className="text-sm font-semibold text-foreground">
            {totals ? `${fmt(totals.names)} nazw, których słownik nie zna, z profili, CV i wymagań` : "Nazwy, których słownik nie zna"}
          </p>
          <p className="text-xs text-muted-foreground">
            {totals ? `Pogrupowane w ${fmt(totals.open)} ${pluralPl(totals.open, "hasło", "hasła", "haseł")}. ` : ""}
            Kolejność: jak często blokują dopasowanie. Propozycje liczy model co noc; nic nie wchodzi do
            słownika bez zatwierdzenia.
          </p>
        </div>
        <Button
          size="sm"
          disabled={!totals || totals.sure === 0 || acceptSure.isPending}
          onClick={() => void confirmSure()}
        >
          Zatwierdź pewne nowe hasła i warianty{totals ? ` (${totals.sure})` : ""}
        </Button>
      </div>
      <Input
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setPage(0);
        }}
        placeholder="Szukaj w propozycjach…"
        aria-label="Szukaj w propozycjach"
        className="max-w-sm"
      />
      {viewState === "loading" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Ładowanie propozycji…
        </p>
      ) : null}
      {viewState === "error" || viewState === "forbidden" ? (
        <QueryStateNotice state={viewState} onRetry={() => void query.refetch()} />
      ) : null}
      {viewState === "empty" ? (
        <p className="text-sm text-muted-foreground">
          {debounced
            ? "Żadna propozycja nie pasuje do wyszukiwania."
            : "Nie ma propozycji do przejrzenia. Model liczy je co noc między 1:00 a 5:00."}
        </p>
      ) : null}
      {viewState === "ready" && data ? (
        <>
          <div className="relative overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left">
              <thead className="bg-muted/50 text-[11px] font-semibold text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Hasło i zapisy z danych</th>
                  <th className="px-3 py-2">Gdzie występuje</th>
                  <th className="px-3 py-2">Propozycja</th>
                  <th className="px-3 py-2">Kategoria</th>
                  <th className="px-3 py-2">
                    <span className="sr-only">Akcje</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <ProposalRow key={row.id} row={row} categories={data.categories} />
                ))}
              </tbody>
            </table>
          </div>
          {lastPage > 0 ? (
            <div className="flex items-center justify-between text-sm">
              <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                Poprzednia
              </Button>
              <span className="text-muted-foreground">
                Strona {page + 1} z {lastPage + 1}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={page >= lastPage}
                onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
              >
                Następna
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
