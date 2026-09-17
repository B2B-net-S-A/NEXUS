"use client";

// Kontakt do konsultanta na karcie „Informacje o kontrakcie" — jeden wiersz
// pod „Typ kontraktu" (ticket „E-mail i telefon kandydata w widoku kontraktu").
//
// Wyniesione ze strony szczegółów kontraktu (2300+ linii), żeby dało się to
// przetestować bez montowania całego ekranu: reguła „skąd wartość i co znaczy
// jej brak" jest tu jedyną treścią.
//
// Trzy rzeczy, które łatwo cofnąć przy refaktorze:
//
//  * **Brak wartości renderuje „—", nigdy pustą komórkę.** Puste miejsce obok
//    wypełnionych pól czyta się jak utrata danych, nie jak „nie mamy".
//  * **Wartość z profilu jest OZNACZONA.** Bez tego wyczyszczenie pola wygląda
//    na niezapisaną zmianę („skasowałem, a dalej coś jest").
//  * **Edytor startuje od wartości WIDOCZNEJ**, także gdy pochodzi z profilu —
//    prefiks „+48 600…" jest zwykle poprawny i chodzi o poprawienie cyfry,
//    a nie o przepisanie numeru od zera. `InlineText` nie zapisuje, gdy nic się
//    nie zmieniło, więc samo wejście w edycję nie zakłada nadpisania.

import { Mail, Phone } from "lucide-react";

import { InlineText } from "@/components/orders/InlineOrderFields";

export type ContactSource = "contract" | "candidate_profile" | null;

export interface ContractCandidateContactRowProps {
  email: string | null;
  emailSource: ContactSource;
  phone: string | null;
  phoneSource: ContactSource;
  /** Czy zalogowany może edytować kontrakt (mirror `contract.update`). */
  editable: boolean;
  onSaveEmail: (raw: string) => Promise<void>;
  onSavePhone: (raw: string) => Promise<void>;
  onError: (message: string) => void;
}

const FROM_PROFILE_TITLE =
  "Wartość z profilu kandydata — na umowie nie ma własnej. Wpisanie tu czegoś " +
  "nadpisze ją tylko dla tego kontraktu; wyczyszczenie przywróci profil.";

function FromProfileBadge() {
  return (
    <span
      title={FROM_PROFILE_TITLE}
      className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
    >
      z profilu
    </span>
  );
}

function ContactField({
  icon: Icon,
  label,
  value,
  source,
  editable,
  onSave,
  onError,
  placeholder,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | null;
  source: ContactSource;
  editable: boolean;
  onSave: (raw: string) => Promise<void>;
  onError: (message: string) => void;
  placeholder: string;
}) {
  const display = value ? (
    // `min-w-0` na obu poziomach jest load-bearing: bez niego długi adres
    // e-mail nie daje się przyciąć i ZAWIJA się pod ikonę, przepychając ołówek
    // poza pierwszą linię — wygląda to jak usterka układu, a nie jak decyzja.
    <span className="block min-w-0 truncate" title={value}>
      {value}
    </span>
  ) : (
    <span className="text-muted-foreground">—</span>
  );

  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="flex min-w-0 items-center gap-1.5 text-sm text-foreground">
        <Icon className="w-3.5 h-3.5 shrink-0 text-muted-foreground" aria-hidden />
        {/* Ograniczenie szerokości MUSI siedzieć na własnym opakowaniu, a nie
            na całym wierszu: korzeń `InlineText` to `inline-flex`, więc bez
            `min-w-0`/`max-w-full` długi adres rozpycha kolumnę i zawija się
            pod ikonę. Wariant `[&>span]` celuje wyłącznie w ten korzeń —
            nałożony na cały wiersz trafiłby też w odznakę „z profilu" (to
            również `<span>`) i ściskał wartość do kilku znaków. */}
        <div className="min-w-0 flex-1 [&>span]:flex [&>span]:min-w-0 [&>span]:max-w-full">
          <InlineText
            value={value ?? ""}
            display={display}
            ariaLabel={label}
            placeholder={placeholder}
            editable={editable}
            onSave={onSave}
            onError={onError}
          />
        </div>
      </div>
      {/* Odznaka w OSOBNEJ linii, nie obok wartości: kolumna ma tu ~170 px,
          więc odznaka obok zjadała tyle miejsca, że przycinany był nawet numer
          telefonu — a ucięty numer wygląda na kompletny i nie da się go
          odróżnić od błędnego. */}
      {source === "candidate_profile" ? (
        <div className="mt-0.5 pl-5">
          <FromProfileBadge />
        </div>
      ) : null}
    </div>
  );
}

export function ContractCandidateContactRow({
  email,
  emailSource,
  phone,
  phoneSource,
  editable,
  onSaveEmail,
  onSavePhone,
  onError,
}: ContractCandidateContactRowProps) {
  return (
    // Jeden wiersz, dwie kolumny — na wąskim ekranie (~400 px) stackują się,
    // żeby karta nie wymuszała poziomego przewijania.
    <div className="grid grid-cols-1 gap-x-6 gap-y-2 py-2 pl-7 sm:grid-cols-2">
      <ContactField
        icon={Mail}
        label="E-mail"
        value={email}
        source={emailSource}
        editable={editable}
        onSave={onSaveEmail}
        onError={onError}
        placeholder="jan.kowalski@example.com"
      />
      <ContactField
        icon={Phone}
        label="Telefon"
        value={phone}
        source={phoneSource}
        editable={editable}
        onSave={onSavePhone}
        onError={onError}
        placeholder="+48 600 100 200"
      />
    </div>
  );
}
