"use client"

import { useMemo, useState } from"react"
import { useRouter } from"next/navigation"
import { useMutation, useQuery } from"@tanstack/react-query"
import { Building2, Check, MapPin, Search, Sparkles } from"lucide-react"

import api from"@/lib/api"
import { useAuthStore } from"@/store/auth"
import { cn } from"@/lib/utils"
import { Button } from"@/components/ui/button"
import { Checkbox } from"@/components/ui/checkbox"
import { Input } from"@/components/ui/input"

interface JobListItem {
 id: number
 title: string
 client_name?: string | null
 location?: string | null
 status?: string | null
 seniority?: string | null
}

interface JobsResponse {
 items: JobListItem[]
 total: number
}

interface OnboardingResponsePayload {
 user: {
 id: number
 email: string
 name: string
 role: string
 profile_completed: boolean
 profile_completed_at: string | null
 }
}

function matchesQuery(job: JobListItem, q: string): boolean {
 if (!q) return true
 const needle = q.trim().toLowerCase()
 if (!needle) return true
 return (
 job.title.toLowerCase().includes(needle) ||
 (job.client_name?.toLowerCase() ??"").includes(needle) ||
 (job.location?.toLowerCase() ??"").includes(needle)
 )
}

export function OnboardingRecruiterV2() {
 const router = useRouter()
 const token = useAuthStore((s) => s.token)
 const setAuth = useAuthStore((s) => s.setAuth)

 const [search, setSearch] = useState("")
 const [selected, setSelected] = useState<Set<number>>(new Set())

 const { data, isLoading } = useQuery<JobsResponse>({
 queryKey: ["onboarding-jobs"],
 queryFn: () =>
 api
 .get<JobsResponse>("/api/jobs", {
 params: { status: "published", page: 1, page_size: 100 },
 })
 .then((r) => r.data),
 staleTime: 60_000,
 })

 const mutation = useMutation<OnboardingResponsePayload, unknown, void>({
 mutationFn: async () => {
 const { data: payload } = await api.post<OnboardingResponsePayload>("/api/users/me/onboarding",
 { active_job_ids: Array.from(selected) },
 )
 return payload
 },
 onSuccess: (payload) => {
 setAuth(
 {
 id: payload.user.id,
 email: payload.user.email,
 name: payload.user.name,
 role: payload.user.role as never,
 profile_completed: payload.user.profile_completed,
 profile_completed_at: payload.user.profile_completed_at,
 // Onboarding endpoint nie zwraca tych pól — backfill default false.
 force_password_change: false,
 force_password_change_at: null,
 },
 token ?? undefined,
 )
 try {
 localStorage.setItem("onboarding_completed","true")
 } catch {
 /* non-browser env */
 }
 router.replace("/")
 },
 })

 const allJobs = data?.items ?? []
 const filtered = useMemo(
 () => allJobs.filter((j) => matchesQuery(j, search)),
 [allJobs, search],
 )

 function toggle(id: number) {
 setSelected((prev) => {
 const next = new Set(prev)
 if (next.has(id)) next.delete(id)
 else next.add(id)
 return next
 })
 }

 const isEmpty = !isLoading && allJobs.length === 0
 const submitting = mutation.isPending

 return (
 <div className="min-h-screen flex items-start justify-center px-4 py-10">
 <div className="w-full max-w-3xl">
 <div className="mb-6 flex flex-col items-start">
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Onboarding · Aktywni w searchu
 </p>
 <h1 className="font-semibold text-2xl md:text-3xl font-extrabold tracking-[-0.02em] text-foreground mt-1">
 Którymi rekrutacjami aktualnie się zajmujesz?
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Zaznacz oferty, nad którymi aktywnie pracujesz. Zostaniesz dopisany
 jako współpracownik — nie zmieni to głównego przypisania.
 </p>
 </div>

 <div className="bg-card border border-border rounded-xl shadow-md overflow-hidden">
 <div className="px-5 pt-5">
 <Input
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder="Szukaj po tytule, kliencie, lokalizacji…"
 value={search}
 onChange={(e) => setSearch(e.target.value)}
 disabled={isLoading || isEmpty}
 />
 </div>

 <div className="px-5 py-4 max-h-[55vh] overflow-y-auto">
 {isLoading ? (
 <div className="space-y-2 animate-pulse">
 {Array.from({ length: 6 }).map((_, i) => (
 <div
 key={i}
 className="h-12 rounded-lg bg-[hsl(var(--border))]/60"
 />
 ))}
 </div>
 ) : isEmpty ? (
 <div className="py-10 text-center">
 <Sparkles className="h-8 w-8 mx-auto text-primary opacity-50 mb-2" />
 <p className="text-sm text-muted-foreground">
 Nie ma jeszcze ofert w systemie. Możesz pominąć ten krok —
 wrócisz do niego, gdy będzie co oznaczać.
 </p>
 </div>
 ) : filtered.length === 0 ? (
 <p className="py-10 text-center text-sm text-muted-foreground">
 Brak ofert pasujących do „{search}".
 </p>
 ) : (
 <ul className="divide-y divide-border">
 {filtered.map((job) => {
 const checked = selected.has(job.id)
 return (
 <li key={job.id}>
 <label
 className={cn("flex items-start gap-3 px-2 py-3 cursor-pointer rounded-md transition-colors",
 checked
 ?"bg-primary/10"
 :"hover:bg-background",
 )}
 >
 <Checkbox
 checked={checked}
 onCheckedChange={() => toggle(job.id)}
 className="mt-0.5"
 aria-label={`Zaznacz ${job.title}`}
 />
 <div className="flex-1 min-w-0">
 <p className="font-medium text-foreground truncate">
 {job.title}
 </p>
 <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
 {job.client_name && (
 <span className="inline-flex items-center gap-1 truncate">
 <Building2 className="h-3 w-3" />
 {job.client_name}
 </span>
 )}
 {job.location && (
 <span className="inline-flex items-center gap-1 truncate">
 <MapPin className="h-3 w-3" />
 {job.location}
 </span>
 )}
 {job.seniority && (
 <span className="uppercase text-[10px] tracking-wider text-primary">
 {job.seniority}
 </span>
 )}
 </div>
 </div>
 </label>
 </li>
 )
 })}
 </ul>
 )}
 </div>

 <div className="px-5 py-4 border-t border-border bg-background flex items-center justify-between gap-3">
 <p className="text-xs text-muted-foreground">
 Wybrano: <strong className="text-foreground">{selected.size}</strong>
 </p>
 <Button
 variant="primary"
 loading={submitting}
 onClick={() => mutation.mutate()}
 >
 {submitting ?"Zapisuję…" : (
 <>
 <Check className="h-4 w-4" /> Zakończ onboarding
 </>
 )}
 </Button>
 </div>
 </div>

 {mutation.isError && (
 <p className="mt-3 text-sm text-primary">
 Nie udało się zapisać. Spróbuj ponownie.
 </p>
 )}
 </div>
 </div>
 )
}
