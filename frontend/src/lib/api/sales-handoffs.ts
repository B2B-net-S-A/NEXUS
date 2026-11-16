// Sprzedaż → przekazanie spotkania i werdykt (10.11.2026).
//
// Lustro `backend/app/api/sales_handoffs.py` i trasy `/api/sales/companies/identity`.
// Listy są zawsze dla zalogowanej osoby: przełącznika osoby tu nie ma i nie będzie.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { salesKeys, type Ref } from "@/lib/api/sales";

export type HandoffPhase = "no_term" | "upcoming" | "confirm" | "verdict" | "done";
export type HandoffVerdict = "qualified" | "not_now" | "not_a_fit" | "no_show";

export interface HandoffPerson {
  id: number;
  name: string;
  title: string | null;
  phone: string | null;
  email: string | null;
  do_not_contact: boolean;
}

export interface Handoff {
  opportunity: Ref;
  company: Ref;
  status: "open" | "won" | "lost";
  stage_key: string;
  stage_name: string;
  /** Prowadzący spotkanie, czyli opiekun szansy. */
  host: Ref | null;
  /** Osoba, która umówiła spotkanie. */
  booked_by: Ref | null;
  booked_at: string | null;
  meeting_at: string | null;
  duration_minutes: number;
  /** Termin czytany z kalendarza Outlook: zmienia się go w Outlooku. */
  from_calendar: boolean;
  service: string | null;
  problem: string | null;
  decision_maker: string | null;
  timing: string | null;
  contact: HandoffPerson | null;
  confirmed_at: string | null;
  verdict: HandoffVerdict | null;
  verdict_at: string | null;
  verdict_reason: string | null;
  return_on: string | null;
  phase: HandoffPhase;
  /** Inne przekazane spotkanie tej osoby nachodzi na ten termin. */
  clash: boolean;
  /** Kiedy prowadzący wysłał zaproszenie z Outlooka. */
  invite_sent_at?: string | null;
}

export interface InviteRecipient {
  address: string;
  name: string | null;
  /** Adres jest w bazie kandydatów: ze Sprzedaży go nie zapraszamy. */
  blocked: "candidate" | null;
}

export interface InviteDraft {
  mailbox: "ok" | "missing" | "no_calendar_scope";
  subject: string;
  recipients: InviteRecipient[];
  meeting_at: string | null;
  duration_minutes: number;
  sent_at: string | null;
  /** Treść zaproszenia wpisana przy umawianiu (lista dzwoniących 13.11.2026). */
  message?: string | null;
}

export interface InviteInput {
  opportunity_id: number;
  subject: string;
  to: string[];
  message: string | null;
  /** Klucz jednej wysyłki: drugi klik z tym samym kluczem nie wysyła drugiego zaproszenia. */
  request_id: string;
}

export interface HandoffWeek {
  week_start: string;
  booked: number;
  held: number;
  qualified: number;
}

export interface Handoffs {
  to_me: Handoff[];
  booked_by_me: Handoff[];
  weeks: HandoffWeek[];
}

export interface HandoffForm {
  hosts: Ref[];
  default_host_id: number | null;
}

export interface BusySpan {
  start: string;
  end: string;
}

export interface HostBusy {
  /** `unavailable`: skrzynka prowadzącego nie jest połączona, widać tylko spotkania ze Sprzedaży. */
  calendar: "ok" | "unavailable";
  busy: BusySpan[];
}

export interface BookMeetingInput {
  company_id?: number;
  new_company?: { name: string; website_url?: string | null; domain?: string | null; allow_duplicate?: boolean };
  opportunity_id?: number;
  company_domain?: string | null;
  contact_id?: number;
  new_contact?: { full_name: string; title?: string | null; email?: string | null; phone?: string | null };
  host_user_id: number;
  meeting_at?: string | null;
  duration_minutes?: number;
  service?: string | null;
  problem?: string | null;
  decision_maker?: string | null;
  timing?: string | null;
  /** Treść zaproszenia i adres klienta: podpowiedź do okna zaproszenia prowadzącego. */
  invite_message?: string | null;
  invite_to?: string | null;
}

export interface VerdictInput {
  opportunity_id: number;
  kind: HandoffVerdict;
  reason?: string | null;
  return_on?: string | null;
}

export interface CompanyIdentityMatch {
  id: number;
  name: string;
  hq_city: string | null;
  domain: string | null;
  open_opportunities: number;
  reason: "name" | "domain" | "similar";
}

export interface CompanyIdentity {
  domain: string | null;
  domain_source: "website" | "email" | null;
  matches: CompanyIdentityMatch[];
}

export const handoffKeys = {
  mine: [...salesKeys.all, "handoffs"] as const,
  form: [...salesKeys.all, "handoffs", "form"] as const,
  busy: (hostId: number | null, day: string | null) => [...salesKeys.all, "handoffs", "busy", hostId, day] as const,
  opportunity: (id: number) => [...salesKeys.all, "handoffs", "opportunity", id] as const,
  identity: (name: string, email: string, website: string) =>
    [...salesKeys.all, "company-identity", name, email, website] as const,
};

function useInvalidateSales() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: salesKeys.all });
}

/** Spotkania przekazane zalogowanej osobie i te, które sama umówiła. */
export function useHandoffs() {
  return useQuery({
    queryKey: handoffKeys.mine,
    queryFn: async () => (await api.get<Handoffs>("/api/sales/handoffs")).data,
  });
}

export function useHandoffForm(enabled = true) {
  return useQuery({
    queryKey: handoffKeys.form,
    queryFn: async () => (await api.get<HandoffForm>("/api/sales/handoffs/form")).data,
    enabled,
    staleTime: 60_000,
  });
}

/** Zajęte godziny prowadzącego w dniu `RRRR-MM-DD`; bez prowadzącego albo dnia nie pyta. */
export function useHostBusy(hostId: number | null, day: string | null) {
  return useQuery({
    queryKey: handoffKeys.busy(hostId, day),
    queryFn: async () =>
      (await api.get<HostBusy>("/api/sales/handoffs/host-busy", { params: { host_id: hostId, day } })).data,
    enabled: hostId != null && day != null,
    staleTime: 60_000,
  });
}

export function useOpportunityHandoff(opportunityId: number) {
  return useQuery({
    queryKey: handoffKeys.opportunity(opportunityId),
    queryFn: async () =>
      (await api.get<Handoff | null>(`/api/sales/handoffs/by-opportunity/${opportunityId}`)).data,
    enabled: Number.isFinite(opportunityId) && opportunityId > 0,
  });
}

export function useBookMeeting() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: BookMeetingInput) => (await api.post<Handoff>("/api/sales/handoffs", payload)).data,
    onSuccess: invalidate,
  });
}

export function useSetHandoffTerm() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { opportunity_id: number; meeting_at: string | null; duration_minutes: number }) => {
      const { opportunity_id, ...payload } = input;
      return (await api.put<Handoff>(`/api/sales/handoffs/${opportunity_id}/term`, payload)).data;
    },
    onSuccess: invalidate,
  });
}

export function useConfirmHandoff() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (opportunityId: number) =>
      (await api.post<Handoff>(`/api/sales/handoffs/${opportunityId}/confirm`)).data,
    onSuccess: invalidate,
  });
}

export function useGiveVerdict() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: VerdictInput) => {
      const { opportunity_id, ...payload } = input;
      return (await api.post<Handoff>(`/api/sales/handoffs/${opportunity_id}/verdict`, payload)).data;
    },
    onSuccess: invalidate,
  });
}

/** Okno „Wyślij zaproszenie”: stan skrzynki prowadzącego, temat i adresat. */
export function useInviteDraft(opportunityId: number) {
  return useQuery({
    queryKey: [...handoffKeys.opportunity(opportunityId), "invite"] as const,
    queryFn: async () => (await api.get<InviteDraft>(`/api/sales/handoffs/${opportunityId}/invite`)).data,
    // Okno pokazuje stan z chwili otwarcia; wysyłka i tak sprawdza wszystko na serwerze.
    staleTime: 0,
    gcTime: 0,
  });
}

export function useSendInvite() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: InviteInput) => {
      const { opportunity_id, ...payload } = input;
      return (await api.post<Handoff>(`/api/sales/handoffs/${opportunity_id}/invite`, payload)).data;
    },
    onSuccess: invalidate,
  });
}

const IDENTITY_MIN_CHARS = 2;

/**
 * Tożsamość firmy przy zakładaniu: karty, które już mogą nią być, i domena z adresu
 * strony albo maila osoby. To podpowiedź: niczego nie blokuje i bez niej formularz działa.
 */
export function useCompanyIdentity(
  input: { name?: string; email?: string; website?: string; excludeId?: number },
  enabled = true,
) {
  const name = (input.name ?? "").trim();
  const email = (input.email ?? "").trim();
  const website = (input.website ?? "").trim();
  const hasText = name.length >= IDENTITY_MIN_CHARS || email.includes("@") || website.includes(".");
  return useQuery({
    queryKey: [...handoffKeys.identity(name, email, website), input.excludeId ?? null] as const,
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (name) params.name = name;
      if (email) params.email = email;
      if (website) params.website = website;
      if (input.excludeId) params.exclude_id = String(input.excludeId);
      return (await api.get<CompanyIdentity>("/api/sales/companies/identity", { params })).data;
    },
    enabled: enabled && hasText,
    staleTime: 60_000,
  });
}
