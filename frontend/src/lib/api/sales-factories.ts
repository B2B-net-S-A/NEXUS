// Sprzedaż → lejek Fabryki IT mierzony kontaktem (10.11.2026).
//
// Lustro `backend/app/api/sales_factories.py`. Wiersze listy kont daje
// `useOpportunities`; tu są liczniki map, kolejka osób i liczniki „Kogo znamy”.
// Klucze map i kolejki zaczynają się od „sales”, więc każdy zapis w Sprzedaży
// je odświeża. Liczniki „Kogo znamy” mają własny klucz: to skan bazy kandydatów
// i nie może ruszać po każdej poprawce osoby na mapie.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

import type { DecisionMapEntry, Ref } from "./sales";

/** Klucz lejka z importu Atlasa (`decision_map.IT_FACTORIES_PIPELINE_KEY`). */
export const IT_FACTORIES_PIPELINE_KEY = "atlas-it-factories";

/** Firma jest klientem NEXUSA: temat prowadzi Delivery Lead. */
export interface FactoryClient {
  name: string;
  delivery_lead: string | null;
}

export interface FactoryAccount {
  opportunity_id: number;
  company_id: number;
  map_total: number;
  map_contacted: number;
  /** Poziom 1 i 2 (zarząd, dyrektorzy). */
  top_total: number;
  top_contacted: number;
  /** Poziom 1 i 2 bez kontaktu i bez sprzeciwu. */
  waiting: number;
  /** Etap mówi o kontakcie, a na mapie nikt go nie ma. Podpowiedź, nie blokada. */
  stage_mismatch: boolean;
  client: FactoryClient | null;
}

export interface FactoryQueuePerson {
  opportunity: { id: number; title: string };
  company: Ref;
  client: FactoryClient | null;
  person: DecisionMapEntry;
}

export interface FactoryQueue {
  owner: Ref;
  people: FactoryQueuePerson[];
  /** Poziom 3 i 4 oraz osoby bez poziomu: zwinięte, nic nie znika. */
  lower_levels: FactoryQueuePerson[];
}

export interface KnownCounts {
  company_id: number;
  current: number;
  past: number;
  via_us: number;
  unknown: number;
}

export interface KnownPeople {
  items: KnownCounts[];
  /** Skan trafił w sufit wierszy: liczby są dolną granicą. */
  truncated: boolean;
}

export const factoryKeys = {
  accounts: (archived: boolean) => ["sales", "it-factories", "accounts", archived] as const,
  queue: (ownerId: number | null) => ["sales", "it-factories", "queue", ownerId] as const,
  known: (archived: boolean) => ["it-factories-known-people", archived] as const,
};

export function useFactoryAccounts(archived: boolean, enabled = true) {
  return useQuery({
    queryKey: factoryKeys.accounts(archived),
    queryFn: async () =>
      (
        await api.get<{ items: FactoryAccount[] }>("/api/sales/it-factories/accounts", {
          params: archived ? { archived: true } : undefined,
        })
      ).data.items,
    enabled,
  });
}

/** `ownerId = null` to kolejka zalogowanej osoby. */
export function useFactoryQueue(ownerId: number | null, enabled = true) {
  return useQuery({
    queryKey: factoryKeys.queue(ownerId),
    queryFn: async () =>
      (
        await api.get<FactoryQueue>("/api/sales/it-factories/queue", {
          params: ownerId ? { owner_id: ownerId } : undefined,
        })
      ).data,
    enabled,
  });
}

/** Skan bazy kandydatów trwa sekundy, więc wynik żyje dłużej niż reszta listy. */
export function useFactoryKnownPeople(archived: boolean, enabled = true) {
  return useQuery({
    queryKey: factoryKeys.known(archived),
    queryFn: async () =>
      (
        await api.get<KnownPeople>("/api/sales/it-factories/known-people", {
          params: archived ? { archived: true } : undefined,
        })
      ).data,
    enabled,
    staleTime: 10 * 60 * 1000,
  });
}
