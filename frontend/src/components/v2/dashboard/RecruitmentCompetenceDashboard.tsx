"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  Search,
  Shuffle,
  Sparkles,
  Star,
  UsersRound,
} from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useToast } from "@/components/Toast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  getRecruitmentOperation,
  getRecruitmentOperations,
  setRecruitmentOperationFavorite,
  type RecruitmentDashboardPreset,
  type RecruitmentOperationsCategory,
  type RecruitmentOperationsPerson,
  type RecruitmentOperationsProcess,
  type RecruitmentOperationsStageCounts,
} from "@/lib/recruitment-operations-api"
import { useDebouncedValue } from "@/lib/use-debounced-value"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"

const PAGE_SIZE = 50
const NO_FAVORITE = "none"
const ALL_CATEGORIES = "all"

const STAGES: Array<{
  key: keyof RecruitmentOperationsStageCounts
  label: string
}> = [
  { key: "new", label: "Nowy" },
  { key: "screening", label: "Screening" },
  { key: "cv_sent", label: "Wysłany do klienta" },
  { key: "client_interview", label: "Interview" },
  { key: "acceptance", label: "Akceptacje" },
]

function friendlyStage(stage: string): string {
  const labels: Record<string, string> = {
    new: "Nowy",
    prep_call: "Przygotowanie rozmowy",
    screening: "Screening",
    verified: "Zweryfikowany",
    interview: "Rozmowa wewnętrzna",
    cv_sent: "Wysłany do klienta",
    client_interview: "Interview",
    acceptance: "Akceptacja klienta",
    negotiation: "Negocjacje",
    onboarding: "Onboarding",
    hired: "Zatrudniony",
  }
  return labels[stage] ?? stage.replaceAll("_", " ")
}

function sharedCandidateLabel(count: number): string {
  return count === 1 ? "1 wspólny kandydat" : `${count} wspólnych kandydatów`
}

function processQueryKey({
  preset,
  scopeCacheKey,
  page,
  query,
  categoryId,
  mineOnly = false,
}: {
  preset: RecruitmentDashboardPreset
  scopeCacheKey: string
  page: number
  query: string
  categoryId: number | null
  mineOnly?: boolean
}) {
  return [
    "recruitment-operations",
    scopeCacheKey,
    preset,
    "competence-list",
    page,
    query,
    categoryId,
    mineOnly,
  ] as const
}

function useRecruitmentOperationsScopeKey(): string {
  const user = useAuthStore((state) => state.user)
  return useMemo(() => {
    if (!user) return "anonymous"
    const scope = user.data_scope
    return JSON.stringify({
      userId: user.id,
      authorizationVersion: user.authorization_version ?? null,
      roles: Array.from(new Set([user.role, ...(user.roles ?? [])])).sort(),
      scope: scope
        ? {
            kind: scope.kind,
            userId: scope.user_id,
            clients: [...scope.allowed_client_ids].sort((a, b) => a - b),
            tacs: [...scope.allowed_tac_user_ids].sort((a, b) => a - b),
            operators: [...scope.allowed_operator_user_ids].sort(
              (a, b) => a - b,
            ),
            pairs: [...(scope.allowed_client_tac_pairs ?? [])].sort(
              (a, b) =>
                a.client_id - b.client_id || a.tac_user_id - b.tac_user_id,
            ),
          }
        : null,
    })
  }, [user])
}

function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-start gap-3 p-5">
        <p className="text-sm font-medium text-foreground">
          Nie udało się pobrać rekrutacji.
        </p>
        <p className="text-xs text-muted-foreground">
          Spróbuj ponownie. Jeśli problem wraca, sprawdź uprawnienia do tego
          widoku.
        </p>
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          Ponów
        </Button>
      </CardContent>
    </Card>
  )
}

function StageGrid({ counts }: { counts: RecruitmentOperationsStageCounts }) {
  return (
    <div
      className="grid grid-cols-2 gap-2 sm:grid-cols-5"
      aria-label="Kandydaci według aktualnego statusu lejka"
    >
      {STAGES.map((stage) => {
        const count = counts[stage.key]
        return (
          <div
            key={stage.key}
            className={cn(
              "min-w-0 rounded-md border px-2.5 py-2",
              count > 0
                ? "border-primary/20 bg-primary/5"
                : "border-border bg-muted/20",
            )}
          >
            <p className="text-base font-semibold tabular-nums text-foreground">
              {count}
            </p>
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {stage.label}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("")
}

function Owners({ process }: { process: RecruitmentOperationsProcess }) {
  const people: Array<{
    role: string
    person: RecruitmentOperationsPerson
  }> = []
  if (process.owners.recruiter) {
    people.push({ role: "Rekruter", person: process.owners.recruiter })
  }
  if (process.owners.tac) {
    people.push({ role: "TAC", person: process.owners.tac })
  }
  if (process.owners.delivery_lead) {
    people.push({
      role: "Delivery Lead",
      person: process.owners.delivery_lead,
    })
  }
  process.owners.collaborators.forEach((person) => {
    people.push({ role: "Współpraca", person })
  })

  if (!people.length) {
    return (
      <Badge variant="warning" size="sm">
        Brak przypisanych
      </Badge>
    )
  }

  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Przypisani do rekrutacji">
      {people.map(({ role, person }) => (
        <span
          key={`${role}-${person.id}`}
          title={`${role}: ${person.name}`}
          className="inline-flex min-w-0 items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs text-foreground"
        >
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary">
            {initials(person.name)}
          </span>
          <span className="max-w-32 truncate">{person.name}</span>
        </span>
      ))}
    </div>
  )
}

function ProcessExpandedDetail({
  jobId,
  preset,
}: {
  jobId: number
  preset: RecruitmentDashboardPreset
}) {
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const scopeCacheKey = useRecruitmentOperationsScopeKey()
  const query = useQuery({
    queryKey: ["recruitment-operations", scopeCacheKey, preset, "detail", jobId],
    queryFn: () => getRecruitmentOperation(preset, jobId),
    staleTime: 30_000,
  })
  const favoriteMutation = useMutation({
    mutationFn: (candidateId: number | null) =>
      setRecruitmentOperationFavorite(preset, jobId, candidateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["recruitment-operations", scopeCacheKey, preset],
      })
      showSuccess("Faworyt rekrutacji został zapisany.")
    },
    onError: () => {
      showError("Nie udało się zapisać faworyta rekrutacji.")
    },
  })

  if (query.isLoading) {
    return <Skeleton className="h-48 w-full rounded-none" />
  }
  if (query.isError || !query.data) {
    return (
      <div className="border-t border-border p-4">
        <ErrorCard onRetry={() => void query.refetch()} />
      </div>
    )
  }

  const detail = query.data
  const process = detail.process
  const favoriteValue = process.favorite_candidate
    ? String(process.favorite_candidate.id)
    : NO_FAVORITE

  return (
    <div className="grid gap-6 border-t border-border bg-muted/20 p-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.7fr)]">
      <section aria-labelledby={`favorite-heading-${jobId}`}>
        <div className="mb-3 flex items-center gap-2">
          <Star className="h-4 w-4 text-primary" />
          <h4
            id={`favorite-heading-${jobId}`}
            className="text-sm font-semibold text-foreground"
          >
            Faworyt rekrutacji
          </h4>
        </div>
        <Select
          value={favoriteValue}
          disabled={favoriteMutation.isPending || !detail.can_edit_favorite}
          onValueChange={(value) =>
            favoriteMutation.mutate(value === NO_FAVORITE ? null : Number(value))
          }
        >
          <SelectTrigger aria-label="Faworyt rekrutacji">
            <SelectValue placeholder="Wybierz kandydata" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_FAVORITE}>Brak faworyta</SelectItem>
            {detail.favorite_options.map((candidate) => (
              <SelectItem key={candidate.id} value={String(candidate.id)}>
                {candidate.name} · {friendlyStage(candidate.stage)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="mt-2 text-xs text-muted-foreground">
          {detail.can_edit_favorite
            ? "Ręczny wybór widoczny dla zespołu rekrutacji."
            : "Zmiana jest dostępna dla właściciela, Delivery Leada, HoR lub administratora."}
        </p>
      </section>

      <section aria-labelledby={`similar-recruitments-heading-${jobId}`}>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h4
            id={`similar-recruitments-heading-${jobId}`}
            className="text-sm font-semibold text-foreground"
          >
            Podobne rekrutacje
          </h4>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Podobny profil rekrutacji i osoby obecne w obu procesach. Wynik nie
          oznacza automatycznego dopasowania kandydata.
        </p>

        {detail.similarity_status === "degraded" ? (
          <p className="mt-3 rounded-lg border border-warning/30 bg-warning-muted p-3 text-sm text-warning-muted-foreground">
            Podobieństwo jest chwilowo niedostępne. To nie oznacza braku
            podobnych rekrutacji.
          </p>
        ) : detail.similar_processes.length ? (
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {detail.similar_processes.map((similar) => (
              <Link
                key={similar.job_id}
                href={similar.href}
                className="rounded-lg border border-border bg-card p-3 transition-colors hover:bg-muted/50 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="line-clamp-2 text-sm font-medium text-foreground">
                    {similar.title}
                  </p>
                  <Badge variant="soft" size="sm">
                    {Math.round(similar.similarity * 100)}%
                  </Badge>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {similar.client.name}
                </p>
                <p className="mt-3 text-xs font-medium text-foreground">
                  {sharedCandidateLabel(similar.candidate_overlap)}
                </p>
              </Link>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">
            Brak podobnych rekrutacji powyżej 60% w Twoim zakresie.
          </p>
        )}
      </section>
    </div>
  )
}

function ProcessRow({
  process,
  preset,
}: {
  process: RecruitmentOperationsProcess
  preset: RecruitmentDashboardPreset
}) {
  const [open, setOpen] = useState(false)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <article>
        <div className="grid min-w-0 gap-4 p-4 lg:grid-cols-[minmax(190px,0.8fr)_minmax(330px,1.5fr)_minmax(230px,1fr)] lg:items-start">
          <div className="min-w-0">
            <div className="flex flex-wrap items-start gap-2">
              <Link
                href={process.href}
                className="min-w-0 font-semibold text-foreground hover:text-primary hover:underline focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                {process.title}
              </Link>
              <Badge
                variant={process.favorite_candidate ? "success" : "warning"}
                size="sm"
              >
                {process.favorite_candidate ? "Ma faworyta" : "Brak faworyta"}
              </Badge>
            </div>
            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Building2 className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{process.client.name}</span>
              <span aria-hidden="true">·</span>
              <span className="shrink-0 tabular-nums">
                {process.candidate_count} os.
              </span>
            </p>

            <div className="mt-3">
              <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Przypisani
              </p>
              <Owners process={process} />
            </div>
          </div>

          <StageGrid counts={process.stage_counts} />

          <div className="flex min-w-0 flex-col gap-3">
            <div className="flex items-start gap-2">
              <Star
                className={cn(
                  "mt-0.5 h-4 w-4 shrink-0",
                  process.favorite_candidate
                    ? "text-success"
                    : "text-warning",
                )}
              />
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Faworyt</p>
                <p className="truncate text-sm font-medium text-foreground">
                  {process.favorite_candidate?.name ?? "Nie wybrano"}
                </p>
              </div>
            </div>

            <div className="flex items-start gap-2">
              <UsersRound className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-medium text-foreground">
                  {sharedCandidateLabel(process.shared_candidate_count)}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {process.shared_candidate_count > 0
                    ? "Już w więcej niż jednej rekrutacji"
                    : "Brak osób wspólnych z innymi rekrutacjami"}
                </p>
              </div>
            </div>

            <CollapsibleTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="w-fit px-0 text-primary hover:bg-transparent hover:underline"
                aria-label={`${open ? "Ukryj" : "Pokaż"} szczegóły rekrutacji ${process.title}`}
              >
                {open ? "Ukryj szczegóły" : "Podobne i faworyt"}
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform",
                    open && "rotate-180",
                  )}
                />
              </Button>
            </CollapsibleTrigger>
          </div>
        </div>

        <CollapsibleContent>
          {open ? (
            <ProcessExpandedDetail jobId={process.job_id} preset={preset} />
          ) : null}
        </CollapsibleContent>
      </article>
    </Collapsible>
  )
}

export function MyAssignedRecruitments({
  preset,
}: {
  preset: RecruitmentDashboardPreset
}) {
  const [open, setOpen] = useState(true)
  const scopeCacheKey = useRecruitmentOperationsScopeKey()
  const query = useQuery({
    queryKey: processQueryKey({
      preset,
      scopeCacheKey,
      page: 1,
      query: "",
      categoryId: null,
      mineOnly: true,
    }),
    queryFn: () =>
      getRecruitmentOperations(preset, {
        page: 1,
        page_size: 100,
        mine_only: true,
      }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  return (
    <section
      aria-labelledby="my-assigned-recruitments-heading"
      data-testid="my-assigned-recruitments"
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <Card className="overflow-hidden p-0">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 bg-card p-4 text-left transition-colors hover:bg-muted/40 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <ClipboardList className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span
                    id="my-assigned-recruitments-heading"
                    className="block text-base font-semibold text-foreground"
                  >
                    Moje przypisane rekrutacje
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    Jako rekruter, TAC, Delivery Lead lub współpracownik
                  </span>
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                {query.data ? (
                  <Badge variant="soft" size="sm">
                    {query.data.total}
                  </Badge>
                ) : null}
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    open && "rotate-180",
                  )}
                />
              </span>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="border-t border-border">
              {query.isLoading ? (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 2 }).map((_, index) => (
                    <Skeleton key={index} className="h-32 w-full" />
                  ))}
                </div>
              ) : query.isError ? (
                <div className="p-4">
                  <ErrorCard onRetry={() => void query.refetch()} />
                </div>
              ) : query.data?.items.length ? (
                <>
                  <div className="divide-y divide-border">
                    {query.data.items.map((process) => (
                      <ProcessRow
                        key={process.job_id}
                        process={process}
                        preset={preset}
                      />
                    ))}
                  </div>
                  {query.data.total > query.data.items.length ? (
                    <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
                      Pokazano pierwsze {query.data.items.length} z {query.data.total}
                      przypisań.
                    </p>
                  ) : null}
                </>
              ) : (
                <div className="px-4 py-8 text-center">
                  <p className="text-sm font-medium text-foreground">
                    Brak przypisanych rekrutacji
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Sekcja pokaże rekrutacje, gdy pojawisz się w ich zespole.
                  </p>
                </div>
              )}
            </div>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </section>
  )
}

interface CategoryGroupData {
  category: RecruitmentOperationsCategory
  processes: RecruitmentOperationsProcess[]
}

function CategoryGroup({
  group,
  preset,
  defaultOpen,
}: {
  group: CategoryGroupData
  preset: RecruitmentDashboardPreset
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const { category, processes } = group

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className="overflow-hidden p-0">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full flex-col gap-3 bg-muted/30 px-4 py-3 text-left transition-colors hover:bg-muted/60 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="flex min-w-0 items-center gap-2.5">
              <ChevronDown
                className={cn(
                  "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                  !open && "-rotate-90",
                )}
              />
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-foreground">
                  {category.name}
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {processes.length === category.total
                    ? `Rekrutacje: ${category.total}`
                    : `Na tej stronie: ${processes.length} z ${category.total}`}
                </span>
              </span>
            </span>
            <span className="flex flex-wrap gap-1.5 pl-6 sm:justify-end sm:pl-0">
              <Badge variant="soft" size="sm">
                {sharedCandidateLabel(category.shared_candidates)}
              </Badge>
              <Badge variant="soft" size="sm">
                {category.processes_with_shared_candidates} ze wspólnymi
              </Badge>
            </span>
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          {category.shared_candidates > 0 ? (
            <div className="flex flex-col gap-2 border-t border-border bg-primary/5 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <span className="flex items-center gap-2 text-foreground">
                <Shuffle className="h-4 w-4 shrink-0 text-primary" />
                <span>
                  <strong>{sharedCandidateLabel(category.shared_candidates)}</strong>{" "}
                  {category.shared_candidates === 1 ? "jest" : "są"} już w więcej
                  niż jednej rekrutacji.
                </span>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                Rekrutacje z pokryciem: {category.processes_with_shared_candidates}
              </span>
            </div>
          ) : null}

          <div className="divide-y divide-border">
            {processes.map((process) => (
              <ProcessRow key={process.job_id} process={process} preset={preset} />
            ))}
          </div>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}

export function RecruitmentCompetenceDashboard({
  preset,
}: {
  preset: RecruitmentDashboardPreset
}) {
  const scopeCacheKey = useRecruitmentOperationsScopeKey()
  const [search, setSearch] = useState("")
  const deferredSearch = useDebouncedValue(search.trim(), 300)
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [page, setPage] = useState(1)

  useEffect(() => {
    setSearch("")
    setCategoryId(null)
    setPage(1)
  }, [preset, scopeCacheKey])

  useEffect(() => {
    setPage(1)
  }, [deferredSearch, categoryId])

  const query = useQuery({
    queryKey: processQueryKey({
      preset,
      scopeCacheKey,
      page,
      query: deferredSearch,
      categoryId,
    }),
    queryFn: () =>
      getRecruitmentOperations(preset, {
        page,
        page_size: PAGE_SIZE,
        q: deferredSearch || undefined,
        category_id: categoryId,
      }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const groups = useMemo<CategoryGroupData[]>(() => {
    const data = query.data
    if (!data) return []

    const categoryByKey = new Map(
      data.categories.map((category) => [
        String(category.id ?? "uncategorized"),
        category,
      ]),
    )
    const processesByKey = new Map<string, RecruitmentOperationsProcess[]>()

    for (const process of data.items) {
      const key = String(process.competence_category?.id ?? "uncategorized")
      const existing = processesByKey.get(key) ?? []
      existing.push(process)
      processesByKey.set(key, existing)
    }

    return Array.from(processesByKey.entries())
      .map(([key, processes]) => ({
        category:
          categoryByKey.get(key) ??
          ({
            id: processes[0]?.competence_category?.id ?? null,
            name:
              processes[0]?.competence_category?.name ??
              "Bez kategorii kompetencji",
            total: processes.length,
            shared_candidates: 0,
            processes_with_shared_candidates: 0,
          } satisfies RecruitmentOperationsCategory),
        processes,
      }))
      .sort((left, right) => {
        const leftIndex = data.categories.findIndex(
          (category) => category.id === left.category.id,
        )
        const rightIndex = data.categories.findIndex(
          (category) => category.id === right.category.id,
        )
        return (
          (leftIndex < 0 ? Number.MAX_SAFE_INTEGER : leftIndex) -
          (rightIndex < 0 ? Number.MAX_SAFE_INTEGER : rightIndex)
        )
      })
  }, [query.data])

  if (query.isError) {
    return <ErrorCard onRetry={() => void query.refetch()} />
  }

  const totalPages = query.data
    ? Math.max(1, Math.ceil(query.data.total / query.data.page_size))
    : 1

  return (
    <section
      className="space-y-4"
      data-testid="recruitment-competence-dashboard"
      aria-labelledby="recruitment-competence-heading"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2
            id="recruitment-competence-heading"
            className="text-lg font-semibold text-foreground"
          >
            Rekrutacje według kompetencji
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Aktualne statusy kandydatów w lejku. Niżej: przypisani, faworyci i
            osoby obecne w kilku rekrutacjach.
          </p>
        </div>
        {query.data ? (
          <Badge variant="soft" size="md">
            Otwarte: {query.data.total} · Kategorie: {query.data.categories.length}
          </Badge>
        ) : null}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative min-w-0 flex-1 sm:max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Szukaj rekrutacji lub klienta…"
            aria-label="Szukaj rekrutacji lub klienta"
            className="pl-9"
          />
        </div>
        <Select
          value={categoryId === null ? ALL_CATEGORIES : String(categoryId)}
          onValueChange={(value) =>
            setCategoryId(value === ALL_CATEGORIES ? null : Number(value))
          }
        >
          <SelectTrigger
            className="w-full sm:w-64"
            aria-label="Kategoria kompetencji"
          >
            <SelectValue placeholder="Wszystkie kompetencje" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_CATEGORIES}>Wszystkie kompetencje</SelectItem>
            {query.data?.categories
              .filter((category) => category.id !== null)
              .map((category) => (
                <SelectItem key={category.id} value={String(category.id)}>
                  {category.name} ({category.total})
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>

      {query.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : groups.length ? (
        <div className="space-y-3">
          {groups.map((group, index) => (
            <CategoryGroup
              key={group.category.id ?? "uncategorized"}
              group={group}
              preset={preset}
              defaultOpen={groups.length <= 2 || index < 2}
            />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-10 text-center">
            <CheckCircle2 className="mx-auto h-8 w-8 text-muted-foreground" />
            <p className="mt-3 text-sm font-medium text-foreground">
              Brak rekrutacji
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Zmień filtr albo wyszukiwaną frazę.
            </p>
          </CardContent>
        </Card>
      )}

      {query.data && totalPages > 1 ? (
        <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            <ArrowLeft className="h-4 w-4" />
            Wstecz
          </Button>
          <span className="px-2 text-xs tabular-nums text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={page >= totalPages}
            onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
          >
            Dalej
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      ) : null}
    </section>
  )
}
