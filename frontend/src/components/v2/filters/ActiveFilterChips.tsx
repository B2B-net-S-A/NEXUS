"use client";

import { useMemo } from"react";
import { useQuery } from"@tanstack/react-query";
import { X } from"lucide-react";
import api from"@/lib/api";
import type { CandidateFilters } from"@/lib/url-filters";
import {
 parseSkillExpression,
 serializeSkillBuckets,
} from"@/lib/skill-expression";

interface TalentPoolLite {
 id: number;
 name: string;
}

interface NamedLookup {
 id: number;
 name: string;
}

interface ActiveFilterChipsProps {
 filters: CandidateFilters;
 onUpdate: (next: Partial<CandidateFilters>) => void;
 poolsById?: Map<number, string>;
 usersById?: Map<number, string>;
 clientsById?: Map<number, string>;
}

const REMOTE_LABELS: Record<string, string> = {
 remote: "Zdalnie",
 hybrid: "Hybryda",
 onsite: "Stacjonarnie",
};

const STATUS_LABELS: Record<string, string> = {
 active: "Aktywni",
 passive: "Pasywni",
 blacklisted: "Zablokowani",
};

const EMPLOYMENT_LABELS: Record<string, string> = {
 at_client: "U klienta",
 available: "Dostępni",
};

const AVAILABILITY_LABELS: Record<string, string> = {
 actively_looking: "Aktywnie szuka",
 open_to_offers: "Otwarty",
 not_looking: "Nie szuka",
 unknown: "Nie wiemy",
};

const STAGE_LABELS: Record<string, string> = {
 new: "Nowy",
 prep_call: "Prep call",
 screening: "Screening",
 verified: "Zweryfikowany",
 interview: "Interview",
 cv_sent: "CV wysłane",
 client_interview: "Rozmowa u klienta",
 acceptance: "Akceptacja",
 negotiation: "Negocjacje",
 onboarding: "Onboarding",
 hired: "Zatrudniony",
 rejected: "Odrzucony",
 withdrawn: "Wycofany",
};

interface Chip {
 key: string;
 label: string;
 clear: () => void;
}

function collectChips(
 filters: CandidateFilters,
 onUpdate: (next: Partial<CandidateFilters>) => void,
 poolsById?: Map<number, string>,
 usersById?: Map<number, string>,
 clientsById?: Map<number, string>
): Chip[] {
 const chips: Chip[] = [];

 if (filters.q) {
 chips.push({
 key: "q",
 label: `„${filters.q}"`,
 clear: () => onUpdate({ q: "", page: 1 }),
 });
 }
 filters.status.forEach((s) => {
 chips.push({
 key: `status:${s}`,
 label: `Status: ${STATUS_LABELS[s] ?? s}`,
 clear: () =>
 onUpdate({
 status: filters.status.filter((x) => x !== s),
 page: 1,
 }),
 });
 });
 filters.employment.forEach((e) => {
 chips.push({
 key: `employment:${e}`,
 label: `Zatrudnienie: ${EMPLOYMENT_LABELS[e] ?? e}`,
 clear: () =>
 onUpdate({
 employment: filters.employment.filter((x) => x !== e),
 page: 1,
 }),
 });
 });
 filters.availability.forEach((a) => {
 chips.push({
 key: `availability:${a}`,
 label: `Dyspozycyjność: ${AVAILABILITY_LABELS[a] ?? a}`,
 clear: () =>
 onUpdate({
 availability: filters.availability.filter((x) => x !== a),
 page: 1,
 }),
 });
 });
 filters.pipelineStage.forEach((s) => {
 chips.push({
 key: `stage:${s}`,
 label: `Etap: ${STAGE_LABELS[s] ?? s}`,
 clear: () =>
 onUpdate({
 pipelineStage: filters.pipelineStage.filter((x) => x !== s),
 page: 1,
 }),
 });
 });
 // Stage-move "who" — correlated with the stage chip above.
 filters.stageMovedByIds.forEach((id) => {
 const name =
 id === 0
 ?"Import systemowy"
 : (usersById?.get(id) ?? `Użytkownik #${id}`);
 chips.push({
 key: `stage_by:${id}`,
 label: `Etap dodał: ${name}`,
 clear: () =>
 onUpdate({
 stageMovedByIds: filters.stageMovedByIds.filter((x) => x !== id),
 page: 1,
 }),
 });
 });
 // Stage-move "when" — single chip for the (inclusive) date range.
 if (filters.stageMovedAfter || filters.stageMovedBefore) {
 const from = filters.stageMovedAfter ||"…";
 const to = filters.stageMovedBefore ||"…";
 chips.push({
 key: "stage_date",
 label: `Etap dodany: ${from} – ${to}`,
 clear: () =>
 onUpdate({ stageMovedAfter: "", stageMovedBefore: "", page: 1 }),
 });
 }
 // Stage-move "client" — the client owning the job where the move happened.
 filters.stageClientIds.forEach((id) => {
 const name = clientsById?.get(id) ?? `Klient #${id}`;
 chips.push({
 key: `stage_client:${id}`,
 label: `Etap u klienta: ${name}`,
 clear: () =>
 onUpdate({
 stageClientIds: filters.stageClientIds.filter((x) => x !== id),
 page: 1,
 }),
 });
 });
 // "Aktualny etap" toggle.
 if (filters.stageCurrentOnly) {
 chips.push({
 key: "stage_current",
 label: "Tylko aktualny etap",
 clear: () => onUpdate({ stageCurrentOnly: false, page: 1 }),
 });
 }
 if (filters.location) {
 chips.push({
 key: "loc",
 label: `📍 ${filters.location}`,
 clear: () => onUpdate({ location: "", page: 1 }),
 });
 }
 filters.remote.forEach((mode) => {
 chips.push({
 key: `remote:${mode}`,
 label: REMOTE_LABELS[mode] ?? mode,
 clear: () =>
 onUpdate({
 remote: filters.remote.filter((m) => m !== mode),
 page: 1,
 }),
 });
 });
 // Skill boolean expression → must / OR-group / NOT chips. Removing a chip
 // rebuilds the expression without that constraint.
 const skillBuckets = parseSkillExpression(filters.skillsExpr);
 const rebuildSkills = (next: typeof skillBuckets) =>
 onUpdate({ skillsExpr: serializeSkillBuckets(next), page: 1 });
 skillBuckets.must.forEach((skill, i) => {
 chips.push({
 key: `skill-must:${skill}:${i}`,
 label: skill,
 clear: () =>
 rebuildSkills({
 ...skillBuckets,
 must: skillBuckets.must.filter((_, idx) => idx !== i),
 }),
 });
 });
 skillBuckets.anyGroups.forEach((group, i) => {
 chips.push({
 key: `skill-any:${i}`,
 label: group.join(" lub "),
 clear: () =>
 rebuildSkills({
 ...skillBuckets,
 anyGroups: skillBuckets.anyGroups.filter((_, idx) => idx !== i),
 }),
 });
 });
 skillBuckets.none.forEach((skill, i) => {
 chips.push({
 key: `skill-none:${skill}:${i}`,
 label: `bez ${skill}`,
 clear: () =>
 rebuildSkills({
 ...skillBuckets,
 none: skillBuckets.none.filter((_, idx) => idx !== i),
 }),
 });
 });
 filters.poolIds.forEach((id) => {
 const name = poolsById?.get(id) ?? `Pula #${id}`;
 chips.push({
 key: `pool:${id}`,
 label: `Pula: ${name}`,
 clear: () =>
 onUpdate({
 poolIds: filters.poolIds.filter((x) => x !== id),
 page: 1,
 }),
 });
 });
 filters.addedByIds.forEach((id) => {
 const name =
 id === 0
 ?"Import systemowy"
 : (usersById?.get(id) ?? `Użytkownik #${id}`);
 chips.push({
 key: `added_by:${id}`,
 label: `Dodał: ${name}`,
 clear: () =>
 onUpdate({
 addedByIds: filters.addedByIds.filter((x) => x !== id),
 page: 1,
 }),
 });
 });
 filters.currentCompany.forEach((name) => {
 chips.push({
 key: `cur_co:${name}`,
 label: `Obecna firma: ${name}`,
 clear: () =>
 onUpdate({
 currentCompany: filters.currentCompany.filter((x) => x !== name),
 page: 1,
 }),
 });
 });
 filters.pastCompany.forEach((name) => {
 chips.push({
 key: `past_co:${name}`,
 label: `Poprz. firma: ${name}`,
 clear: () =>
 onUpdate({
 pastCompany: filters.pastCompany.filter((x) => x !== name),
 page: 1,
 }),
 });
 });
 filters.currentTitle.forEach((role) => {
 chips.push({
 key: `title:${role}`,
 label: `Stanowisko: ${role}`,
 clear: () =>
 onUpdate({
 currentTitle: filters.currentTitle.filter((x) => x !== role),
 page: 1,
 }),
 });
 });
 filters.workedAtClientIds.forEach((id) => {
 const name = clientsById?.get(id) ?? `Klient #${id}`;
 chips.push({
 key: `client_hist:${id}`,
 label: `Klient: ${name}`,
 clear: () =>
 onUpdate({
 workedAtClientIds: filters.workedAtClientIds.filter((x) => x !== id),
 page: 1,
 }),
 });
 });
 if (filters.experienceMin !== null || filters.experienceMax !== null) {
 const lo = filters.experienceMin;
 const hi = filters.experienceMax;
 const label =
 lo !== null && hi !== null
 ? `Doświadczenie: ${lo}–${hi} lat`
 : lo !== null
 ? `Doświadczenie: od ${lo} lat`
 : `Doświadczenie: do ${hi} lat`;
 chips.push({
 key: "experience",
 label,
 clear: () =>
 onUpdate({ experienceMin: null, experienceMax: null, page: 1 }),
 });
 }
 if (filters.rateMin !== null || filters.rateMax !== null) {
 const lo = filters.rateMin;
 const hi = filters.rateMax;
 const label =
 lo !== null && hi !== null
 ? `Stawka: ${lo}–${hi} PLN/h`
 : lo !== null
 ? `Stawka: od ${lo} PLN/h`
 : `Stawka: do ${hi} PLN/h`;
 chips.push({
 key: "rate",
 label,
 clear: () => onUpdate({ rateMin: null, rateMax: null, page: 1 }),
 });
 }
 filters.qAll.forEach((phrase) => {
 chips.push({
 key: `q_all:${phrase}`,
 label: `Wszystkie: „${phrase}"`,
 clear: () =>
 onUpdate({
 qAll: filters.qAll.filter((x) => x !== phrase),
 page: 1,
 }),
 });
 });
 filters.qAny.forEach((group, gi) => {
 group.forEach((phrase) => {
 chips.push({
 key: `q_any:${gi}:${phrase}`,
 label:
 filters.qAny.length > 1
 ? `Grupa ${gi + 1}: „${phrase}"`
 : `Którakolwiek: „${phrase}"`,
 clear: () =>
 onUpdate({
 qAny: filters.qAny
 .map((g, i) => (i === gi ? g.filter((x) => x !== phrase) : g))
 .filter((g) => g.length > 0),
 page: 1,
 }),
 });
 });
 });
 filters.qNone.forEach((phrase) => {
 chips.push({
 key: `q_none:${phrase}`,
 label: `Żadna: „${phrase}"`,
 clear: () =>
 onUpdate({
 qNone: filters.qNone.filter((x) => x !== phrase),
 page: 1,
 }),
 });
 });
 return chips;
}

export function ActiveFilterChips({
 filters,
 onUpdate,
 poolsById,
 usersById,
 clientsById,
}: ActiveFilterChipsProps) {
 // Hit the same React Query cache key as <TalentPoolMultiSelect> (staleTime
 // 60s) — gdy filter dropdown był otwarty w tej sesji, to read jest cache-hit
 // bez extra HTTP. Bez tego chip pokazywał "Pula #4" zamiast "Java Backend
 // Senior" gdy user wrócił z URL share / saved search.
 const { data: poolsData } = useQuery<TalentPoolLite[]>({
 queryKey: ["talent-pools-lite"],
 queryFn: () => api.get("/api/talent-pools").then((r) => r.data),
 staleTime: 60_000,
 enabled: filters.poolIds.length > 0 && !poolsById,
 });
 const resolvedPools = useMemo(() => {
 if (poolsById) return poolsById;
 if (!poolsData) return undefined;
 return new Map(poolsData.map((p) => [p.id, p.name] as const));
 }, [poolsById, poolsData]);

 // Resolve recruiter names for the "Dodał" / "Etap dodał" chips. Shares the
 // `users-directory` react-query key with <UserMultiSelect> (staleTime 60s),
 // so this is a cache-hit once that picker was opened. Without it the chips
 // fall back to "Użytkownik #N" after a URL share / saved-search restore.
 const needsUsers =
 filters.addedByIds.length > 0 || filters.stageMovedByIds.length > 0;
 const { data: usersData } = useQuery<NamedLookup[]>({
 queryKey: ["users-directory"],
 queryFn: () => api.get("/api/users").then((r) => r.data),
 staleTime: 60_000,
 enabled: needsUsers && !usersById,
 });
 const resolvedUsers = useMemo(() => {
 if (usersById) return usersById;
 if (!usersData) return undefined;
 return new Map(usersData.map((u) => [u.id, u.name] as const));
 }, [usersById, usersData]);

 // Resolve client names for the "Klient" / "Etap u klienta" chips. Shares the
 // `clients-lookup` react-query key with <ClientMultiSelect> (staleTime 60s), so
 // this is a cache-hit once that picker was opened. Without it the chips fall
 // back to "Klient #N" after a URL share / saved-search restore.
 const needsClients =
 filters.workedAtClientIds.length > 0 || filters.stageClientIds.length > 0;
 const { data: clientsData } = useQuery<NamedLookup[]>({
 queryKey: ["clients-lookup"],
 queryFn: () => api.get("/api/clients-lookup").then((r) => r.data),
 staleTime: 60_000,
 enabled: needsClients && !clientsById,
 });
 const resolvedClients = useMemo(() => {
 if (clientsById) return clientsById;
 if (!clientsData) return undefined;
 return new Map(clientsData.map((c) => [c.id, c.name] as const));
 }, [clientsById, clientsData]);

 const chips = collectChips(filters, onUpdate, resolvedPools, resolvedUsers, resolvedClients);
 if (chips.length === 0) return null;

 const clearAll = () =>
 onUpdate({
 q: "",
 status: [],
 employment: [],
 availability: [],
 pipelineStage: [],
 location: "",
 remote: [],
 skillsExpr: "",
 poolIds: [],
 addedByIds: [],
 currentCompany: [],
 pastCompany: [],
 currentTitle: [],
 workedAtClientIds: [],
 experienceMin: null,
 experienceMax: null,
 rateMin: null,
 rateMax: null,
 stageMovedByIds: [],
 stageMovedAfter: "",
 stageMovedBefore: "",
 stageClientIds: [],
 stageCurrentOnly: false,
 qAll: [],
 qAny: [],
 qNone: [],
 page: 1,
 });

 return (
 <div className="flex flex-wrap items-center gap-1.5">
 {chips.map((chip) => (
 <button
 key={chip.key}
 onClick={chip.clear}
 className="group inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary hover:bg-primary hover:text-white transition-colors"
 aria-label={`Usuń filtr: ${chip.label}`}
 >
 <span className="truncate max-w-[180px]">{chip.label}</span>
 <X className="h-3 w-3 opacity-70 group-hover:opacity-100" />
 </button>
 ))}
 <button
 onClick={clearAll}
 className="text-xs text-muted-foreground hover:text-primary ml-1"
 >
 Wyczyść wszystko
 </button>
 </div>
 );
}
