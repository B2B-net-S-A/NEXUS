"use client";

import { HelpCircle } from "lucide-react";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";

/**
 * Instrukcja „Jak NEXUS pilnuje duplikatów” (zgłoszenie dzwoniących, decyzje Artura
 * 23.11.2026). Opis zgodny z `dzwonienie-powtorki-i-firmy-w-crm.md`: zmiana bramek
 * w imporcie albo kolejce zmienia też ten tekst.
 */
const RULES: { title: string; body: string }[] = [
  {
    title: "Przy imporcie listy",
    body: "Każdy wiersz przechodzi przez bramki, pierwsza pasująca decyduje: sprzeciw („Nie kontaktować”), klient NEXUSA, powtórka w tym samym pliku, „Już dzwoniono” (ten sam numer, adres e-mail albo osoba z wynikiem w dowolnej kampanii, u każdej osoby), „Już w kampanii” (ten sam NIP albo numer czeka już na liście), „Dzwoni ktoś inny” i brak telefonu. Takie wiersze nie trafiają na listę. Podgląd pokazuje każdy z powodem, a „Pobierz plik z oznaczeniami” daje plik z kolumną „W NEXUSIE”.",
  },
  {
    title: "W kolejce",
    body: "Kolejka pomija „Nowy” rekord pod numerem, adresem albo osobą, która ma już wynik w innym rekordzie, i rekord firmy, która ma otwartą szansę założoną po nim (wtedy dzwonisz przez szansę). „Zły numer” blokuje sam numer, nie osobę.",
  },
  {
    title: "W Tabeli",
    body: "Te same powtórki Tabela ukrywa. „Powtórki” pokazuje je z plakietką: to głównie rekordy z list sprzed 17.11, kiedy tej bramki jeszcze nie było.",
  },
  {
    title: "Na karcie rozmowy",
    body: "Nad numerem stoi „Pod ten numer już dzwoniono” (kiedy, kto, z jakim wynikiem) i „Ta firma jest już w CRM” z przyciskiem „Otwórz szansę”.",
  },
  {
    title: "Co przechodzi celowo",
    body: "Nowa osoba w firmie, w której już dzwoniono: dostaje dopisek „W tej firmie dzwoniono już”, bo nowy decydent bywa jedyną drogą. Ta sama firma na dwóch kartach o różnych nazwach (spółka i grupa) z różnymi numerami: tego bramka nie widzi.",
  },
];

export function DuplicatesHelp() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setOpen(true)}>
        <HelpCircle className="mr-1 h-3.5 w-3.5" aria-hidden /> Jak działają duplikaty?
      </Button>
      {open && (
        <AppModal
          open
          onOpenChange={setOpen}
          title="Jak NEXUS pilnuje duplikatów"
          description="Ta sama osoba albo numer nie powinny trafić do kolejki drugi raz. Tak to działa dziś."
          size="lg"
        >
          <ol className="space-y-3 text-sm">
            {RULES.map((rule, index) => (
              <li key={rule.title} className="flex gap-3">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                  {index + 1}
                </span>
                <div>
                  <p className="font-medium text-foreground">{rule.title}</p>
                  <p className="text-muted-foreground">{rule.body}</p>
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-4 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-foreground">
            Widzisz duplikat, którego bramka nie złapała? Kliknij „To duplikat” na karcie rozmowy: zbieramy takie
            przykłady i poprawiamy bramki.
          </p>
        </AppModal>
      )}
    </>
  );
}
