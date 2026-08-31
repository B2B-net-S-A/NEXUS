"use client";

/**
 * Wybór klienta dla radaru — bez opcji „wszyscy klienci" i bez możliwości
 * odznaczenia.
 *
 * Brak klienta znaczy tu „nie wolno szukać": filtr dopuszczalności sprawdza
 * względem niego blacklistę, NDA, konflikty konkurencyjne i weto hiring
 * managera, a backend odrzuca żądanie bez `client_id`. Zaproszenie do wyboru,
 * który z definicji nie może zadziałać, jest gorsze niż brak podpowiedzi.
 *
 * Trzon mieszka w `ClientSinglePicker` (dzielony z generatorem CV); tutaj
 * zostaje wyłącznie zawężenie kontraktu: `onChange` NIE przyjmuje `null`.
 */

import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";

export type { ClientRef };

interface Props {
  value: ClientRef | null;
  onChange: (client: ClientRef) => void;
}

export function TalentRadarClientPicker({ value, onChange }: Props) {
  return (
    <ClientSinglePicker
      value={value}
      queryKey="clients-lookup-talent-radar"
      onChange={(client) => {
        // `allowClear` jest wyłączone, więc `null` nie ma jak tu trafić —
        // strażnik pilnuje, żeby przyszła zmiana w trzonie nie przemyciła
        // stanu „bez klienta" do radaru po cichu.
        if (client) onChange(client);
      }}
    />
  );
}
