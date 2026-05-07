"use client"

import { useEffect, useMemo, useState } from"react"
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query"
import { ChevronLeft, ChevronRight, Save } from"lucide-react"

import api from"@/lib/api"
import { Button } from"@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from"@/components/ui/card"
import { useAuthStore } from"@/store/auth"

// ── Types ──────────────────────────────────────────────────────────────

interface LiUser { id: number; name: string; role: string; email?: string }
interface LiRow {
 id: number
 user_id: number
 name: string
 report_date: string
 cv_added: number
 messages_sent: number
 responses_received: number
 week_number?: number | null
}

// Rzadkie mapowanie: user_id × date → edited values (local state).
type CellKey = string //"userId|YYYY-MM-DD"
interface CellDraft {
 cv_added: number
 messages_sent: number
 responses_received: number
}

// ── Week helpers ───────────────────────────────────────────────────────

function toISO(d: Date) {
 return d.toISOString().slice(0, 10)
}

function startOfWeek(d: Date) {
 // ISO week — monday
 const copy = new Date(d)
 const day = copy.getDay() || 7
 if (day !== 1) copy.setDate(copy.getDate() - (day - 1))
 copy.setHours(0, 0, 0, 0)
 return copy
}

function addDays(d: Date, n: number) {
 const copy = new Date(d)
 copy.setDate(copy.getDate() + n)
 return copy
}

function fmtDay(d: Date) {
 return d.toLocaleDateString("pl-PL", { weekday: "short", day: "numeric", month: "numeric" })
}

// ── Page ───────────────────────────────────────────────────────────────

export default function AdminLinkedInMetricsPage() {
 const user = useAuthStore((s) => s.user)
 const hydrated = useAuthStore((s) => s.hydrated)
 const isAllowed = !!user && (user.role === "admin" || user.role === "head_of_recruitment")
 const qc = useQueryClient()

 const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()))
 const [drafts, setDrafts] = useState<Record<CellKey, CellDraft>>({})

 const weekDays = useMemo(
 () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
 [weekStart],
 )
 const weekFromISO = toISO(weekDays[0])
 const weekToISO = toISO(weekDays[6])

 const { data: users = [] } = useQuery<LiUser[]>({
 queryKey: ["linkedin-users"],
 queryFn: () =>
 api.get("/api/linkedin-metrics/users").then((r) => r.data),
 enabled: hydrated && isAllowed,
 })

 const { data: rows = [] } = useQuery<LiRow[]>({
 queryKey: ["linkedin-batch", weekFromISO, weekToISO],
 queryFn: () =>
 api
 .get("/api/linkedin-metrics/batch", {
 params: { date_from: weekFromISO, date_to: weekToISO },
 })
 .then((r) => r.data),
 enabled: hydrated && isAllowed,
 })

 // Map server rows → drafts (tylko przy zmianie week_range lub dataset).
 useEffect(() => {
 const next: Record<CellKey, CellDraft> = {}
 for (const r of rows) {
 const key = `${r.user_id}|${r.report_date}`
 next[key] = {
 cv_added: r.cv_added,
 messages_sent: r.messages_sent,
 responses_received: r.responses_received,
 }
 }
 setDrafts(next)
 }, [rows.length, weekFromISO])

 const getDraft = (userId: number, dateIso: string): CellDraft =>
 drafts[`${userId}|${dateIso}`] ?? {
 cv_added: 0,
 messages_sent: 0,
 responses_received: 0,
 }

 const setCell = (
 userId: number,
 dateIso: string,
 field: keyof CellDraft,
 value: number,
 ) => {
 const key = `${userId}|${dateIso}`
 setDrafts((prev) => ({
 ...prev,
 [key]: { ...getDraft(userId, dateIso), [field]: value },
 }))
 }

 const saveMutation = useMutation({
 mutationFn: (payload: { rows: Array<{ user_id: number; report_date: string } & CellDraft> }) =>
 api.post("/api/linkedin-metrics/batch", payload).then((r) => r.data),
 onSuccess: () => {
 qc.invalidateQueries({ queryKey: ["linkedin-batch"] })
 qc.invalidateQueries({ queryKey: ["linkedin-summary"] })
 qc.invalidateQueries({ queryKey: ["linkedin-my-summary"] })
 },
 })

 const handleSave = () => {
 // Zapisuj tylko komórki które mają >0 lub zmieniły się względem oryginału.
 const payload: Array<{ user_id: number; report_date: string } & CellDraft> = []
 for (const [key, draft] of Object.entries(drafts)) {
 const [userIdStr, dateIso] = key.split("|")
 if (draft.cv_added === 0 && draft.messages_sent === 0 && draft.responses_received === 0) {
 continue
 }
 payload.push({
 user_id: Number(userIdStr),
 report_date: dateIso,
 ...draft,
 })
 }
 if (payload.length === 0) return
 saveMutation.mutate({ rows: payload })
 }

 if (!hydrated) return <div className="p-6 text-muted-foreground">Ładowanie…</div>
 if (!isAllowed) {
 return (
 <div className="p-6">
 <Card>
 <CardHeader>
 <CardTitle>Brak dostępu</CardTitle>
 <CardDescription>Strona dla admina/Head of Recruitment.</CardDescription>
 </CardHeader>
 </Card>
 </div>
 )
 }

 return (
 <div className="max-w-[1400px] mx-auto space-y-5 p-4 md:p-6">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Admin · LinkedIn metrics (ręczne)
 </p>
 <h1 className="font-semibold text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-foreground mt-1">
 Aktywność LinkedIn — bulk edit
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Wpisz dzienne liczby dla każdego TAC/recruiter/sourcer. Wiersze zerowe
 nie są zapisywane.
 </p>
 </div>

 {/* Week picker */}
 <Card>
 <CardContent className="py-3 flex items-center gap-3 flex-wrap">
 <Button
 variant="outline"
 size="sm"
 onClick={() => setWeekStart(addDays(weekStart, -7))}
 >
 <ChevronLeft className="h-4 w-4" />
 Poprzedni tydzień
 </Button>
 <div className="font-semibold text-sm">
 Tydzień: {fmtDay(weekDays[0])} – {fmtDay(weekDays[6])}
 </div>
 <Button
 variant="outline"
 size="sm"
 onClick={() => setWeekStart(addDays(weekStart, 7))}
 >
 Następny tydzień
 <ChevronRight className="h-4 w-4" />
 </Button>
 <Button
 variant="outline"
 size="sm"
 onClick={() => setWeekStart(startOfWeek(new Date()))}
 >
 Bieżący tydzień
 </Button>
 <div className="flex-1" />
 <Button
 onClick={handleSave}
 disabled={saveMutation.isPending}
 >
 <Save className="h-4 w-4" />
 {saveMutation.isPending ?"Zapisuję…" :"Zapisz wszystkie"}
 </Button>
 {saveMutation.isSuccess && (
 <span className="text-xs text-[#1d5e31]">
 Zapisano {saveMutation.data?.saved ?? 0} wierszy.
 </span>
 )}
 </CardContent>
 </Card>

 {/* Grid — 3 metryki per dzień per user */}
 <Card>
 <CardHeader>
 <CardTitle>Grid: użytkownik × dzień</CardTitle>
 <CardDescription>
 3 pola per komórka: CV dodane, wiadomości wysłane, odpowiedzi otrzymane.
 </CardDescription>
 </CardHeader>
 <CardContent>
 <div className="overflow-x-auto">
 <table className="w-full text-xs border-collapse">
 <thead>
 <tr className="border-b border-border">
 <th className="text-left font-semibold uppercase tracking-wide text-muted-foreground px-2 py-2 sticky left-0 bg-card">
 Użytkownik
 </th>
 {weekDays.map((d) => (
 <th
 key={d.toISOString()}
 className="text-center font-semibold uppercase tracking-wide text-muted-foreground px-1 py-2 min-w-[140px]"
 >
 {fmtDay(d)}
 </th>
 ))}
 </tr>
 <tr className="border-b border-border">
 <th className="px-2 py-1 sticky left-0 bg-card"></th>
 {weekDays.map((d) => (
 <th
 key={`sub-${d.toISOString()}`}
 className="text-center text-[9px] font-normal text-muted-foreground px-1 py-1 min-w-[140px]"
 >
 CV / Msg / Resp
 </th>
 ))}
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {users.length === 0 && (
 <tr>
 <td
 colSpan={8}
 className="text-center text-sm text-muted-foreground py-6"
 >
 Brak aktywnych użytkowników (TAC/rek/sourcer).
 </td>
 </tr>
 )}
 {users.map((u) => (
 <tr key={u.id} className="hover:bg-primary/10">
 <td className="px-2 py-2 font-medium sticky left-0 bg-card">
 <div>{u.name}</div>
 <div className="text-[10px] text-muted-foreground uppercase">
 {u.role}
 </div>
 </td>
 {weekDays.map((d) => {
 const dateIso = toISO(d)
 const draft = getDraft(u.id, dateIso)
 return (
 <td
 key={`${u.id}-${dateIso}`}
 className="px-1 py-1 align-top"
 >
 <div className="flex gap-0.5">
 <input
 type="number"
 min="0"
 value={draft.cv_added}
 onChange={(e) =>
 setCell(
 u.id,
 dateIso, "cv_added",
 Math.max(0, Number(e.target.value || 0)),
 )
 }
 className="w-10 px-1 py-0.5 text-[11px] border border-border rounded text-right"
 title="CV dodane"
 />
 <input
 type="number"
 min="0"
 value={draft.messages_sent}
 onChange={(e) =>
 setCell(
 u.id,
 dateIso, "messages_sent",
 Math.max(0, Number(e.target.value || 0)),
 )
 }
 className="w-10 px-1 py-0.5 text-[11px] border border-border rounded text-right"
 title="Wiadomości wysłane"
 />
 <input
 type="number"
 min="0"
 value={draft.responses_received}
 onChange={(e) =>
 setCell(
 u.id,
 dateIso, "responses_received",
 Math.max(0, Number(e.target.value || 0)),
 )
 }
 className="w-10 px-1 py-0.5 text-[11px] border border-border rounded text-right"
 title="Odpowiedzi otrzymane"
 />
 </div>
 </td>
 )
 })}
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 </CardContent>
 </Card>
 </div>
 )
}
