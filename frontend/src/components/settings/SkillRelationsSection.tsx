"use client";

/**
 * Słownik umiejętności → „Powiązania” (mapa wiedzy IT, 07.11.2026).
 *
 * „Wynika z” i „część” spełniają wymaganie wszędzie (Spring Boot ⇒ Java,
 * GitHub ⇒ Git), zamiennik i „typowe” dają pytanie do rozmowy. Powiązania
 * proponuje i zatwierdza nocny bieg (dane z profili, słowniczek, model —
 * decyzja Artura z 07.11.2026 „wszystko zatwierdź sam”). Tu widać, co działa,
 * i można powiązanie wycofać.
 */

import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { skillsAdminApi, type SkillRelation, type SkillRelationKind } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

const PAGE_SIZE = 50;

export const skillRelationsQueryKey = ["skills-admin", "relations"] as const;

export const RELATION_LABEL: Record<SkillRelationKind, string> = {
  implies: "wynika z",
  part_of: "część",
  alternative: "zamiennik",
  typical: "typowe",
};

const RELATION_ARROW: Record<SkillRelationKind, string> = {
  implies: "⇒",
  part_of: "⇒",
  alternative: "~",
  typical: "→",
};

const RELATION_TONE: Record<SkillRelationKind, string> = {
  implies: "bg-success-muted text-success-muted-foreground",
  part_of: "bg-success-muted text-success-muted-foreground",
  alternative: "bg-warning-muted text-warning-muted-foreground",
  typical: "bg-warning-muted text-warning-muted-foreground",
};

const RELATION_HELP: Record<SkillRelationKind, string> = {
  implies: "Spełnia wymaganie wszędzie: wyszukiwanie, bramka krytycznych, QC, przegląd DL.",
  part_of: "Spełnia wymaganie wszędzie, jak „wynika z”.",
  alternative: "Nie spełnia wymagania, ale osoba zostaje widoczna z pytaniem do rozmowy.",
  typical: "Nie spełnia wymagania — QC i ściąga podpowiadają pytanie do rozmowy.",
};

type KindFilter = "all" | SkillRelationKind;

function RelationRow({
  relation,
  onWithdraw,
  busy,
}: {
  relation: SkillRelation;
  onWithdraw: (relation: SkillRelation) => void;
  busy: boolean;
}) {
  const share =
    relation.share === null ? null : `${Math.round(relation.share * 100)}% z ${relation.support.toLocaleString("pl-PL")} profili`;
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 px-3 py-2.5">
      <div className="min-w-0 space-y-0.5">
        <p className="flex flex-wrap items-center gap-2 font-medium text-foreground">
          <span>
            {relation.from.name} {RELATION_ARROW[relation.kind]} {relation.to.name}
          </span>
          <span
            className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", RELATION_TONE[relation.kind])}
            title={RELATION_HELP[relation.kind]}
          >
            {RELATION_LABEL[relation.kind]}
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          {[share, relation.reason, relation.source === "glossary" ? "słowniczek „po ludzku”" : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      {relation.status === "accepted" ? (
        <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => onWithdraw(relation)}>
          Wycofaj
        </Button>
      ) : null}
    </li>
  );
}

export function SkillRelationsSection() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [kind, setKind] = useState<KindFilter>("all");
  const [page, setPage] = useState(0);
  const query = useQuery({
    queryKey: [...skillRelationsQueryKey, kind, page],
    queryFn: () =>
      skillsAdminApi.relations({
        status: "accepted",
        kind: kind === "all" ? undefined : kind,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });
  const withdraw = useMutation({
    mutationFn: (relation: SkillRelation) => skillsAdminApi.withdrawRelation(relation.id),
    onSuccess: () => {
      toast.showSuccess("Powiązanie wycofane — nie wróci w nocnym biegu");
      void queryClient.invalidateQueries({ queryKey: skillRelationsQueryKey });
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się wycofać powiązania")),
  });
  const data = query.data;
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: (data?.items.length ?? 0) === 0,
    isSuccess: query.isSuccess,
  });
  const lastPage = Math.max(0, Math.ceil((data?.total ?? 0) / PAGE_SIZE) - 1);

  const ask = async (relation: SkillRelation) => {
    const ok = await askConfirm({
      title: `Wycofać „${relation.from.name} ${RELATION_ARROW[relation.kind]} ${relation.to.name}”?`,
      description:
        "Powiązanie przestanie działać w wyszukiwaniu, bramce krytycznych, QC i generatorze CV. " +
        "Nocny bieg go nie przywróci.",
      confirmLabel: "Wycofaj",
    });
    if (ok) withdraw.mutate(relation);
  };

  return (
    <section aria-label="Powiązania haseł" className="space-y-3" data-testid="skill-relations">
      {confirmDialog}
      <p className="text-sm text-muted-foreground">
        Co z czego wynika. „Wynika z” i „część” spełniają wymaganie wszędzie (Spring Boot ⇒ Java,
        GitHub ⇒ Git), zamiennik i „typowe” dają pytanie do rozmowy. Powiązania liczy i zatwierdza
        nocny bieg z danych profili, słowniczka i oceny modelu
        {data ? ` — działa ${data.totals.accepted.toLocaleString("pl-PL")}` : ""}.
      </p>
      <SegmentedRadio
        label="Rodzaj powiązania"
        value={kind}
        onChange={(value) => {
          setKind(value as KindFilter);
          setPage(0);
        }}
        options={[
          { value: "all", label: "Wszystkie" },
          { value: "implies", label: "Wynika z" },
          { value: "part_of", label: "Część" },
          { value: "alternative", label: "Zamienniki" },
          { value: "typical", label: "Typowe" },
        ]}
      />
      {viewState === "loading" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Ładowanie powiązań…
        </p>
      ) : null}
      {viewState === "error" || viewState === "forbidden" ? (
        <QueryStateNotice state={viewState} onRetry={() => void query.refetch()} />
      ) : null}
      {viewState === "empty" ? (
        <p className="text-sm text-muted-foreground">
          Jeszcze nie ma powiązań tego rodzaju — pojawią się po nocnym biegu.
        </p>
      ) : null}
      {viewState === "ready" && data ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {data.items.map((relation) => (
            <RelationRow
              key={relation.id}
              relation={relation}
              onWithdraw={(r) => void ask(r)}
              busy={withdraw.isPending}
            />
          ))}
        </ul>
      ) : null}
      {lastPage > 0 ? (
        <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
          <Button type="button" size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Poprzednia
          </Button>
          <span>
            {page + 1} / {lastPage + 1}
          </span>
          <Button type="button" size="sm" variant="outline" disabled={page >= lastPage} onClick={() => setPage((p) => p + 1)}>
            Następna
          </Button>
        </div>
      ) : null}
    </section>
  );
}
