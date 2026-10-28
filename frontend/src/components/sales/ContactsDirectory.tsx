"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Users } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useSalesContacts, type SalesContact } from "@/lib/api/sales";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { hasPermission } from "@/lib/permissions";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { ContactEditDialog } from "./ContactEditDialog";

const PAGE = 50;

/**
 * Sprzedaż → Kontakty: osoby ze wszystkich firm (w Atlasie osobna kartoteka;
 * po imporcie API było, ekranu nie). Szukanie po nazwisku, stanowisku, mailu,
 * telefonie i firmie; edycja i archiwum z jednego okna.
 */
export function ContactsDirectory() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const executives = searchParams?.get("decydenci") === "1";
  const archived = searchParams?.get("archiwum") === "1";
  const offset = Math.max(0, Number(searchParams?.get("od") ?? 0) || 0);
  const [editing, setEditing] = useState<SalesContact | null>(null);
  const contacts = useSalesContacts(null, q, true, { executives, archived, limit: PAGE, offset });
  const items = contacts.data?.items ?? [];
  const total = contacts.data?.total ?? 0;
  const state = resolveViewState({
    isLoading: contacts.isLoading,
    error: contacts.error,
    isSuccess: contacts.isSuccess,
    isEmpty: items.length === 0,
  });

  const writeParams = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(patch)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: (value) => {
            setQ(value);
            writeParams({ q: value.trim() || null, od: null });
          },
          placeholder: "Szukaj po nazwisku, stanowisku, mailu, telefonie albo firmie…",
          ariaLabel: "Szukaj kontaktu",
        }}
        filters={
          <>
            <Button
              size="sm"
              variant={executives ? "primary" : "outline"}
              aria-pressed={executives}
              onClick={() => writeParams({ decydenci: executives ? null : "1", od: null })}
            >
              Tylko decydenci
            </Button>
            <Button
              size="sm"
              variant={archived ? "primary" : "outline"}
              aria-pressed={archived}
              onClick={() => writeParams({ archiwum: archived ? null : "1", od: null })}
            >
              Archiwum
            </Button>
          </>
        }
        resultCount={contacts.isSuccess ? total : undefined}
      />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie kontaktów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void contacts.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={Users}
          title="Nic nie pasuje do wyszukiwania"
          description="Zmień wyszukiwanie albo filtry. Kontakty dodajesz w karcie firmy."
        />
      ) : (
        <>
          <div className="relative overflow-x-auto">
            <Table className="min-w-[760px]">
              <TableHeader>
                <TableRow>
                  <TableHead className={CALM_HEAD}>Osoba</TableHead>
                  <TableHead className={CALM_HEAD}>Firma</TableHead>
                  <TableHead className={CALM_HEAD}>Kontakt</TableHead>
                  <TableHead className={CALM_HEAD} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((contact) => {
                  const others = contact.companies.filter((link) => !link.is_primary);
                  return (
                    <TableRow key={contact.id} className={CALM_ROW}>
                      <TableCell>
                        <span className="font-medium text-foreground">{contact.full_name}</span>
                        {contact.is_executive && (
                          <Badge variant="soft" size="sm" className="ml-1.5">
                            decydent
                          </Badge>
                        )}
                        <p className={CALM_SUBLINE}>{contact.title ?? "—"}</p>
                      </TableCell>
                      <TableCell>
                        {contact.company_id ? (
                          <Link href={`/sales/companies/${contact.company_id}`} className="hover:underline">
                            {contact.company_name}
                          </Link>
                        ) : (
                          "—"
                        )}
                        {others.length > 0 && (
                          <p className={CALM_SUBLINE}>
                            także: {others.map((other) => other.company_name).join(", ")}
                          </p>
                        )}
                      </TableCell>
                      <TableCell className="text-sm">
                        {contact.email ?? "—"}
                        <p className={CALM_SUBLINE}>{contact.phone ?? contact.mobile_phone ?? ""}</p>
                      </TableCell>
                      <TableCell className="text-right">
                        {canEdit && (
                          <Button size="sm" variant="ghost" onClick={() => setEditing(contact)}>
                            Edytuj
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          {total > PAGE && (
            <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, total)} z {total}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={offset === 0}
                onClick={() => writeParams({ od: offset - PAGE > 0 ? String(offset - PAGE) : null })}
              >
                Poprzednie
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={offset + PAGE >= total}
                onClick={() => writeParams({ od: String(offset + PAGE) })}
              >
                Następne
              </Button>
            </div>
          )}
        </>
      )}
      {editing && (
        <ContactEditDialog
          contact={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
