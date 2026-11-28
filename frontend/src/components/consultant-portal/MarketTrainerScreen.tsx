"use client";

import { portalApi, portalKeys, usePortalQuery } from "@/lib/api/consultant-portal";

import { Failure, Fact, Loading, Panel, ScreenTitle, TRAINER_FLOW } from "./PanelScreens";

/**
 * „Dane do umowy” trenera z rynku (0807). Dane firmy wpisuje TCM przy otwarciu panelu
 * (decyzja Artura 28.11.2026), więc tu są tylko do odczytu, jak dane do przelewu
 * konsultanta. Trener rozlicza się fakturą, umowa szkoleniowa jest ta sama.
 */
export function MarketTrainerScreen() {
  const query = usePortalQuery(portalKeys.trainerCompany, portalApi.trainerCompany);
  if (query.isLoading) return <Loading />;
  if (query.isError) return <Failure error={query.error} text="Nie udało się wczytać danych. Odśwież stronę." />;
  if (!query.isSuccess) return null;
  const { company, application } = query.data;
  return (
    <div className="min-w-0 space-y-4">
      <ScreenTitle
        title="Dane do umowy"
        lead="Z tymi danymi przygotujemy umowę szkoleniową. Szkolenia rozliczasz fakturą."
      />
      <Panel title="Twoja firma">
        <dl className="space-y-2.5">
          <Fact label="Firma" value={company.company_name || "nie podano"} />
          <Fact label="NIP" value={company.nip ?? "nie podano"} />
          {company.regon ? <Fact label="REGON" value={company.regon} /> : null}
          <Fact label="Adres" value={company.company_address || "nie podano"} />
          <Fact label="Adres do kontaktu" value={company.email ?? "nie podano"} />
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">
          Coś się nie zgadza? Napisz do osoby z B2B.net, która prowadzi Twoje szkolenia. Tych danych
          nie zmienisz w panelu.
        </p>
      </Panel>
      <Panel title="Twoje zgłoszenie">
        <dl className="space-y-2.5">
          <Fact label="Tematy" value={application.topics.join(", ") || "nie podano"} />
          <Fact label="Pierwsze szkolenie" value={application.first_training} />
        </dl>
        <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Jak to działa: </span>
          {TRAINER_FLOW.slice(1).join(" → ")}.
        </p>
      </Panel>
    </div>
  );
}
