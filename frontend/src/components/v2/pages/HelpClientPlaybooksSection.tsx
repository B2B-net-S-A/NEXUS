"use client";

/**
 * Pomoc → Klienci — procedura per klient GENEROWANA z karty klienta (D11).
 *
 * Lista klientów z kartą po lewej, po prawej pełna karta (`ClientPlaybookCard`
 * w wariancie `full`): fakty, „co powiedzieć kandydatowi", reguły priorytetu,
 * zasady procesu i onboarding (markdown), dokumenty. Pomoc nie ma tu żadnej
 * własnej treści — zastępuje 14 wzorów Word per klient, które czytał każdy
 * zalogowany. Link „Edytuj kartę" (tylko DL/admin) prowadzi do profilu klienta.
 *
 * `?client=<id>` to cel linku „Pełna karta klienta →" ze strony rekrutacji
 * (D13): rekruter nie przejdzie przez middleware `/clients`, a Pomoc czyta
 * każdy zalogowany. Czytane efektem, nie inicjalizatorem — miękka nawigacja
 * App Routera nie odmontowuje sekcji.
 *
 * Lista niesie PEŁNE karty, więc zasiewa cache `["client-playbook", id]` —
 * prawy panel nie robi GET per klient.
 *
 * Cztery gałęzie w kolejności błąd → ładowanie → pusto → dane; pusty stan
 * dopiero po `isSuccess`, a awaria to alert z ponowieniem, nigdy pustka.
 */

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Building2, Search } from "lucide-react";

import { ClientPlaybookCard } from "@/components/client-playbook/ClientPlaybookCard";
import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Input } from "@/components/ui/input";
import { useClientPlaybooksOverview } from "@/lib/client-playbooks";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

// Zakres U+0300–U+036F = znaki łączące po NFD (usuwa ogonki i kreski);
// „ł" nie rozkłada się w NFD, stąd osobna podmiana.
const fold = (value: string) =>
  value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l");

function parseClientParam(raw: string | null): number | null {
  const parsed = Number.parseInt(raw ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function HelpClientPlaybooksSection() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const requestedClient = parseClientParam(searchParams.get("client"));
  const [rawQuery, setRawQuery] = useState("");
  const debouncedQuery = useDebouncedValue(rawQuery, 250);
  const [selectedId, setSelectedId] = useState<number | null>(requestedClient);
  useEffect(() => {
    if (requestedClient !== null) setSelectedId(requestedClient);
  }, [requestedClient]);

  const listQuery = useClientPlaybooksOverview();

  // Klucz i staleTime identyczne z `useClientPlaybook` — zasiane dane są
  // świeże, więc karta w prawym panelu nie strzela po nie drugi raz.
  useEffect(() => {
    for (const item of listQuery.data?.items ?? []) {
      queryClient.setQueryData(["client-playbook", item.client_id], item);
    }
  }, [listQuery.data, queryClient]);

  const allItems = useMemo(() => listQuery.data?.items ?? [], [listQuery.data]);
  const items = useMemo(() => {
    const q = fold(debouncedQuery.trim());
    return allItems
      .filter((item) => !q || fold(item.client_name ?? "").includes(q))
      .sort((a, b) => (a.client_name ?? "").localeCompare(b.client_name ?? "", "pl"));
  }, [allItems, debouncedQuery]);

  // Auto-wybór pierwszego (wzorzec listy procedur), ale DOPIERO po sukcesie:
  // pusta lista sprzed odpowiedzi kasowałaby klienta wskazanego w adresie.
  useEffect(() => {
    if (!listQuery.isSuccess) return;
    if (items.length === 0) {
      setSelectedId(null);
      return;
    }
    if (selectedId === null || !items.some((item) => item.client_id === selectedId)) {
      setSelectedId(items[0].client_id);
    }
  }, [items, selectedId, listQuery.isSuccess]);

  const state = resolveViewState({
    isLoading: listQuery.isLoading,
    isError: listQuery.isError,
    error: listQuery.error,
    isSuccess: listQuery.isSuccess,
    isEmpty: allItems.length === 0,
  });

  if (state === "loading") {
    return <p className="p-4 text-sm text-muted-foreground">Ładowanie kart klientów…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return (
      <QueryStateNotice
        state={state}
        description={
          state === "error" ? "Nie udało się wczytać listy kart klientów." : undefined
        }
        onRetry={state === "error" ? () => void listQuery.refetch() : undefined}
      />
    );
  }
  if (state === "empty") {
    return (
      <EmptyState
        icon={Building2}
        title="Żaden klient nie ma jeszcze karty"
        description="Karty zakładają Delivery Leadowie w profilu klienta (Zasady współpracy) albo w Ustawieniach → Reguły CV → Karta klienta."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] gap-4">
      <aside className="space-y-3 md:sticky md:top-4 md:self-start">
        <Input
          leadingIcon={<Search className="h-4 w-4" />}
          placeholder="Szukaj klienta…"
          value={rawQuery}
          onChange={(e) => setRawQuery(e.target.value)}
          aria-label="Szukaj klienta"
        />
        <nav
          aria-label="Lista kart klientów"
          className="rounded-lg border border-border bg-card overflow-hidden"
        >
          {items.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              Brak wyników dla tego zapytania.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {items.map((item) => {
                const active = item.client_id === selectedId;
                return (
                  <li key={item.client_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(item.client_id)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "w-full text-left px-4 py-3 transition-colors hover:bg-primary/10",
                        active && "bg-primary/10",
                      )}
                    >
                      <span className="block text-sm font-medium text-foreground truncate">
                        {item.client_name ?? `#${item.client_id}`}
                      </span>
                      <span className="block text-xs text-muted-foreground mt-0.5">
                        {`wersja ${item.version}${
                          item.updated_at
                            ? ` · ${new Date(item.updated_at).toLocaleDateString("pl-PL")}`
                            : ""
                        }`}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </nav>
        <p className="text-xs text-muted-foreground px-1">
          {items.length} z {allItems.length}
        </p>
      </aside>
      <section className="rounded-lg border border-border bg-card min-h-[400px] p-6">
        {selectedId === null ? (
          <p className="text-sm text-muted-foreground">Wybierz klienta z listy.</p>
        ) : (
          <ClientPlaybookCard
            clientId={selectedId}
            variant="full"
            editHref={`/clients/${selectedId}?tab=zasady`}
          />
        )}
      </section>
    </div>
  );
}
