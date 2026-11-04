"use client";

/**
 * Harness wizualny formularza Generatora Umów B2B — przede wszystkim
 * przełącznik „Umowa JDG / Umowa spółka” (ticket 8, 28.09.2026) i pola
 * komparycji spółki z KRS.
 *
 * ZERO zapytań: zasiane są stałe klucze formularza (obszary, numer, klienci)
 * z `updatedAt` w przyszłości, a interceptor odrzuca każde żądanie — lookup
 * NIP/KRS w harnessie kończy się komunikatem „Nie znaleziono”, pola wpisuje
 * się ręcznie. Dane fikcyjne.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { GeneratorForm } from "@/components/v2/pages/B2BContractGeneratorV2";
import { api, type B2BRole } from "@/lib/api";

const FUTURE = Date.now() + 365 * 24 * 3600 * 1000;

const ROLES: B2BRole[] = [
  {
    id: 1,
    category_key: "dev",
    category_label_pl: "Programowanie",
    category_label_en: "Development",
    slug: "java",
    name_pl: "Programista Java",
    name_en: "Java Developer",
    area_label_pl: "Java",
    area_label_en: "Java",
    scope_pl: ["Rozwój aplikacji."],
    scope_en: ["Application development."],
    display_order: 0,
    is_active: true,
  },
];

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  const opts = { updatedAt: FUTURE };
  qc.setQueryData(["b2b-roles"], ROLES, opts);
  qc.setQueryData(
    ["b2b-next-number"],
    { contract_number: "4242/2026", year: 2026, seq: 4242 },
    opts,
  );
  qc.setQueryData(
    ["b2b-clients-lookup"],
    [{ id: 1, name: "Przykładowy Bank S.A." }],
    opts,
  );
  return qc;
}

function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(
          new Error("Harness /preview/b2b-generator nie wysyła zapytań."),
          { isAxiosError: true, code: "ERR_PREVIEW_OFFLINE" },
        ),
      ),
    ),
  );
  useEffect(
    () => () => {
      api.interceptors.request.eject(interceptorId);
    },
    [interceptorId],
  );
}

function Harness() {
  useNetworkBlocked();
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <h1 className="text-lg font-semibold">Generator Umów B2B — formularz</h1>
      <GeneratorForm />
    </div>
  );
}

export default function B2BGeneratorPreviewPage() {
  const [client] = useState(seededClient);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <Harness />
      </ToastProvider>
    </QueryClientProvider>
  );
}
