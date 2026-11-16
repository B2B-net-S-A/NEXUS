"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { ChevronRight, Search, X } from "lucide-react";

import { CallButton, MailLink, looksLikePhone } from "@/components/phone-preview/contact";
import { PREVIEW_PATH } from "@/components/phone-preview/access";
import { Block, Loaded, Rows } from "@/components/phone-preview/ui";
import { api } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";

// „Szukaj” na telefonie (decyzja Artura 14.11.2026): kandydat po imieniu, mailu
// albo numerze (np. z nieodebranego połączenia), kontakt u klienta, rekrutacja.
// Najwyżej 5 wyników na grupę, bez przeglądania listy.

interface Hit { id: number; name: string; subtitle: string }
interface GlobalSearch { candidates: Hit[]; jobs: Hit[] }
interface ClientContact { id: number; name: string; position: string | null; client_name: string | null; phone: string | null; email: string | null }

export default function PhonePreviewSearchPage() {
  const [q, setQ] = useState("");
  const term = useDebouncedValue(q.trim(), 250);
  const enabled = term.length >= 2;
  const phone = looksLikePhone(term);
  const global = useQuery({
    queryKey: ["phone-preview", "search", term],
    queryFn: () => api.get<GlobalSearch>("/api/search/global", { params: { q: term } }).then((r) => r.data),
    enabled,
  });
  const contacts = useQuery({
    queryKey: ["phone-preview", "contacts", term],
    // 403 = rola bez kontaktów klientów (np. DL bez portfela): to brak dostępu,
    // nie awaria, więc sekcja znika zamiast pokazywać błąd.
    queryFn: () =>
      api
        .get<ClientContact[]>("/api/contacts", { params: { search: term } })
        .then((r): ClientContact[] | null => r.data.slice(0, 5))
        .catch((e: unknown) => {
          if (isAxiosError(e) && e.response?.status === 403) return null;
          throw e;
        }),
    enabled: enabled && !phone,
  });
  return (
    <div className="pb-6">
      <header className="sticky top-0 z-10 border-b bg-card px-4 pb-3 pt-3">
        <h1 className="text-xl font-semibold leading-tight">Szukaj</h1>
        <label className="mt-2 flex h-12 items-center gap-2 rounded-xl border bg-background px-3 focus-within:border-primary">
          <Search className="h-5 w-5 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            type="search"
            enterKeyHint="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Imię i nazwisko, e-mail albo numer"
            className="w-0 min-w-0 flex-1 appearance-none border-0 bg-transparent text-base shadow-none outline-none focus:outline-none focus-visible:outline-none focus-visible:ring-0 [&::-webkit-search-cancel-button]:hidden"
          />
          {q ? (
            <button type="button" onClick={() => setQ("")} aria-label="Wyczyść" className="flex h-9 w-9 items-center justify-center">
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </label>
      </header>
      {!enabled ? (
        <div className="space-y-2 px-4 pt-5 text-sm text-muted-foreground">
          <p>Wpisz co najmniej 2 znaki. Szukamy w kandydatach, kontaktach u klientów i rekrutacjach.</p>
          <p>Nieodebrane połączenie? Wklej numer, a NEXUS powie, kto dzwonił.</p>
        </div>
      ) : (
        <>
          <Block title={phone ? "Kto ma ten numer" : "Kandydaci"}>
            <Loaded query={global} height="h-32">
              {(g) =>
                g.candidates.length === 0 ? (
                  <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Nikogo nie znaleziono.</p>
                ) : (
                  <Rows>
                    {g.candidates.map((c) => (
                      <Link key={c.id} href={`${PREVIEW_PATH}/kandydat/${c.id}`} className="flex items-center gap-3 px-3 py-2.5">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">{c.name}</div>
                          <div className="truncate text-xs text-muted-foreground">{c.subtitle}</div>
                        </div>
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                      </Link>
                    ))}
                  </Rows>
                )
              }
            </Loaded>
          </Block>
          {phone || contacts.data === null ? null : (
            <Block title="Kontakty u klientów">
              <Loaded query={contacts} height="h-20">
                {(list) =>
                  !list?.length ? (
                    <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Brak kontaktów u klientów.</p>
                  ) : (
                    <Rows>
                      {list.map((c) => (
                        <div key={c.id} className="flex items-center gap-3 px-3 py-2.5">
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium">{c.name}</div>
                            <div className="truncate text-xs text-muted-foreground">{[c.position, c.client_name].filter(Boolean).join(" · ")}</div>
                            <MailLink email={c.email} />
                          </div>
                          <CallButton phone={c.phone} />
                        </div>
                      ))}
                    </Rows>
                  )
                }
              </Loaded>
            </Block>
          )}
          {global.data?.jobs.length ? (
            <Block title="Rekrutacje">
              <Rows>
                {global.data.jobs.map((j) => (
                  <Link key={j.id} href={`${PREVIEW_PATH}/rekrutacje/${j.id}`} className="block px-3 py-2.5">
                    <div className="truncate text-sm font-medium">{j.name}</div>
                    <div className="truncate text-xs text-muted-foreground">{j.subtitle}</div>
                  </Link>
                ))}
              </Rows>
            </Block>
          ) : null}
        </>
      )}
    </div>
  );
}
