"use client"

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Crown, Info } from "lucide-react"

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
import { fetchAllClientOptions } from "@/lib/admin-client-options"
import { cn } from "@/lib/utils"
import { hasRole, useAuthStore } from "@/store/auth"
import { TAC_UI_ENABLED } from "@/lib/tac-ui"
import { useUrlWriter } from "@/lib/url-selection"
import { TabbedNav } from "@/components/ds/TabbedNav"
import { CompetenceTeamPanel } from "@/components/v2/competence-team/CompetenceTeamPanel"
import { AllocationRulesPanel } from "@/components/v2/competence-team/AllocationRulesPanel"
import { usePathname, useSearchParams } from "next/navigation"

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

const OPERATOR_ROLES = ["recruiter"]
const DIRECTORY_ROLES = [...OPERATOR_ROLES, "delivery_lead"]

// ── Shared helpers ─────────────────────────────────────────────────────────────

function useInvalidate() {
  const queryClient = useQueryClient()

  return () => {
    queryClient.invalidateQueries({ queryKey: ["team-structure-summary"] })
    queryClient.invalidateQueries({ queryKey: ["admin-team-structure-summary"] })
  }
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
            {TAC_UI_ENABLED ? (
              <p className="text-muted-foreground">
                System łączy przypisania klient ↔ Delivery Lead z przypisaniami
                klient ↔ TAC. TAC-ów przypisujesz na karcie klienta, a Delivery
                Leadów w sekcji poniżej. Rekruterzy raportują organizacyjnie do
                Head of Recruitment.
              </p>
            ) : (
              <p className="text-muted-foreground">
                Delivery Leadów przypisujesz do klientów w sekcji poniżej.
                Rekruterzy raportują organizacyjnie do Head of Recruitment.
              </p>
            )}
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

type TeamTab = "kategorie" | "dl" | "automat"

const TEAM_TABS = [
  { value: "kategorie", label: "Kategorie" },
  { value: "dl", label: "Delivery Leadzi i klienci" },
  { value: "automat", label: "Automat przydziału" },
]

export default function AdminTeamStructurePage() {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  // Zakładka w adresie (`?zakladka=`), żeby stary link `/settings/competence-team`
  // mógł otworzyć „Kategorie”, a F5 zostawał na tej samej zakładce.
  const searchParams = useSearchParams()
  const pathname = usePathname() ?? "/settings/team-structure"
  const { replaceUrl } = useUrlWriter()
  const rawTab = searchParams?.get("zakladka")
  const tab: TeamTab = rawTab === "dl" || rawTab === "automat" ? rawTab : "kategorie"
  const selectTab = (next: string) => {
    const params = new URLSearchParams(searchParams?.toString() ?? "")
    params.set("zakladka", next)
    replaceUrl(`${pathname}?${params.toString()}`)
  }
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
    // B43: `GET /api/clients` nie zna `limit` — stronicuje po `page_size` (sufit
    // 100), więc picker DL widział tylko pierwsze 20 firm. Przechodzimy strony.
    queryFn: () =>
      fetchAllClientOptions((page, page_size) =>
        api.get("/api/clients", { params: { page, page_size } }).then((r) => ({
          items: ((r.data.items ?? []) as ClientBrief[]).map(({ id, name }) => ({
            id,
            name,
          })),
          total: Number(r.data.total ?? 0),
        })),
      ),
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

  return (
    <div className="mx-auto max-w-[1400px] space-y-6 p-4 md:p-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
          Rekrutacja · Struktura zespołu
        </p>
        <h1 className="mt-1 text-3xl font-extrabold tracking-[-0.025em] text-foreground md:text-4xl">
          Zespół rekrutacji
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {canEdit
            ? "Kto szuka w której kategorii i którego klienta prowadzi Delivery Lead. Automat przydziela requesty najpierw 1. priorytetowi."
            : "Podgląd kompetencji zespołu oraz przypisań Delivery Leadów do klientów."}
        </p>
      </div>

      {canEdit ? (
        <>
          <TabbedNav
            tabs={TEAM_TABS}
            value={tab}
            onValueChange={selectTab}
            ariaLabel="Zespół rekrutacji"
          />
          {tab === "kategorie" ? (
            <CompetenceTeamPanel />
          ) : tab === "automat" ? (
            <AllocationRulesPanel />
          ) : (
            <>
              <DeliveryLeadReportingInfo />
              <DlClientsSection summary={summary} dls={dls} clients={clients} />
            </>
          )}
        </>
      ) : (
        <TeamStructureReadOnly summary={summary} />
      )}
    </div>
  )
}
