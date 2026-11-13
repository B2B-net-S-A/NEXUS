"use client";

/**
 * Harness panelu konsultanta: prawdziwe ekrany na zasianym cache, ZERO zapytań.
 * Dane wyłącznie fikcyjne. `?ekran=start|na-start|rozliczenia|faktury|rozmowy|sprzet|pomoc|trener|trener-wyslane|
 * szkolenia|szkolenia-nagranie|szkolenie-wycena|szkolenie-poprawa|szkolenie-umowa|szkolenie-przekazanie|szkolenie-faktura`.
 */
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PanelNav } from "@/components/consultant-portal/PanelNav";
import {
  EquipmentScreen,
  HelpScreen,
  InvoicesScreen,
  SettlementScreen,
  StartMaterialsScreen,
  StartScreen,
  TalksScreen,
  TrainerScreen,
} from "@/components/consultant-portal/PanelScreens";
import { PortalShell } from "@/components/consultant-portal/PortalShell";
import { TrainingDetailView } from "@/components/consultant-portal/TrainingDetail";
import { TrainingsScreen, TrainingsView } from "@/components/consultant-portal/TrainingScreens";
import { portalKeys, type PortalMe } from "@/lib/api/consultant-portal";

import { PREVIEW_APPLICATION, PREVIEW_TRAININGS, previewTraining } from "@/components/consultant-portal/training-fixtures";

/** Stały „dziś” harnessu, żeby etapy szkoleń nie zmieniały się z kalendarzem. */
const TODAY = "2026-11-13";

const ME: PortalMe = {
  first_name: "Anna",
  client: "Bank Przykładowy",
  since: "2024-01-15",
  until: null,
  support_email: "wsparcie@example.com",
  topics: [
    { key: "invoice", label: "Faktury i płatności" },
    { key: "access", label: "Sprzęt i dostępy" },
  ],
  rate: { amount: "160.00", currency: "PLN", unit: "hourly" },
  support_phone: "+48 22 000 00 00",
  menu: { start: true, equipment: true },
};

function seeded(): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false, enabled: false } },
  });
  client.setQueryData(portalKeys.todo, {
    items: [
      { key: "invoice", title: "Wyślij fakturę", detail: "Za 10.2026", href: "/konsultant/faktury" },
      { key: "protocol", title: "Potwierdź odbiór sprzętu", detail: "Protokół PZO/2026/11/1", href: "/konsultant/sprzet" },
    ],
  });
  client.setQueryData(portalKeys.meetings, { items: [], note: "Rozmowa jest spisywana." });
  client.setQueryData(portalKeys.start, {
    start_date: "2026-12-01",
    first_day: { place: "Ulica Przykładowa 1, Warszawa", time: "9:00", bring: "Dowód osobisty", contact_name: "Menedżer klienta" },
    documents: [{ name: "Oświadczenie o poufności", note: null, offset_days: -5, required: true }],
    materials: [
      { id: 1, title: "Jak się u nas rozliczasz", kind: "file", url: null, file_name: "rozliczenia.pdf", shared: true },
      { id: 2, title: "Bezpieczeństwo u klienta", kind: "link", url: "https://example.com/szkolenie", file_name: null, shared: false },
    ],
  });
  client.setQueryData(portalKeys.settlement, {
    mode: "client_report",
    instructions: "Fakturę wystaw do 10. dnia miesiąca.",
    buyer: { name: "B2B.net S.A.", nip: "0000000000", address: "Ulica Przykładowa 1, Warszawa" },
    payment_days: 14,
  });
  client.setQueryData(portalKeys.finance, {
    months: [
      {
        year: 2026,
        month: 10,
        report_label: "Raport: przysyła klient",
        invoice_label: "Faktura: czekamy",
        issue_invoice: true,
        action: "send_invoice",
        documents: [],
      },
    ],
  });
  client.setQueryData(portalKeys.equipment, {
    items: [
      {
        id: 1,
        name: "Laptop testowy",
        category: "laptop",
        inventory_number: "0001",
        serial_number: "ABC123",
        since: "2026-03-12",
        protocol_id: 1,
        protocol_number: "PZO/2026/3/1",
        protocol_status: "potwierdzony",
        protocol_label: "Potwierdzony",
      },
    ],
    protocols: [
      {
        id: 2,
        number: "PZO/2026/11/1",
        kind: "wydanie",
        date: "2026-11-03",
        status: "oczekuje",
        label: "Czeka na Twoje potwierdzenie",
        items: ["Słuchawki testowe"],
        can_confirm: true,
      },
    ],
  });
  client.setQueryData(portalKeys.cases, { items: [] });
  client.setQueryData(portalKeys.faq, { items: [] });
  client.setQueryData(portalKeys.trainer, { application: null });
  client.setQueryData(portalKeys.trainings, PREVIEW_TRAININGS);
  // Pusty plik zamiast biletu: odtwarzacz nie wysyła zapytania, a rozdziały działają.
  client.setQueryData(portalKeys.ticket(31), { url: "data:video/mp4;base64," });
  return client;
}

/** Zgłoszenie już wysłane: osobny cache, żeby `?ekran=trener` dalej pokazywał pusty formularz. */
function SentApplication() {
  const client = useMemo(() => {
    const sent = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false, enabled: false } } });
    sent.setQueryData(portalKeys.trainer, { application: PREVIEW_APPLICATION });
    return sent;
  }, []);
  return (
    <QueryClientProvider client={client}>
      <TrainerScreen />
    </QueryClientProvider>
  );
}

function Screen() {
  const ekran = useSearchParams().get("ekran") ?? "start";
  const client = useMemo(seeded, []);
  const screens: Record<string, React.ReactNode> = {
    start: <StartScreen me={ME} />,
    "na-start": <StartMaterialsScreen me={ME} />,
    rozliczenia: <SettlementScreen me={ME} />,
    faktury: <InvoicesScreen />,
    rozmowy: <TalksScreen me={ME} />,
    sprzet: <EquipmentScreen me={ME} />,
    pomoc: <HelpScreen me={ME} />,
    trener: <TrainerScreen />,
    "trener-wyslane": <SentApplication />,
    szkolenia: <TrainingsScreen />,
    "szkolenia-nagranie": (
      <TrainingsView data={PREVIEW_TRAININGS} today={TODAY} initialTab="recordings" initialRecording={21} />
    ),
    "szkolenie-wycena": <TrainingDetailView training={previewTraining(3, "ordered")} today={TODAY} />,
    "szkolenie-poprawa": <TrainingDetailView training={previewTraining(3, "returned")} today={TODAY} />,
    "szkolenie-umowa": <TrainingDetailView training={previewTraining(2, "accepted")} today={TODAY} />,
    "szkolenie-przekazanie": <TrainingDetailView training={previewTraining(1, "signed")} today={TODAY} />,
    "szkolenie-faktura": (
      <TrainingDetailView
        training={previewTraining(1, "signed", {
          handover: previewTraining(1, "signed").handover.map((item) => ({ ...item, state: "accepted" as const })),
          payment: { invoice_ready_at: "2026-11-12T10:00:00+01:00", paid_at: null },
          can_invoice: true,
        })}
        today={TODAY}
      />
    ),
  };
  return (
    <QueryClientProvider client={client}>
      <PortalShell onLogout={() => undefined} nav={<PanelNav me={ME} />}>
        {screens[ekran] ?? screens.start}
      </PortalShell>
    </QueryClientProvider>
  );
}

export default function ConsultantPanelPreview() {
  return (
    <Suspense fallback={null}>
      <Screen />
    </Suspense>
  );
}
