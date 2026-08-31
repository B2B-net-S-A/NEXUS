"use client"

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Crown, Info, Save } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import api from "@/lib/api"
import { cn } from "@/lib/utils"
import { hasRole, useAuthStore } from "@/store/auth"

// ── Types ─────────────────────────────────────────────────────────────────────

interface UserBrief {
  id: number
  name: string
  email?: string
  role?: string
  roles?: string[]
}

interface Category {
  id: number
  slug: string
  name_pl: string
  name_en: string
}

interface AssignedOperator {
  user_id: number
  name: string
  priority: number | null
}

interface SourcerCategoryRow {
  category: Category
  first_priority: AssignedOperator[]
  second_priority: AssignedOperator[]
}

interface DlClientsRow {
  delivery_lead: UserBrief
  clients: Array<{ id: number; name: string; is_head: boolean }>
}

interface TeamStructureSummary {
  categories: SourcerCategoryRow[]
  dl_clients: DlClientsRow[]
  totals: Record<string, number>
}

interface ClientBrief {
  id: number
  name: string
}

interface CompetenceSelection {
  primaryId: number | null
  secondaryIds: number[]
}

const OPERATOR_ROLES = ["sourcer", "tac", "recruiter"]
const DIRECTORY_ROLES = [...OPERATOR_ROLES, "delivery_lead"]

const ROLE_LABELS: Record<string, string> = {
  sourcer: "Sourcer",
  tac: "TAC",
  recruiter: "Rekruter",
}

function operatorRoleLabel(operator: UserBrief): string {
  const roles = new Set([operator.role, ...(operator.roles ?? [])])
  const labels = OPERATOR_ROLES.filter((role) => roles.has(role)).map(
    (role) => ROLE_LABELS[role],
  )

  return labels.join(" / ") || "Zespół rekrutacji"
}

// ── Shared helpers ─────────────────────────────────────────────────────────────

function useInvalidate() {
  const queryClient = useQueryClient()

  return () => {
    queryClient.invalidateQueries({ queryKey: ["team-structure-summary"] })
    queryClient.invalidateQueries({ queryKey: ["admin-team-structure-summary"] })
  }
}

function selectionForOperator(
  userId: number,
  categoryRows: SourcerCategoryRow[],
): CompetenceSelection {
  let primaryId: number | null = null
  const secondaryIds: number[] = []

  for (const row of categoryRows) {
    if (row.first_priority.some((operator) => operator.user_id === userId)) {
      primaryId ??= row.category.id
    }
    if (row.second_priority.some((operator) => operator.user_id === userId)) {
      secondaryIds.push(row.category.id)
    }
  }

  return {
    primaryId,
    secondaryIds: secondaryIds.filter((id) => id !== primaryId),
  }
}

// ── 1. Person-centric competences ──────────────────────────────────────────────

function OperatorCompetenceEditor({
  operator,
  categories,
  initialSelection,
}: {
  operator: UserBrief
  categories: Category[]
  initialSelection: CompetenceSelection
}) {
  const invalidate = useInvalidate()
  const [primaryId, setPrimaryId] = useState<number | null>(
    initialSelection.primaryId,
  )
  const [secondaryIds, setSecondaryIds] = useState(
    () => new Set(initialSelection.secondaryIds),
  )

  const save = useMutation({
    mutationFn: () =>
      api
        .put(`/api/team-structure/operators/${operator.id}/competences`, {
          primary_competence_category_id: primaryId,
          secondary_competence_category_ids: [...secondaryIds].sort(
            (left, right) => left - right,
          ),
        })
        .then((response) => response.data),
    onSuccess: invalidate,
  })

  const selectPrimary = (categoryId: number | null) => {
    setPrimaryId(categoryId)
    if (categoryId !== null) {
      setSecondaryIds((current) => {
        const next = new Set(current)
        next.delete(categoryId)
        return next
      })
    }
    save.reset()
  }

  const toggleSecondary = (categoryId: number) => {
    setSecondaryIds((current) => {
      const next = new Set(current)
      if (next.has(categoryId)) {
        next.delete(categoryId)
      } else {
        next.add(categoryId)
      }
      return next
    })
    save.reset()
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-foreground">{operator.name}</p>
          <p className="text-xs text-muted-foreground">{operator.email}</p>
        </div>
        <Badge variant="soft" size="sm">
          {operatorRoleLabel(operator)}
        </Badge>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(320px,1.2fr)_auto] lg:items-end">
        <div>
          <label
            className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
            htmlFor={`primary-competence-${operator.id}`}
          >
            Kompetencja główna
          </label>
          <select
            id={`primary-competence-${operator.id}`}
            aria-label={`Główna kompetencja — ${operator.name}`}
            className="h-10 w-full rounded-lg border border-border bg-card px-3"
            value={primaryId ?? ""}
            onChange={(event) =>
              selectPrimary(event.target.value ? Number(event.target.value) : null)
            }
          >
            <option value="">Wybierz jedną kategorię</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name_pl}
              </option>
            ))}
          </select>
        </div>

        <fieldset>
          <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Kompetencje dodatkowe
          </legend>
          <div className="flex min-h-10 flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border px-3 py-2">
            {categories.length === 0 ? (
              <span className="text-xs text-muted-foreground">
                Brak aktywnych kategorii
              </span>
            ) : (
              categories.map((category) => {
                const isPrimary = primaryId === category.id
                return (
                  <label
                    key={category.id}
                    className={cn(
                      "flex items-center gap-2 text-sm",
                      isPrimary && "text-muted-foreground",
                    )}
                  >
                    <input
                      type="checkbox"
                      aria-label={`${category.name_pl} jako dodatkowa dla ${operator.name}`}
                      checked={!isPrimary && secondaryIds.has(category.id)}
                      disabled={isPrimary}
                      onChange={() => toggleSecondary(category.id)}
                      className="h-4 w-4"
                    />
                    <span>{category.name_pl}</span>
                  </label>
                )
              })
            )}
          </div>
        </fieldset>

        <Button
          aria-label={`Zapisz kompetencje — ${operator.name}`}
          disabled={primaryId === null || save.isPending}
          onClick={() => save.mutate()}
        >
          <Save className="h-4 w-4" />
          {save.isPending ? "Zapisuję…" : "Zapisz"}
        </Button>
      </div>

      {primaryId === null && (
        <p className="mt-2 text-xs text-amber-700">
          Wybierz dokładnie jedną kompetencję główną, aby zapisać.
        </p>
      )}
      {save.isSuccess && (
        <p className="mt-2 flex items-center gap-1 text-xs text-emerald-700">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Kompetencje zapisane atomowo.
        </p>
      )}
      {save.isError && (
        <p className="mt-2 text-xs text-destructive" role="alert">
          Nie udało się zapisać kompetencji. Spróbuj ponownie.
        </p>
      )}
    </div>
  )
}

function OperatorCompetencesSection({
  summary,
  operators,
}: {
  summary: TeamStructureSummary | undefined
  operators: UserBrief[]
}) {
  const categoryRows = summary?.categories ?? []
  const categories = categoryRows.map((row) => row.category)

  return (
    <Card>
      <CardHeader>
        <CardTitle>1. Kompetencje zespołu rekrutacji</CardTitle>
        <CardDescription>
          Każdy aktywny Sourcer, TAC i Rekruter ma dokładnie jedną kompetencję
          główną oraz dowolną liczbę różnych kompetencji dodatkowych. Cały wybór
          jednej osoby zapisujemy w jednej operacji.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {operators.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            Brak aktywnych Sourcerów, TAC-ów i Rekruterów.
          </p>
        ) : (
          operators.map((operator) => {
            const selection = selectionForOperator(operator.id, categoryRows)
            const selectionKey = `${operator.id}:${selection.primaryId ?? "none"}:${selection.secondaryIds.join(",")}`

            return (
              <OperatorCompetenceEditor
                key={selectionKey}
                operator={operator}
                categories={categories}
                initialSelection={selection}
              />
            )
          })
        )}
      </CardContent>
    </Card>
  )
}

// ── 2. Reporting model ──────────────────────────────────────────────────────────────

function DeliveryLeadReportingInfo() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>2. Zespół Delivery Leada</CardTitle>
        <CardDescription>
          Nie utrzymujemy osobnego, kanonicznego przypisania jednej osoby do
          jednego Delivery Leada.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex gap-3 rounded-xl border border-primary/20 bg-primary/10 p-4">
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div className="space-y-2 text-sm">
            <p className="font-semibold text-foreground">
              Skład zespołu DL wynika z relacji przy kliencie.
            </p>
            <p className="text-muted-foreground">
              System łączy przypisania klient ↔ Delivery Lead z przypisaniami
              klient ↔ TAC. TAC-ów przypisujesz na karcie klienta, a Delivery
              Leadów w sekcji poniżej. Sourcerzy, TAC-y i Rekruterzy raportują
              organizacyjnie do Head of Recruitment.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── 3. DL → Clients ──────────────────────────────────────────────────────────────────────

function DlClientsSection({
  summary,
  dls,
  clients,
}: {
  summary: TeamStructureSummary | undefined
  dls: UserBrief[]
  clients: ClientBrief[]
}) {
  const invalidate = useInvalidate()
  const [form, setForm] = useState({
    delivery_lead_user_id: "",
    client_id: "",
    is_head: false,
  })

  const assign = useMutation({
    mutationFn: (body: {
      delivery_lead_user_id: number
      client_id: number
      is_head: boolean
    }) => api.post("/api/team-structure/dl-clients", body).then((r) => r.data),
    onSuccess: () => {
      invalidate()
      setForm({ delivery_lead_user_id: "", client_id: "", is_head: false })
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>3. Delivery Lead → Klienci</CardTitle>
        <CardDescription>
          Przypisz DL do klientów. Zaznacz <span className="font-semibold">Head</span>{" "}
          dla głównego opiekuna (maksymalnie jeden na klienta).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3 rounded-lg bg-primary/10 p-3">
          <div className="min-w-[180px] flex-1">
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Delivery Lead
            </label>
            <select
              aria-label="Delivery Lead do przypisania"
              className="h-10 w-full rounded-lg border border-border bg-card px-3"
              value={form.delivery_lead_user_id}
              onChange={(event) =>
                setForm({ ...form, delivery_lead_user_id: event.target.value })
              }
            >
              <option value="">—</option>
              {dls.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name}
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-[180px] flex-1">
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Klient
            </label>
            <select
              aria-label="Klient do przypisania Delivery Leada"
              className="h-10 w-full rounded-lg border border-border bg-card px-3"
              value={form.client_id}
              onChange={(event) =>
                setForm({ ...form, client_id: event.target.value })
              }
            >
              <option value="">—</option>
              {clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name}
                </option>
              ))}
            </select>
          </div>
          <label className="flex h-10 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.is_head}
              onChange={(event) =>
                setForm({ ...form, is_head: event.target.checked })
              }
              className="h-4 w-4"
            />
            <span>Head (główny opiekun)</span>
          </label>
          <Button
            onClick={() =>
              assign.mutate({
                delivery_lead_user_id: Number(form.delivery_lead_user_id),
                client_id: Number(form.client_id),
                is_head: form.is_head,
              })
            }
            disabled={
              !form.delivery_lead_user_id || !form.client_id || assign.isPending
            }
          >
            {assign.isPending ? "Przypisuję…" : "Przypisz"}
          </Button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border">
              <tr>
                <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Delivery Lead
                </th>
                <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Klienci
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(summary?.dl_clients ?? []).map((row) => (
                <tr key={row.delivery_lead.id}>
                  <td className="px-3 py-2 align-top font-semibold">
                    {row.delivery_lead.name}
                  </td>
                  <td className="px-3 py-2">
                    {row.clients.length === 0 && (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                    <div className="flex flex-wrap gap-1.5">
                      {row.clients.map((client) => (
                        <Badge
                          key={client.id}
                          variant={client.is_head ? "burgundy" : "soft"}
                          size="sm"
                          className={cn(client.is_head && "gap-1")}
                        >
                          {client.is_head && <Crown className="h-3 w-3" />}
                          {client.name}
                        </Badge>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function TeamStructureReadOnly({
  summary,
}: {
  summary: TeamStructureSummary | undefined
}) {
  if (!summary) {
    return <div className="text-sm text-muted-foreground">Ładowanie struktury…</div>
  }

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Kompetencje zespołu</CardTitle>
          <CardDescription>
            Kategorie oraz osoby przypisane w pierwszym i drugim priorytecie.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {summary.categories.map((row) => (
            <div key={row.category.id} className="rounded-lg border border-border p-3">
              <div className="font-medium">{row.category.name_pl}</div>
              <div className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <div className="text-xs text-muted-foreground">Pierwszy priorytet</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {row.first_priority.length > 0 ? row.first_priority.map((operator) => (
                      <Badge key={operator.user_id} size="sm" variant="soft">
                        {operator.name}
                      </Badge>
                    )) : <span className="text-muted-foreground">—</span>}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Drugi priorytet</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {row.second_priority.length > 0 ? row.second_priority.map((operator) => (
                      <Badge key={operator.user_id} size="sm" variant="outline">
                        {operator.name}
                      </Badge>
                    )) : <span className="text-muted-foreground">—</span>}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Klienci Delivery Leadów</CardTitle>
          <CardDescription>
            Pełne przypisanie klientów, z oznaczeniem Head DL.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {summary.dl_clients.map((row) => (
            <div key={row.delivery_lead.id} className="rounded-lg border border-border p-3">
              <div className="font-medium">{row.delivery_lead.name}</div>
              <div className="mt-2 flex flex-wrap gap-1">
                {row.clients.length > 0 ? row.clients.map((client) => (
                  <Badge
                    key={client.id}
                    size="sm"
                    variant={client.is_head ? "success" : "soft"}
                  >
                    {client.name}{client.is_head ? " · Head DL" : ""}
                  </Badge>
                )) : <span className="text-sm text-muted-foreground">Brak przypisań</span>}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────────────

export default function AdminTeamStructurePage() {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  const canEdit = hasRole(user, "admin", "head_of_recruitment")
  const isAllowed = canEdit || hasRole(user, "finance")

  const { data: summary } = useQuery<TeamStructureSummary>({
    queryKey: ["admin-team-structure-summary"],
    queryFn: () => api.get("/api/team-structure/summary").then((r) => r.data),
    enabled: hydrated && isAllowed,
  })

  const { data: assignableUsers = [] } = useQuery<UserBrief[]>({
    queryKey: ["admin-users-all"],
    queryFn: () => {
      const params = new URLSearchParams()
      DIRECTORY_ROLES.forEach((role) => params.append("roles", role))
      return api.get(`/api/users?${params.toString()}`).then((r) => r.data)
    },
    enabled: hydrated && canEdit,
  })

  const { data: clients = [] } = useQuery<ClientBrief[]>({
    queryKey: ["admin-clients-list"],
    queryFn: () =>
      api
        .get("/api/clients", { params: { limit: 500 } })
        .then((r) => (Array.isArray(r.data) ? r.data : r.data.items ?? [])),
    enabled: hydrated && canEdit,
  })

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>
  }

  if (!isAllowed) {
    return (
      <div className="p-6">
        <Card>
          <CardHeader>
            <CardTitle>Brak dostępu</CardTitle>
            <CardDescription>
              Strona dla Admina lub Head of Recruitment.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  const effectiveRoles = (candidate: UserBrief) =>
    new Set([candidate.role, ...(candidate.roles ?? [])].filter(Boolean))
  const dls = assignableUsers.filter((candidate) =>
    effectiveRoles(candidate).has("delivery_lead"),
  )
  const operators = assignableUsers.filter((candidate) =>
    OPERATOR_ROLES.some((role) => effectiveRoles(candidate).has(role)),
  )

  return (
    <div className="mx-auto max-w-[1400px] space-y-6 p-4 md:p-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
          Rekrutacja · Struktura zespołu
        </p>
        <h1 className="mt-1 text-3xl font-extrabold tracking-[-0.025em] text-foreground md:text-4xl">
          Kompetencje i odpowiedzialności
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {canEdit
            ? "Zarządzaj kompetencjami osób oraz przypisaniami Delivery Leadów do klientów."
            : "Podgląd kompetencji zespołu oraz przypisań Delivery Leadów do klientów."}
        </p>
      </div>

      {canEdit ? (
        <>
          <OperatorCompetencesSection summary={summary} operators={operators} />
          <DeliveryLeadReportingInfo />
          <DlClientsSection summary={summary} dls={dls} clients={clients} />
        </>
      ) : (
        <TeamStructureReadOnly summary={summary} />
      )}
    </div>
  )
}
