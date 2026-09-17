"use client";

/**
 * Harness wiersza „E-mail / Telefon" z karty „Informacje o kontrakcie".
 *
 * Renderuje PRAWDZIWY `ContractCandidateContactRow` i nie rusza sieci — zapis
 * jest podmieniony na lokalny stan, więc strona może stać w `PUBLIC_PATHS`
 * i chodzić po niej nightly Playwright bez sesji.
 *
 * Cztery stany obok siebie, bo ich różnice łatwo zepsuć niezauważenie:
 * wartość wpisana na umowie (bez odznaki), wartość z profilu kandydata
 * (z odznaką „z profilu"), BRAK w obu źródłach — który musi renderować „—",
 * a nie pustą komórkę — i widok bez uprawnień, w którym wartości zostają,
 * a znika wyłącznie ołówek.
 */

import { useState } from "react";

import { ContractCandidateContactRow } from "@/components/contracts/ContractCandidateContactRow";

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
    <section className="rounded-2xl bg-card p-6 shadow-xs">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">{note}</p>
      <div className="rounded-xl border border-border p-3">{children}</div>
    </section>
  );
}

export default function ContractCandidateContactPreview() {
  // Stan lokalny zamiast PATCH-a: harness pokazuje zachowanie edycji
  // (w tym „wyczyść → wraca wartość z profilu") bez sesji i bez API.
  const [email, setEmail] = useState<string | null>(null);
  const [phone, setPhone] = useState<string | null>(null);
  const profileEmail = "anna.nowak@example.com";
  const profilePhone = "+48 600 100 200";

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header>
        <h1 className="text-lg font-semibold text-foreground">
          Kontakt do konsultanta na karcie kontraktu
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Kolejność źródeł: umowa z generatora → profil kandydata → puste.
        </p>
      </header>

      <Case
        title="Interaktywnie — nadpisanie kontra profil"
        note="Wpisz wartość: odznaka „z profilu” znika. Wyczyść pole: wraca wartość z profilu. Tak zachowuje się prawdziwy ekran po odpowiedzi serwera."
      >
        <ContractCandidateContactRow
          email={email ?? profileEmail}
          emailSource={email ? "contract" : "candidate_profile"}
          phone={phone ?? profilePhone}
          phoneSource={phone ? "contract" : "candidate_profile"}
          editable
          onSaveEmail={async (raw) => setEmail(raw || null)}
          onSavePhone={async (raw) => setPhone(raw || null)}
          onError={() => undefined}
        />
      </Case>

      <Case
        title="Dane z generatora umowy"
        note="Wartość zapisana na umowie — bez odznaki, bo to nie jest fallback."
      >
        <ContractCandidateContactRow
          email="anna.nowak@partner.example.com"
          emailSource="contract"
          phone="+48 601 202 303"
          phoneSource="contract"
          editable
          onSaveEmail={async () => undefined}
          onSavePhone={async () => undefined}
          onError={() => undefined}
        />
      </Case>

      <Case
        title="Brak w obu źródłach"
        note="„—”, nigdy pusta komórka: puste miejsce obok wypełnionych pól czyta się jak utrata danych."
      >
        <ContractCandidateContactRow
          email={null}
          emailSource={null}
          phone={null}
          phoneSource={null}
          editable
          onSaveEmail={async () => undefined}
          onSavePhone={async () => undefined}
          onError={() => undefined}
        />
      </Case>

      <Case
        title="Bez uprawnień do edycji"
        note="Wartości widoczne, ołówka nie ma — rola spoza admin/Delivery Lead."
      >
        <ContractCandidateContactRow
          email={profileEmail}
          emailSource="candidate_profile"
          phone={profilePhone}
          phoneSource="candidate_profile"
          editable={false}
          onSaveEmail={async () => undefined}
          onSavePhone={async () => undefined}
          onError={() => undefined}
        />
      </Case>
    </main>
  );
}
