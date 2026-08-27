"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import {
  ArrowLeft,
  ArrowRight,
  BriefcaseBusiness,
  Building2,
  CheckCircle2,
  ExternalLink,
  FolderKanban,
  Search,
  Sparkles,
  Star,
  Tags,
  UserRoundCheck,
  Users,
} from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useToast } from "@/components/Toast"
import { StatCard, StatCardGrid } from "@/components/ds"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
  type RecruitmentOperationsProcess,
  type RecruitmentOperationsStageCounts,
} from "@/lib/recruitment-operations-api"
import { useDebouncedValue } from "@/lib/use-debounced-value"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"

const PAGE_SIZE = 50
const NO_FAVORITE = "none"

const STAGES: Array<{
  key: keyof RecruitmentOperationsStageCounts
  label: string
  shortLabel: string
}> = [
  { key: "sourcing", label: "Sourcing", shortLabel: "Source" },
  { key: "verified", label: "Zweryfikowani", shortLabel: "Verified" },
  { key: "recommended", label: "Rekomendowani", shortLabel: "CV sent" },
  { key: "interview", label: "Rozmowy", shortLabel: "Interview" },
  { key: "accepted", label: "Akceptacja", shortLabel: "Accepted" },
]

function friendlyStage(stage: string): string {
  const labels: Record<string, string> = {
    new: "Nowy",
    prep_call: "Przygotowanie rozmowy",
    screening: "Screening",
    verified: "Zweryfikowany",
    interview: "Rozmowa wewnętrzna",
    cv_sent: "CV wysłane",
    client_interview: "Rozmowa u klienta",
    acceptance: "Akceptacja klienta",
    negotiation: "Negocjacje",
    onboarding: "Onboarding",
    hired: "Zatrudniony",
  }
  return labels[stage] ?? stage.replaceAll("_", " ")
}

function processQueryKey({
  preset,
  scopeCacheKey,
  page,
  query,
  categoryId,
}: {
  preset: RecruitmentDashboardPreset
  scopeCacheKey: string
  page: number
  query: string
  categoryId: number | null
}) {
  return [
    "recruitment-operations",
    scopeCacheKey,
    preset,
    "list",
    page,
    query,
    categoryId,
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
            operators: [...scope.allowed_operator_user_ids].sort((a, b) => a - b),
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
          Nie udało się pobrać procesów.
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

export function RecruitmentOperationsKpis({
  preset,
}: {
  preset: RecruitmentDashboardPreset
}) {
  const scopeCacheKey = useRecruitmentOperationsScopeKey()
  const query = useQuery({
    queryKey: ["recruitment-operations", scopeCacheKey, preset, "summary"],
    queryFn: () => getRecruitmentOperations(preset, { page: 1, page_size: 1 }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  if (query.isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-32 rounded-xl" />
        ))}
      </div>
    )
  }

  if (query.isError || !query.data) {
    return <ErrorCard onRetry={() => void query.refetch()} />
  }

  const summary = query.data.summary
  return (
    <StatCardGrid data-testid="recruitment-operations-kpis">
      <StatCard
        label="Otwarte procesy"
        value={summary.open_processes}
        icon={FolderKanban}
        sub="Opublikowane zapytania w Twoim zakresie"
      />
      <StatCard
        label="Kandydaci w procesach"
        value={summary.active_candidates}
        icon={Users}
        sub="Osoby na bieżących etapach zapytań"
      />
      <StatCard
        label="Kategorie kompetencji"
        value={summary.competence_categories}
        icon={Tags}
        sub="Kategorie z otwartymi procesami"
      />
      <StatCard
        label="Bez faworyta"
        value={summary.processes_without_favorite}
        icon={Star}
        sub="Procesy wymagające decyzji"
      />
    </StatCardGrid>
  )
}

function ProcessListItem({
  process,
  selected,
  onSelect,
}: {
  process: RecruitmentOperationsProcess
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "w-full rounded-lg border p-3 text-left transition-colors",
        "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-primary bg-primary/5"
          : "border-border bg-card hover:bg-muted/50",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">
            {process.title}
          </p>
          <p className="mt-1 flex items-center gap-1 truncate text-xs text-muted-foreground">
            <Building2 className="h-3 w-3 shrink-0" />
            {process.client.name}
          </p>
        </div>
        <Badge variant={process.favorite_candidate ? "success" : "warning"} size="sm">
          {process.favorite_candidate ? "Faworyt" : "Brak faworyta"}
        </Badge>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span className="truncate">
          {process.competence_category?.name ?? "Bez kategorii"}
        </span>
        <span className="shrink-0 tabular-nums">
          {process.candidate_count} os.
        </span>
      </div>
    </button>
  )
}

function StageGrid({ counts }: { counts: RecruitmentOperationsStageCounts }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {STAGES.map((stage) => (
        <div key={stage.key} className="rounded-lg border border-border bg-muted/30 p-3">
          <p className="text-2xl font-semibold tabular-nums text-foreground">
            {counts[stage.key]}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{stage.label}</p>
        </div>
      ))}
    </div>
  )
}

function Owners({ process }: { process: RecruitmentOperationsProcess }) {
  const roles = [
    ["Rekruter", process.owners.recruiter?.name],
    ["TAC", process.owners.tac?.name],
    ["Delivery Lead", process.owners.delivery_lead?.name],
  ] as const

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {roles.map(([label, name]) => (
        <div key={label}>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-sm font-medium text-foreground">
            {name ?? "Nieprzypisany"}
          </p>
        </div>
      ))}
      {process.owners.collaborators.length ? (
        <div className="sm:col-span-3">
          <p className="text-xs text-muted-foreground">Współpracownicy</p>
          <p className="mt-1 text-sm text-foreground">
            {process.owners.collaborators.map((person) => person.name).join(", ")}
          </p>
        </div>
      ) : null}
    </div>
  )
}

function ProcessDetail({
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
      showSuccess("Faworyt procesu został zapisany.")
    },
    onError: () => {
      showError("Nie udało się zapisać faworyta procesu.")
    },
  })

  if (query.isLoading) {
    return <Skeleton className="h-[560px] w-full rounded-xl" />
  }
  if (query.isError || !query.data) {
    return <ErrorCard onRetry={() => void query.refetch()} />
  }

  const detail = query.data
  const process = detail.process
  const favoriteValue = process.favorite_candidate
    ? String(process.favorite_candidate.id)
    : NO_FAVORITE

  return (
    <Card className="min-w-0">
      <CardHeader className="gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>{process.title}</CardTitle>
              {process.competence_category ? (
                <Badge variant="soft" size="sm">
                  {process.competence_category.name}
                </Badge>
              ) : null}
            </div>
            <CardDescription className="mt-1">
              {process.client.name} · {process.candidate_count} kandydatów na etapach
            </CardDescription>
          </div>
          <Link
            href={process.href}
            className={buttonVariants({ size: "sm", variant: "outline" })}
          >
            Otwórz proces
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        <section aria-labelledby="process-stages-heading">
          <h3 id="process-stages-heading" className="mb-3 text-sm font-semibold text-foreground">
            Kandydaci na etapach
          </h3>
          <StageGrid counts={process.stage_counts} />
        </section>

        <section className="grid gap-4 border-t border-border pt-5 lg:grid-cols-2">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <UserRoundCheck className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold text-foreground">
                Odpowiedzialność
              </h3>
            </div>
            <Owners process={process} />
          </div>

          <div>
            <div className="mb-3 flex items-center gap-2">
              <Star className="h-4 w-4 text-amber-500" />
              <h3 className="text-sm font-semibold text-foreground">
                Faworyt procesu
              </h3>
            </div>
            <Select
              value={favoriteValue}
              disabled={favoriteMutation.isPending || !detail.can_edit_favorite}
              onValueChange={(value) =>
                favoriteMutation.mutate(value === NO_FAVORITE ? null : Number(value))
              }
            >
              <SelectTrigger aria-label="Faworyt procesu">
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
                ? "Wybór jest ręczny i widoczny dla całego zespołu procesu."
                : "Faworyta może zmienić właściciel procesu, Delivery Lead, Head of Recruitment lub administrator."}
            </p>
          </div>
        </section>

        <section className="border-t border-border pt-5" aria-labelledby="similar-processes-heading">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <h3 id="similar-processes-heading" className="text-sm font-semibold text-foreground">
                  Podobne procesy
                </h3>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Możesz wykorzystać tych samych kandydatów — system niczego nie wysyła automatycznie.
              </p>
            </div>
          </div>

          {detail.similarity_status === "degraded" ? (
            <p className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-800">
              Podobieństwo jest chwilowo niedostępne. To nie oznacza braku podobnych procesów.
            </p>
          ) : detail.similar_processes.length ? (
            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              {detail.similar_processes.map((similar) => (
                <Link
                  key={similar.job_id}
                  href={similar.href}
                  className="rounded-lg border border-border p-3 transition-colors hover:bg-muted/50 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
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
                    {similar.candidate_overlap} wspólnych kandydatów
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted-foreground">
              Brak podobnych procesów powyżej 60% w Twoim zakresie.
            </p>
          )}
        </section>
      </CardContent>
    </Card>
  )
}

export function RecruitmentOperationsDashboard({
  preset,
}: {
  preset: RecruitmentDashboardPreset
}) {
  const scopeCacheKey = useRecruitmentOperationsScopeKey()
  const [search, setSearch] = useState("")
  const deferredSearch = useDebouncedValue(search.trim(), 300)
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)

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

  const items = useMemo(() => query.data?.items ?? [], [query.data?.items])
  useEffect(() => {
    if (!items.length) {
      setSelectedJobId(null)
      return
    }
    if (!selectedJobId || !items.some((item) => item.job_id === selectedJobId)) {
      setSelectedJobId(items[0].job_id)
    }
  }, [items, selectedJobId])

  if (query.isError) {
    return <ErrorCard onRetry={() => void query.refetch()} />
  }

  const totalPages = query.data
    ? Math.max(1, Math.ceil(query.data.total / query.data.page_size))
    : 1

  return (
    <div className="space-y-4" data-testid="recruitment-operations-dashboard">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative min-w-0 flex-1 lg:max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Szukaj procesu lub klienta…"
            aria-label="Szukaj procesu lub klienta"
            className="pl-9"
          />
        </div>

        <div className="flex max-w-full gap-2 overflow-x-auto pb-1">
          <Button
            type="button"
            size="sm"
            variant={categoryId === null ? "primary" : "outline"}
            onClick={() => setCategoryId(null)}
            className="shrink-0"
          >
            Wszystkie
            {query.data ? ` (${query.data.summary.open_processes})` : ""}
          </Button>
          {query.data?.categories
            .filter((category) => category.id !== null)
            .map((category) => (
              <Button
                key={category.id}
                type="button"
                size="sm"
                variant={categoryId === category.id ? "primary" : "outline"}
                onClick={() => setCategoryId(category.id)}
                className="shrink-0"
              >
                {category.name} ({category.total})
              </Button>
            ))}
        </div>
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Card className="h-fit xl:sticky xl:top-24">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">Otwarte procesy</CardTitle>
                <CardDescription>
                  {query.data ? `${query.data.total} w Twoim zakresie` : "Ładowanie…"}
                </CardDescription>
              </div>
              <BriefcaseBusiness className="h-5 w-5 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="max-h-[38rem] space-y-2 overflow-y-auto xl:max-h-[calc(100vh-14rem)]">
            {query.isLoading ? (
              Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-24 rounded-lg" />
              ))
            ) : items.length ? (
              items.map((process) => (
                <ProcessListItem
                  key={process.job_id}
                  process={process}
                  selected={process.job_id === selectedJobId}
                  onSelect={() => setSelectedJobId(process.job_id)}
                />
              ))
            ) : (
              <div className="py-8 text-center">
                <CheckCircle2 className="mx-auto h-8 w-8 text-muted-foreground" />
                <p className="mt-3 text-sm font-medium text-foreground">
                  Brak procesów
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Zmień filtr albo wyszukiwaną frazę.
                </p>
              </div>
            )}

            {query.data && totalPages > 1 ? (
              <div className="flex items-center justify-between border-t border-border pt-3">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  <ArrowLeft className="h-4 w-4" />
                  Wstecz
                </Button>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {page} / {totalPages}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={page >= totalPages}
                  onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                >
                  Dalej
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>

        {selectedJobId ? (
          <ProcessDetail jobId={selectedJobId} preset={preset} />
        ) : query.isLoading ? (
          <Skeleton className="h-[560px] w-full rounded-xl" />
        ) : (
          <Card>
            <CardContent className="flex min-h-64 items-center justify-center p-6 text-center text-sm text-muted-foreground">
              Wybierz proces, aby zobaczyć etapy, faworyta i podobne zapytania.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
