"use client"

import { useState } from"react"
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query"
import { Crown, Plus, Trash2 } from"lucide-react"

import api from"@/lib/api"
import { cn } from"@/lib/utils"
import { Button } from"@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from"@/components/ui/card"
import { Badge } from"@/components/ui/badge"
import { Input } from"@/components/ui/input"
import { useAuthStore } from"@/store/auth"

// ── Types ──────────────────────────────────────────────────────────────

interface UserBrief { id: number; name: string; email?: string; role?: string }
interface Category { id: number; slug: string; name_pl: string; name_en: string }

interface SourcerCategoryRow {
 category: Category
 first_priority: Array<{ user_id: number; name: string; priority: number | null }>
 second_priority: Array<{ user_id: number; name: string; priority: number | null }>
}

interface DlWithTacsRow {
 delivery_lead: UserBrief
 tacs: Array<{
 user_id: number
 name: string
 linkedin_farming: Category[]
 }>
}

interface DlClientsRow {
 delivery_lead: UserBrief
 clients: Array<{ id: number; name: string; is_head: boolean }>
}

interface TeamStructureSummary {
 categories: SourcerCategoryRow[]
 delivery_leads: DlWithTacsRow[]
 dl_clients: DlClientsRow[]
 totals: Record<string, number>
}

interface ClientBrief { id: number; name: string }

// ── Shared hooks ───────────────────────────────────────────────────────

function useInvalidate() {
 const qc = useQueryClient()
 return () => {
 qc.invalidateQueries({ queryKey: ["team-structure-summary"] })
 qc.invalidateQueries({ queryKey: ["admin-team-structure-summary"] })
 }
}

// ── 1. Sourcer × Category matrix ───────────────────────────────────────

function SourcerCategorySection({
 summary,
 users,
}: {
 summary: TeamStructureSummary | undefined
 users: UserBrief[]
}) {
 const invalidate = useInvalidate()
 const [form, setForm] = useState({ user_id: "", category_id: "", priority: "1" })

 const assign = useMutation({
 mutationFn: (body: { user_id: number; competence_category_id: number; priority: number }) =>
 api.post("/api/team-structure/sourcer-categories", body).then((r) => r.data),
 onSuccess: () => {
 invalidate()
 setForm({ user_id: "", category_id: "", priority: "1" })
 },
 })

 const canSubmit = form.user_id && form.category_id

 return (
 <Card>
 <CardHeader>
 <CardTitle>1. Sourcerzy × Kategorie kompetencji</CardTitle>
 <CardDescription>
 Przypisz sourcera/TAC/rekrutera do kategorii z priorytetem 1 (główna) lub 2 (wsparcie).
 </CardDescription>
 </CardHeader>
 <CardContent className="space-y-4">
 <div className="flex flex-wrap items-end gap-3 p-3 bg-primary/10/40 rounded-lg">
 <div className="flex-1 min-w-[200px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 Użytkownik
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={form.user_id}
 onChange={(e) => setForm({ ...form, user_id: e.target.value })}
 >
 <option value="">—</option>
 {users.map((u) => (
 <option key={u.id} value={u.id}>
 {u.name} ({u.role})
 </option>
 ))}
 </select>
 </div>
 <div className="flex-1 min-w-[200px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 Kategoria
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={form.category_id}
 onChange={(e) => setForm({ ...form, category_id: e.target.value })}
 >
 <option value="">—</option>
 {(summary?.categories ?? []).map((r) => (
 <option key={r.category.id} value={r.category.id}>
 {r.category.name_pl}
 </option>
 ))}
 </select>
 </div>
 <div className="w-24">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 Priority
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={form.priority}
 onChange={(e) => setForm({ ...form, priority: e.target.value })}
 >
 <option value="1">1st</option>
 <option value="2">2nd</option>
 </select>
 </div>
 <Button
 onClick={() =>
 assign.mutate({
 user_id: Number(form.user_id),
 competence_category_id: Number(form.category_id),
 priority: Number(form.priority),
 })
 }
 disabled={!canSubmit || assign.isPending}
 >
 <Plus className="h-4 w-4" />
 {assign.isPending ?"Zapisuję…" :"Dodaj / Zaktualizuj"}
 </Button>
 </div>

 <div className="overflow-x-auto">
 <table className="w-full text-sm">
 <thead className="border-b border-border">
 <tr>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Kategoria
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 1st priority
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 2nd priority
 </th>
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {(summary?.categories ?? []).map((row) => (
 <tr key={row.category.id}>
 <td className="px-3 py-2 font-semibold">{row.category.name_pl}</td>
 <td className="px-3 py-2">
 <div className="flex flex-wrap gap-1.5">
 {row.first_priority.length === 0 && (
 <span className="text-xs text-muted-foreground">—</span>
 )}
 {row.first_priority.map((s) => (
 <Badge key={s.user_id} variant="soft" size="sm">
 {s.name}
 </Badge>
 ))}
 </div>
 </td>
 <td className="px-3 py-2">
 <div className="flex flex-wrap gap-1.5">
 {row.second_priority.length === 0 && (
 <span className="text-xs text-muted-foreground">—</span>
 )}
 {row.second_priority.map((s) => (
 <Badge key={s.user_id} size="sm">
 {s.name}
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

// ── 2. TAC → DL matrix ─────────────────────────────────────────────────

function TacDlSection({
 summary,
 tacs,
 dls,
 categories,
}: {
 summary: TeamStructureSummary | undefined
 tacs: UserBrief[]
 dls: UserBrief[]
 categories: Category[]
}) {
 const invalidate = useInvalidate()
 const [form, setForm] = useState({ tac_user_id: "", delivery_lead_user_id: "" })
 const [farmForm, setFarmForm] = useState({ tac_user_id: "", category_id: "" })

 const assign = useMutation({
 mutationFn: (body: { tac_user_id: number; delivery_lead_user_id: number }) =>
 api.post("/api/team-structure/tac-delivery-leads", body).then((r) => r.data),
 onSuccess: () => {
 invalidate()
 setForm({ tac_user_id: "", delivery_lead_user_id: "" })
 },
 })

 const unassign = useMutation({
 mutationFn: (tacId: number) =>
 api.delete(`/api/team-structure/tac-delivery-leads/${tacId}`).then((r) => r.data),
 onSuccess: invalidate,
 })

 const addFarming = useMutation({
 mutationFn: (body: { tac_user_id: number; competence_category_id: number }) =>
 api.post("/api/team-structure/tac-linkedin-farming", body).then((r) => r.data),
 onSuccess: () => {
 invalidate()
 setFarmForm({ tac_user_id: "", category_id: "" })
 },
 })

 return (
 <Card>
 <CardHeader>
 <CardTitle>2. TAC → Delivery Lead</CardTitle>
 <CardDescription>
 Jeden TAC raportuje do jednego DL. Re-assign nadpisze poprzedni DL.
 </CardDescription>
 </CardHeader>
 <CardContent className="space-y-4">
 <div className="flex flex-wrap items-end gap-3 p-3 bg-primary/10/40 rounded-lg">
 <div className="flex-1 min-w-[180px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 TAC
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={form.tac_user_id}
 onChange={(e) => setForm({ ...form, tac_user_id: e.target.value })}
 >
 <option value="">—</option>
 {tacs.map((u) => (
 <option key={u.id} value={u.id}>
 {u.name}
 </option>
 ))}
 </select>
 </div>
 <div className="flex-1 min-w-[180px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 Delivery Lead
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={form.delivery_lead_user_id}
 onChange={(e) =>
 setForm({ ...form, delivery_lead_user_id: e.target.value })
 }
 >
 <option value="">—</option>
 {dls.map((u) => (
 <option key={u.id} value={u.id}>
 {u.name}
 </option>
 ))}
 </select>
 </div>
 <Button
 onClick={() =>
 assign.mutate({
 tac_user_id: Number(form.tac_user_id),
 delivery_lead_user_id: Number(form.delivery_lead_user_id),
 })
 }
 disabled={!form.tac_user_id || !form.delivery_lead_user_id || assign.isPending}
 >
 <Plus className="h-4 w-4" />
 Przypisz
 </Button>
 </div>

 <div className="overflow-x-auto">
 <table className="w-full text-sm">
 <thead className="border-b border-border">
 <tr>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Delivery Lead
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 TAC-y
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 LinkedIn farming
 </th>
 <th className="text-right text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Akcje
 </th>
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {(summary?.delivery_leads ?? []).map((row) =>
 row.tacs.length === 0 ? (
 <tr key={row.delivery_lead.id}>
 <td className="px-3 py-2 font-semibold">
 {row.delivery_lead.name}
 </td>
 <td colSpan={3} className="px-3 py-2 text-xs text-muted-foreground italic">
 brak TAC-ów
 </td>
 </tr>
 ) : (
 row.tacs.map((tac, tIdx) => (
 <tr key={`${row.delivery_lead.id}-${tac.user_id}`}>
 {tIdx === 0 && (
 <td
 rowSpan={row.tacs.length}
 className="px-3 py-2 font-semibold align-top border-r border-border"
 >
 {row.delivery_lead.name}
 </td>
 )}
 <td className="px-3 py-2">{tac.name}</td>
 <td className="px-3 py-2">
 <div className="flex flex-wrap gap-1">
 {tac.linkedin_farming.length === 0 && (
 <span className="text-xs text-muted-foreground">—</span>
 )}
 {tac.linkedin_farming.map((c) => (
 <Badge key={c.id} variant="soft" size="sm">
 {c.name_pl}
 </Badge>
 ))}
 </div>
 </td>
 <td className="px-3 py-2 text-right">
 <button
 className="text-xs text-primary hover:underline"
 onClick={() => unassign.mutate(tac.user_id)}
 >
 <Trash2 className="inline h-3 w-3 mr-1" />
 Usuń
 </button>
 </td>
 </tr>
 ))
 )
 )}
 </tbody>
 </table>
 </div>

 <div className="border-t border-border pt-4">
 <h4 className="text-sm font-semibold mb-2">
 Dodaj kategorię LinkedIn farming dla TAC
 </h4>
 <div className="flex flex-wrap items-end gap-3 p-3 bg-primary/10/40 rounded-lg">
 <div className="flex-1 min-w-[180px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 TAC
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={farmForm.tac_user_id}
 onChange={(e) =>
 setFarmForm({ ...farmForm, tac_user_id: e.target.value })
 }
 >
 <option value="">—</option>
 {tacs.map((u) => (
 <option key={u.id} value={u.id}>
 {u.name}
 </option>
 ))}
 </select>
 </div>
 <div className="flex-1 min-w-[180px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 Kategoria
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={farmForm.category_id}
 onChange={(e) =>
 setFarmForm({ ...farmForm, category_id: e.target.value })
 }
 >
 <option value="">—</option>
 {categories.map((c) => (
 <option key={c.id} value={c.id}>
 {c.name_pl}
 </option>
 ))}
 </select>
 </div>
 <Button
 onClick={() =>
 addFarming.mutate({
 tac_user_id: Number(farmForm.tac_user_id),
 competence_category_id: Number(farmForm.category_id),
 })
 }
 disabled={!farmForm.tac_user_id || !farmForm.category_id || addFarming.isPending}
 >
 <Plus className="h-4 w-4" />
 Dodaj farming
 </Button>
 </div>
 </div>
 </CardContent>
 </Card>
 )
}

// ── 3. DL → Clients ────────────────────────────────────────────────────

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
 Przypisz DL do klientów. Zaznacz <span className="font-semibold">Head</span>{""}
 dla głównego opiekuna (max 1 per klient — automatycznie odznaczany u
 innych).
 </CardDescription>
 </CardHeader>
 <CardContent className="space-y-4">
 <div className="flex flex-wrap items-end gap-3 p-3 bg-primary/10/40 rounded-lg">
 <div className="flex-1 min-w-[180px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 Delivery Lead
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={form.delivery_lead_user_id}
 onChange={(e) =>
 setForm({ ...form, delivery_lead_user_id: e.target.value })
 }
 >
 <option value="">—</option>
 {dls.map((u) => (
 <option key={u.id} value={u.id}>
 {u.name}
 </option>
 ))}
 </select>
 </div>
 <div className="flex-1 min-w-[180px]">
 <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground block mb-1">
 Klient
 </label>
 <select
 className="w-full h-10 px-3 border border-border rounded-lg bg-card"
 value={form.client_id}
 onChange={(e) => setForm({ ...form, client_id: e.target.value })}
 >
 <option value="">—</option>
 {clients.map((c) => (
 <option key={c.id} value={c.id}>
 {c.name}
 </option>
 ))}
 </select>
 </div>
 <label className="flex items-center gap-2 text-sm h-10">
 <input
 type="checkbox"
 checked={form.is_head}
 onChange={(e) => setForm({ ...form, is_head: e.target.checked })}
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
 disabled={!form.delivery_lead_user_id || !form.client_id || assign.isPending}
 >
 <Plus className="h-4 w-4" />
 Przypisz
 </Button>
 </div>

 <div className="overflow-x-auto">
 <table className="w-full text-sm">
 <thead className="border-b border-border">
 <tr>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Delivery Lead
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Klienci
 </th>
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {(summary?.dl_clients ?? []).map((row) => (
 <tr key={row.delivery_lead.id}>
 <td className="px-3 py-2 font-semibold align-top">
 {row.delivery_lead.name}
 </td>
 <td className="px-3 py-2">
 {row.clients.length === 0 && (
 <span className="text-xs text-muted-foreground">—</span>
 )}
 <div className="flex flex-wrap gap-1.5">
 {row.clients.map((c) => (
 <Badge
 key={c.id}
 variant={c.is_head ?"burgundy" :"soft"}
 size="sm"
 className={cn(c.is_head &&"gap-1")}
 >
 {c.is_head && <Crown className="h-3 w-3" />}
 {c.name}
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

// ── Page ──────────────────────────────────────────────────────────────

export default function AdminTeamStructurePage() {
 const user = useAuthStore((s) => s.user)
 const hydrated = useAuthStore((s) => s.hydrated)
 const isAllowed = !!user && (user.role ==="admin" || user.role ==="head_of_recruitment")

 const { data: summary } = useQuery<TeamStructureSummary>({
 queryKey: ["admin-team-structure-summary"],
 queryFn: () =>
 api.get("/api/team-structure/summary").then((r) => r.data),
 enabled: hydrated && isAllowed,
 })

 const { data: assignableUsers = [] } = useQuery<UserBrief[]>({
 queryKey: ["admin-users-all"],
 queryFn: () =>
 api
 .get("/api/users", { params: { roles: ["sourcer","tac","recruiter","delivery_lead"] } })
 .then((r) => r.data),
 enabled: hydrated && isAllowed,
 })

 const { data: clients = [] } = useQuery<ClientBrief[]>({
 queryKey: ["admin-clients-list"],
 queryFn: () =>
 api
 .get("/api/clients", { params: { limit: 500 } })
 .then((r) => (Array.isArray(r.data) ? r.data : r.data.items ?? [])),
 enabled: hydrated && isAllowed,
 })

 if (!hydrated) return <div className="p-6 text-muted-foreground">Ładowanie…</div>

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

 const tacs = assignableUsers.filter((u) => u.role ==="tac")
 const dls = assignableUsers.filter((u) => u.role ==="delivery_lead")
 const sourcerAndAbove = assignableUsers.filter((u) =>
 ["sourcer","tac","recruiter"].includes(u.role ??"")
 )
 const categoryList = (summary?.categories ?? []).map((r) => r.category)

 return (
 <div className="max-w-[1400px] mx-auto space-y-6 p-4 md:p-6">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Admin · Struktura zespołu
 </p>
 <h1 className="font-semibold text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-foreground mt-1">
 Macierze przypisań
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 CRUD dla sourcer × kategoria, TAC → DL, LinkedIn farming, DL → klient.
 </p>
 </div>

 <SourcerCategorySection summary={summary} users={sourcerAndAbove} />
 <TacDlSection
 summary={summary}
 tacs={tacs}
 dls={dls}
 categories={categoryList}
 />
 <DlClientsSection summary={summary} dls={dls} clients={clients} />
 </div>
 )
}
