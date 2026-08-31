"use client";

/**
 * Harness wizualny treści procedury w module Pomoc.
 *
 * Renderuje PRODUKCYJNY `ProcedureContent` (nie kopię) z zahardkodowanym
 * dokumentem — strona nie robi ani jednego zapytania do API, więc może stać
 * w `PUBLIC_PATHS`. Ten sam wzorzec co `/preview/order-lifecycle`.
 *
 * Powstał dla instrukcji obsługi zamówień, która ma sekcję dla każdego klienta:
 * bez spisu treści czytelnik przewija kilkanaście ekranów i w praktyce czyta nie
 * tę sekcję, co trzeba. Harness pokazuje OBA stany obok siebie — dokument długi
 * (spis treści jest) i krótki (spisu nie ma) — bo próg jest tym miejscem, które
 * przy zmianie stylów najłatwiej zepsuć niezauważenie.
 */

import { ProcedureContent } from "@/components/v2/pages/HelpPageV2";
import type { Procedure } from "@/lib/api/procedures";

function procedure(overrides: Partial<Procedure> = {}): Procedure {
  return {
    id: 1,
    slug: "zamowienia-instrukcja-delivery-lead",
    title: "Zamówienia — instrukcja dla Delivery Leada",
    content: "",
    sort_order: 100,
    is_published: true,
    created_by: null,
    updated_by: null,
    created_at: "2026-08-31T09:00:00Z",
    updated_at: "2026-08-31T09:00:00Z",
    ...overrides,
  };
}

const LONG = `> **Zgodność z systemem sprawdzona:** 2026-08-31

Instrukcja opisuje, jak dziś naprawdę działa moduł Zamówienia.

## Gdzie są zamówienia

**Klienci → nazwa klienta → zakładka „Zamówienia"**. Lista jest jedna, podzielona
na sekcje: **MD**, **Kosztowe**, **Okresowe**.

## Trzy typy zamówienia

| Typ | Kiedy go używasz | Jak się rozlicza |
|---|---|---|
| **Okresowe** | jedna osoba = jedno zamówienie | datami |
| **MD** | jeden numer, kilku konsultantów | budżetem dni |
| **Kosztowe** | jeden numer, jedna kwota | kwotą w złotych |

## Klienci — czym różni się każdy

### Bank Pocztowy

* Numer zamówienia wyłącznie z pola **„Numer pisma"**.
* Stawka jest dzielona przez 8 i zapisywana jako godzinowa.

### Credit Agricole

* Stawka wyłącznie spod napisu **„Wynagrodzenie za 1MD"**.
* Nic nie jest przeliczane.

### Erste Bank Polska

* Kwota w dokumencie jest brutto — system dzieli ją przez **1,23**.

## Najczęstsze pułapki

1. **„Zamówienie utknęło w Draft."** Brakuje numeru, daty startu albo stawki.
2. **„Odczyt zostawił puste stawki."** System nie zgadywał — wpisz ręcznie.
`;

const SHORT = `Krótka procedura bez podziału na sekcje.

## Jedyny nagłówek

Poniżej progu trzech nagłówków spis treści się nie renderuje — przy dwóch
sekcjach zabierałby więcej miejsca, niż oszczędza przewijania.
`;

export default function ProcedureHelpPreview() {
  return (
    <main className="mx-auto max-w-5xl space-y-8 p-6">
      <header>
        <h1 className="text-xl font-semibold text-foreground">
          Harness: treść procedury (Pomoc → Procedury)
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Mocki, zero zapytań do API.
        </p>
      </header>

      <section className="rounded-lg border border-border bg-card">
        <ProcedureContent
          procedure={procedure({ content: LONG })}
          isAdmin={false}
          onEdit={() => {}}
          onDelete={() => {}}
        />
      </section>

      <section className="rounded-lg border border-border bg-card">
        <ProcedureContent
          procedure={procedure({
            id: 2,
            title: "Krótka procedura (bez spisu treści)",
            content: SHORT,
          })}
          isAdmin
          onEdit={() => {}}
          onDelete={() => {}}
        />
      </section>
    </main>
  );
}
