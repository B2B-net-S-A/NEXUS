"use client";

import Link from "next/link";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useSalesContacts, type SalesContact } from "@/lib/api/sales";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

/** MAKIETA: Sprzedaż → Kontakty — kartoteka osób z wszystkich firm, edycja. API już jest. */
export function ContactsDirectory() {
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<SalesContact | null>(null);
  const contacts = useSalesContacts(null, q);
  const items = contacts.data?.items ?? [];
  const state = resolveViewState({
    isLoading: contacts.isLoading,
    error: contacts.error,
    isSuccess: contacts.isSuccess,
    isEmpty: items.length === 0,
  });

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: setQ,
          placeholder: "Szukaj po nazwisku, stanowisku, mailu, telefonie albo firmie…",
          ariaLabel: "Szukaj kontaktu",
        }}
        filters={
          <>
            <Button size="sm" variant="outline">Tylko decydenci</Button>
            <Button size="sm" variant="outline">Archiwum</Button>
          </>
        }
        resultCount={contacts.isSuccess ? contacts.data.total : undefined}
      />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie kontaktów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void contacts.refetch()} />
      ) : state === "empty" ? (
        <p className="py-6 text-sm text-muted-foreground">Nic nie pasuje do wyszukiwania.</p>
      ) : (
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
              {items.slice(0, 50).map((contact) => (
                <TableRow key={contact.id} className={CALM_ROW}>
                  <TableCell>
                    <span className="font-medium text-foreground">{contact.full_name}</span>
                    {contact.is_executive && (
                      <Badge variant="soft" size="sm" className="ml-1.5">decydent</Badge>
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
                  </TableCell>
                  <TableCell className="text-sm">
                    {contact.email ?? "—"}
                    <p className={CALM_SUBLINE}>{contact.phone ?? contact.mobile_phone ?? ""}</p>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(contact)}>
                      Edytuj
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {editing && (
        <AppModal
          open
          onOpenChange={(open) => !open && setEditing(null)}
          title="Edytuj kontakt"
          size="md"
          footer={
            <>
              <Button variant="outline" onClick={() => setEditing(null)}>Anuluj</Button>
              <Button onClick={() => setEditing(null)}>Zapisz</Button>
            </>
          }
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["Imię i nazwisko", editing.full_name],
                ["Stanowisko", editing.title],
                ["E-mail", editing.email],
                ["Telefon", editing.phone ?? editing.mobile_phone],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="space-y-1">
                <Label>{label}</Label>
                <Input defaultValue={value ?? ""} />
              </div>
            ))}
            <div className="space-y-1 sm:col-span-2">
              <Label>Firma</Label>
              <Input defaultValue={editing.company_name ?? ""} />
            </div>
          </div>
          <Button size="sm" variant="quiet" className="mt-2 px-0">
            Archiwizuj kontakt (np. odszedł z firmy)
          </Button>
        </AppModal>
      )}
    </div>
  );
}
