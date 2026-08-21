"use client"

import { useMemo, useState } from"react"
import { useRouter } from"next/navigation"
import { useMutation, useQuery } from"@tanstack/react-query"
import { Building2, Check, MapPin, Search, Sparkles } from"lucide-react"

import api from"@/lib/api"
import { type User, useAuthStore } from"@/store/auth"
import { cn } from"@/lib/utils"
import { Button } from"@/components/ui/button"
import { Checkbox } from"@/components/ui/checkbox"
import { Input } from"@/components/ui/input"
import { markOnboardingCompleted } from "@/lib/onboarding-storage"
import {
 QueryStateNotice,
 type BlockingViewState,
} from "@/components/ds/QueryStateNotice"
import { isBlockingViewState, resolveViewState } from "@/lib/view-state"

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

 const { data, isLoading, isError, error, refetch } = useQuery<JobsResponse>({
 queryKey: ["onboarding-jobs", "recruiter"],
 queryFn: () =>
 api
 .get<JobsResponse>("/api/users/me/onboarding/jobs")
 .then((r) => r.data),
 staleTime: 60_000,
 })

 const mutation = useMutation<User, unknown, void>({
 mutationFn: async () => {
 await api.post("/api/users/me/onboarding",
 { active_job_ids: Array.from(selected) },
 )
 const { data: refreshedUser } = await api.get<User>("/api/auth/me")
 return refreshedUser
 },
 onSuccess: (refreshedUser) => {
 if (!token) return
 setAuth(refreshedUser, token)
 markOnboardingCompleted()
 router.replace("/")
 },
 })

 const allJobs = useMemo(() => data?.items ?? [], [data?.items])
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

 // Pusty stan MUSI wisieć na sukcesie, nie na `!isLoading`. „Zakończ onboarding"
 // zapisuje `profile_completed=true` bezwarunkowo i nie ma ścieżki powrotnej w UI,
 // więc nieudane pobranie listy udające „firma nie ma rekrutacji" zostawia rekrutera
 // trwale bez żadnej rekrutacji — a to wejście do „Mojej pracy", priorytetów i KPI.
 const viewState = resolveViewState({
 isLoading,
 isError,
 error,
 isEmpty: allJobs.length === 0,
 })
 const isBlocked = isBlockingViewState(viewState)
 const isEmpty = viewState === "empty"
 const submitting = mutation.isPending

 return (
 <div className="min-h-screen flex items-start justify-center px-4 py-10">
 <div className="w-full max-w-3xl">
 <div className="mb-6 flex flex-col items-start">
 <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
 Onboarding · Aktywni w searchu
 </p>
 <h1 className="font-semibold text-2xl md:text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
 Którymi rekrutacjami aktualnie się zajmujesz?
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Zaznacz rekrutacje, nad którymi aktywnie pracujesz. Zostaniesz dopisany
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
 disabled={isLoading || isBlocked || isEmpty}
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
 ) : isBlocked ? (
 <QueryStateNotice
 state={viewState as BlockingViewState}
 description={
 viewState === "forbidden"
 ?"Twoja rola nie ma dostępu do listy rekrutacji. Zgłoś się do administratora — nie kończ onboardingu z pustym wyborem."
 :"Nie udało się wczytać listy rekrutacji. Ponów próbę — pusta lista nie znaczy tu, że rekrutacji nie ma."
 }
 onRetry={() => refetch()}
 />
 ) : isEmpty ? (
 <div className="py-10 text-center">
 <Sparkles className="h-8 w-8 mx-auto text-primary opacity-50 mb-2" />
 <p className="text-sm text-muted-foreground">
 Nie ma jeszcze rekrutacji w systemie. Możesz pominąć ten krok —
 wrócisz do niego, gdy będzie co oznaczać.
 </p>
 </div>
 ) : filtered.length === 0 ? (
 <p className="py-10 text-center text-sm text-muted-foreground">
 Brak rekrutacji pasujących do „{search}".
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
 disabled={isBlocked}
 title={
 isBlocked
 ?"Najpierw wczytaj listę rekrutacji — inaczej zapiszesz pusty wybór na stałe."
 : undefined
 }
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
