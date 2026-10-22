"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { CLIENT_TAB_LABEL, type SameNameClient } from "@/lib/client-duplicate";

/**
 * Ramka „taki klient już jest” w oknie „Dodaj firmę” (22.10.2026).
 *
 * Ostrzeżenie, nie blokada: ta sama nazwa bywa inną firmą. Zakładka przy
 * nazwie mówi, gdzie szukać istniejącego klienta — duplikat Energi powstał,
 * bo stary rekord leżał w Nieaktywnych, a nowy dodano w Aktywnych.
 */
export function ExistingClientNotice({
  clients,
  saving,
  onOpenProfile,
  onAddAnyway,
}: {
  clients: SameNameClient[];
  saving: boolean;
  onOpenProfile: () => void;
  onAddAnyway: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-warning/30 bg-warning-muted p-3 text-sm text-warning-muted-foreground"
    >
      <p className="font-semibold">
        {clients.length === 1 ? "Taki klient już jest" : "Tacy klienci już są"}
      </p>
      <ul className="mt-1 space-y-1">
        {clients.map((client) => (
          <li key={client.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="break-words">
              {client.name}
              {client.categories.length
                ? ` · zakładka ${client.categories.map((c) => CLIENT_TAB_LABEL[c]).join(", ")}`
                : ""}
            </span>
            <Link
              href={`/clients/${client.id}`}
              onClick={onOpenProfile}
              className="text-xs font-medium underline underline-offset-2"
            >
              Otwórz profil
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-xs">
        Jeśli to ta sama firma, przenieś istniejącego klienta do właściwej zakładki zamiast
        zakładać drugiego.
      </p>
      <div className="mt-2">
        <Button type="button" size="sm" variant="outline" loading={saving} onClick={onAddAnyway}>
          Dodaj mimo to
        </Button>
      </div>
    </div>
  );
}
