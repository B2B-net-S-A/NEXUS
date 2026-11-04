"use client";

/**
 * Harness designu banera reguł CV klienta.
 *
 * Renderuje PRAWDZIWY `ClientCvRuleBanner`, ale nie rusza sieci: cache
 * react-query jest zasiany z góry (`setQueryData` + `staleTime: Infinity`),
 * a komponent i tak dostaje dane propsami. To warunek wejścia do
 * `PUBLIC_PATHS` w middleware.ts — stronę otwiera Playwright bez sesji.
 *
 * Pięć stanów obok siebie, bo ich różnice łatwo zepsuć niezauważenie i każda
 * pomyłka kosztuje inaczej:
 *
 *  * brak klienta — NIC się nie renderuje (nie ma o czym informować);
 *  * ładowanie — krótka informacja, nie pustka;
 *  * brak zatwierdzonych reguł — OSTRZEŻENIE. To jest stan, dla którego ten
 *    baner powstał: niewłączona reguła jest inaczej niewidoczna, bo generacja
 *    „działa", a plik po prostu dostaje nazwę, której klient nie akceptuje;
 *  * reguły obowiązują — co zadziała i jak będzie się nazywał plik;
 *  * awaria odczytu — MUSI wyglądać inaczej niż „brak reguł". Cisza po błędzie
 *    czytałaby się jak fakt, a nie jak nieudane sprawdzenie.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  ClientCvRuleBanner,
  type ClientCvRule,
} from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { makeCvRule } from "@/test/fixtures/cv-rule";

const client = new QueryClient({
  defaultOptions: { queries: { staleTime: Infinity, retry: false } },
});

const POLNOCNY: ClientCvRule = makeCvRule({
  seed_key: "profil-championa-wzor-polnocny-docx",
  confirmed_by_name: "Adam Wzorcowy",
});

const KAPPA: ClientCvRule = makeCvRule({
  client_id: 2,
  client_name: "Bank Kappa",
  filename_pattern: "ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
  cv_language: "pl",
  requires_rodo_consent_block: true,
  notes:
    "Maks. 3 rekomendacje na stanowisko. CV bez zdjęcia. Numer projektu ZOB-xxxx bierzemy z zamówienia.",
  generator_instructions:
    "Bez sekcji zainteresowań. Maks. 3 projekty na stanowisko. Opisy obowiązków do 2 zdań.",
  content_mode: "polished",
  content_mode_locked: true,
  seed_key: "profil-championa-wzor-kappa-docx",
  confirmed_by_name: "Adam Wzorcowy",
  client_policy:
    "nazwa pliku, język PL, blok zgody RODO, tryb „Redakcja”, instrukcje dla generatora, notatka DL",
  filename_preview: "ZOB-4521_Analityk Biznesowy_Jan Kowalski.docx",
});

const LAMBDA_PROPOSED: ClientCvRule = makeCvRule({
  client_id: 3,
  client_name: "Bank Lambda S.A.",
  cv_language: null,
  requires_en_copy: true,
  confirmed_at: null,
  confirmed_by_name: null,
  is_active: false,
  client_policy: "",
  filename_preview: null,
  seed_key: "profil-championa-wzor-lambda-docx",
});

function Case({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2 rounded-lg border p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="text-xs text-muted-foreground">{note}</p>
      <div className="max-w-xl">{children}</div>
    </section>
  );
}

export default function CvGeneratorClientRulesPreview() {
  return (
    <QueryClientProvider client={client}>
      <div className="mx-auto max-w-3xl space-y-4 p-8">
        <h1 className="text-xl font-semibold">
          Baner reguł CV klienta — stany
        </h1>

        <Case
          title="Klient niewybrany"
          note="Nic się nie renderuje — nie ma o czym informować."
        >
          <ClientCvRuleBanner
            clientId={null}
            rule={undefined}
            isLoading={false}
            isError={false}
          />
        </Case>

        <Case title="Sprawdzanie" note="Krótki komunikat zamiast pustki.">
          <ClientCvRuleBanner
            clientId={1}
            rule={undefined}
            isLoading
            isError={false}
          />
        </Case>

        <Case
          title="Reguły niezatwierdzone (BANK LAMBDA)"
          note="Najważniejszy stan: reguła istnieje, ale NIE obowiązuje. Bez tego ostrzeżenia plik po cichu dostaje nazwę ogólną."
        >
          <ClientCvRuleBanner
            clientId={3}
            rule={LAMBDA_PROPOSED}
            isLoading={false}
            isError={false}
          />
        </Case>

        <Case
          title="Reguły obowiązują — wymuszony EN (Bank Północny)"
          note="Jedyny klient wymagający wyłącznie angielskiego."
        >
          <ClientCvRuleBanner
            clientId={1}
            rule={POLNOCNY}
            isLoading={false}
            isError={false}
          />
        </Case>

        <Case
          title="Reguły obowiązują — projekt w nazwie + zgoda RODO (Bank Kappa)"
          note="Jedyny klient, którego standard zmienia ZAWARTOŚĆ dokumentu."
        >
          <ClientCvRuleBanner
            clientId={2}
            rule={KAPPA}
            isLoading={false}
            isError={false}
          />
        </Case>

        <Case
          title="Awaria odczytu"
          note="Musi wyglądać inaczej niż „brak reguł” — inaczej błąd czyta się jak fakt."
        >
          <ClientCvRuleBanner
            clientId={1}
            rule={undefined}
            isLoading={false}
            isError
          />
        </Case>
      </div>
    </QueryClientProvider>
  );
}
