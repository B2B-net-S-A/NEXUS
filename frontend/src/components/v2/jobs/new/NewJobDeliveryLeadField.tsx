"use client";

/**
 * `/jobs/new` → pole „Delivery Lead” w sekcji „Kategoria i zespół” (08.10.2026).
 *
 * Pokazuje, kto zostanie Delivery Leadem, zanim rekrutacja powstanie: osoba
 * z rolą Delivery Leada jest DL-em rekrutacji, którą zakłada, inaczej główny
 * DL klienta. Regułę liczy serwer (`GET /api/job-intake/delivery-lead` — ta
 * sama co przy zapisie); tu można ją tylko zmienić. Do tej daty formularz
 * nie mówił, kto będzie DL-em, i pomyłkę było widać dopiero po utworzeniu.
 *
 * `value === null` znaczy „osoba domyślna” — wtedy `POST /api/jobs` nie niesie
 * `delivery_lead_id` i serwer wpisuje ją sam.
 */

import { useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

/** `GET /api/job-intake/delivery-lead` → `default`. */
export interface DefaultDeliveryLead {
  user_id: number;
  name: string | null;
  /** `creator` = osoba zakładająca rekrutację, `client_head` = główny DL klienta. */
  source: "creator" | "client_head";
}

interface DirectoryUser {
  id: number;
  name?: string | null;
  email?: string | null;
}

const ROLE_TEXT =
  "Do tej osoby trafia przegląd CV przed wysyłką do klienta i alerty rekrutacji.";

/** Zdanie pod polem — mówi, skąd wzięła się osoba. */
export function deliveryLeadHint(
  defaultLead: DefaultDeliveryLead | null,
  chosenId: number | null,
): string {
  if (chosenId != null && chosenId !== defaultLead?.user_id) {
    return defaultLead
      ? `Wybrano ręcznie. Bez zmiany byłby to: ${defaultLead.name ?? `#${defaultLead.user_id}`}.`
      : "Wybrano ręcznie.";
  }
  if (defaultLead == null) {
    return "Klient nie ma głównego Delivery Leada. Wskaż osobę albo zostaw puste — przegląd CV trafi wtedy do Delivery Leadów przypisanych do klienta.";
  }
  return defaultLead.source === "creator"
    ? `Zakładasz tę rekrutację, więc jesteś jej Delivery Leadem. ${ROLE_TEXT}`
    : `Główny Delivery Lead klienta. ${ROLE_TEXT}`;
}

const personLabel = (u: DirectoryUser) => u.name || u.email || `#${u.id}`;

interface Props {
  clientId: number | null;
  /** Wybór ręczny; `null` = osoba domyślna. */
  value: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
}

export function NewJobDeliveryLeadField({ clientId, value, onChange, disabled = false }: Props) {
  const id = useId();
  const [editing, setEditing] = useState(false);

  const defaultQuery = useQuery({
    queryKey: ["job-intake-delivery-lead", clientId],
    enabled: clientId != null,
    retry: false,
    queryFn: () =>
      api
        .get("/api/job-intake/delivery-lead", { params: { client_id: clientId } })
        .then((r) => (r.data as { default?: DefaultDeliveryLead | null }).default ?? null),
  });
  const defaultLead = defaultQuery.data ?? null;

  // Ten sam katalog i klucz co pole „Delivery Lead” w panelu „Zespół”.
  // Wczytuje się dopiero, gdy ktoś chce zmienić osobę.
  const directoryQuery = useQuery({
    queryKey: ["users-directory", "delivery-lead-roles"],
    enabled: editing || value != null,
    staleTime: 5 * 60_000,
    queryFn: () =>
      api
        .get("/api/users", {
          params: { roles: ["delivery_lead", "admin", "head_of_recruitment"] },
          // FastAPI wiąże powtórzone `roles=`; axios domyślnie wysyła `roles[]=`.
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data as DirectoryUser[]),
  });
  const directory = directoryQuery.data ?? [];
  // Osoba domyślna stoi na liście także wtedy, gdy katalog się nie wczytał.
  const options =
    defaultLead && !directory.some((u) => u.id === defaultLead.user_id)
      ? [{ id: defaultLead.user_id, name: defaultLead.name }, ...directory]
      : directory;

  const shownId = value ?? defaultLead?.user_id ?? null;
  const shownPerson = options.find((u) => u.id === shownId);
  const shownName =
    shownId == null
      ? "nie przypisano"
      : shownPerson
        ? personLabel(shownPerson)
        : `Użytkownik #${shownId}`;
  const isMe = value == null && defaultLead?.source === "creator";

  let body: ReactNode;
  if (clientId == null && value == null) {
    body = (
      <p className="text-sm text-muted-foreground">
        Wybierz klienta — wtedy pokażemy, kto będzie Delivery Leadem.
      </p>
    );
  } else if (defaultQuery.isLoading) {
    body = (
      <p className="text-sm text-muted-foreground">Sprawdzam, kto będzie Delivery Leadem…</p>
    );
  } else {
    body = (
      <>
        {editing ? (
          <select
            id={`${id}-select`}
            aria-labelledby={`${id}-label`}
            className="h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm text-foreground sm:max-w-sm"
            value={shownId ?? ""}
            disabled={disabled}
            onChange={(e) => {
              const picked = e.target.value ? Number(e.target.value) : null;
              // Powrót do osoby domyślnej to brak wyboru — serwer wpisze ją sam.
              onChange(picked === defaultLead?.user_id ? null : picked);
            }}
          >
            {defaultLead == null ? (
              <option value="">
                {defaultQuery.isError ? "— domyślny —" : "— bez Delivery Leada —"}
              </option>
            ) : null}
            {options.map((u) => (
              <option key={u.id} value={u.id}>
                {personLabel(u)}
              </option>
            ))}
          </select>
        ) : (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-foreground">
            <span className="font-medium" data-testid="new-job-delivery-lead-name">
              {defaultQuery.isError && value == null ? "domyślny" : shownName}
              {isMe ? " (Ty)" : ""}
            </span>
            <button
              type="button"
              className="text-xs font-medium text-primary underline-offset-2 hover:underline disabled:opacity-60"
              disabled={disabled}
              onClick={() => setEditing(true)}
            >
              Zmień
            </button>
          </p>
        )}
        {editing && directoryQuery.isError ? (
          <span role="alert" className="text-xs text-destructive">
            Nie udało się wczytać listy osób.{" "}
            <button
              type="button"
              className="font-medium underline"
              onClick={() => void directoryQuery.refetch()}
            >
              Ponów
            </button>
          </span>
        ) : null}
        {defaultQuery.isError ? (
          <span role="alert" className="text-xs text-destructive">
            Nie udało się sprawdzić, kto będzie Delivery Leadem.{" "}
            <button
              type="button"
              className="font-medium underline"
              onClick={() => void defaultQuery.refetch()}
            >
              Ponów
            </button>
          </span>
        ) : (
          <p className="text-xs leading-snug text-muted-foreground">
            {deliveryLeadHint(defaultLead, value)}
          </p>
        )}
      </>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid="new-job-delivery-lead">
      <span id={`${id}-label`} className="text-sm font-medium text-foreground">
        Delivery Lead
      </span>
      {body}
    </div>
  );
}
