"use client";

/**
 * Harness strony „Daily — requesty i obłożenie” (`/jobs/daily`) — publiczny,
 * ZERO zapytań. Renderuje widok `RequestBoardView` w wariancie `daily` z danych
 * fikcyjnych (repo jest publiczne — żadnych prawdziwych nazwisk): cztery
 * kategorie, osiem requestów (propozycja automatu, request bez rekrutera,
 * champion), obłożenie z urlopem i sześć zmian od piątku 9:30 (poniedziałek
 * rano — okno obejmuje weekend). Przyciski nic nie zapisują; filtry
 * i „Następna kategoria →” działają lokalnie.
 */

import { useState } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { RequestBoardView } from "@/components/v2/request-board/RequestBoard";
import type { RequestBoard } from "@/lib/api/requestAllocation";
import { EMPTY_FILTERS, type BoardFilters } from "@/lib/request-board";

/** Poniedziałek; okno zmian zaczyna się w piątek o 9:30 czasu firmy. */
const TODAY = "2026-10-05";
const noop = () => undefined;

const people = {
  anna: { user_id: 1, name: "Anna Przykładowa" },
  bartek: { user_id: 2, name: "Bartek Testowy" },
  celina: { user_id: 3, name: "Celina Wzorcowa" },
  darek: { user_id: 4, name: "Darek Makietowy" },
  ewa: { user_id: 5, name: "Ewa Fikcyjna" },
};

const leads = {
  gosia: { id: 61, name: "Gosia Delivery" },
  henryk: { id: 62, name: "Henryk Pokazowy" },
};

const BOARD: RequestBoard = {
  mode: "shadow",
  availability_known: true,
  viewer: { user_id: 70, primary_category_id: null },
  changes_since: "2026-10-02T07:30:00Z",
  groups: [
    { category_id: 1, name: "Infra & Operations & Security / Data & AI", slug: "infrastructure_operations", total: 2, searching: 2, champion: 0 },
    { category_id: 2, name: "Development", slug: "software_development", total: 3, searching: 2, champion: 1 },
    { category_id: 4, name: "QA", slug: "security_quality", total: 2, searching: 2, champion: 0 },
    { category_id: 5, name: "Management & Delivery (PM & BA)", slug: "management_delivery", total: 1, searching: 1, champion: 0 },
  ],
  requests: [
    // Propozycja automatu: nikt jeszcze nie pracuje, czeka na akceptację.
    { job_id: 11, title: "DevOps Engineer (Azure)", client_name: "Klient Alfa", category_id: 1, deadline: "2026-10-09", sent: 0, champion: false, priority_level: "p1", delivery_lead: leads.gosia, opened_effective_at: "2026-10-01T07:30:00Z", people: [{ ...people.anna, proposed: true, source: "auto", via: "assignment", assigned_by_name: null }] },
    { job_id: 12, title: "Data Engineer", client_name: "Klient Beta", category_id: 1, deadline: "2026-10-02", sent: 1, champion: false, priority_level: "p2", delivery_lead: leads.henryk, opened_effective_at: "2026-09-18T09:00:00Z", people: [{ ...people.bartek, proposed: false, source: "owner", via: "owner", assigned_by_name: null }] },
    { job_id: 21, title: "Senior Java Developer", client_name: "Klient Gamma", category_id: 2, deadline: "2026-10-07", sent: 0, champion: false, priority_level: "p1", delivery_lead: leads.gosia, opened_effective_at: "2026-09-25T08:00:00Z", people: [{ ...people.celina, proposed: false, source: "manual", via: "assignment", assigned_by_name: "Henryk Pokazowy" }, { ...people.anna, proposed: false, source: "manual", via: "collaborator", assigned_by_name: null }] },
    { job_id: 22, title: "Kotlin Developer", client_name: "Klient Delta", category_id: 2, deadline: "2026-10-16", sent: 2, champion: false, priority_level: "p2", delivery_lead: leads.henryk, opened_effective_at: "2026-09-28T10:00:00Z", people: [{ ...people.darek, proposed: false, source: "owner", via: "owner", assigned_by_name: null }] },
    // Champion: stoi na dole grupy, przygaszony.
    { job_id: 23, title: "React Developer", client_name: "Klient Alfa", category_id: 2, deadline: "2026-10-08", sent: 3, champion: true, priority_level: "p2", delivery_lead: leads.gosia, opened_effective_at: "2026-09-10T08:00:00Z", people: [{ ...people.darek, proposed: false, source: "owner", via: "owner", assigned_by_name: null }] },
    // „Bez rekrutera”: nikt nie pracuje i automat nikogo nie proponuje.
    { job_id: 41, title: "Tester automatyzujący", client_name: "Klient Beta", category_id: 4, deadline: null, sent: 0, champion: false, priority_level: "accepting", delivery_lead: null, opened_effective_at: "2026-10-03T12:00:00Z", people: [] },
    { job_id: 42, title: "Test Lead", client_name: "Klient Gamma", category_id: 4, deadline: "2026-10-12", sent: 1, champion: false, priority_level: "p2", delivery_lead: leads.henryk, opened_effective_at: "2026-09-29T08:00:00Z", people: [{ ...people.celina, proposed: false, source: "manual", via: "assignment", assigned_by_name: "Gosia Delivery" }] },
    { job_id: 51, title: "Product Owner", client_name: "Klient Gamma", category_id: 5, deadline: "2026-10-19", sent: 2, champion: false, priority_level: "p2", delivery_lead: leads.henryk, opened_effective_at: "2026-09-20T08:00:00Z", people: [{ ...people.ewa, proposed: false, source: "manual", via: "assignment", assigned_by_name: "Gosia Delivery" }] },
  ],
  load: [
    { ...people.anna, count: 1, proposed: 1, leave_until: null, requests: [
      { job_id: 21, title: "Senior Java Developer", client_name: "Klient Gamma", deadline: "2026-10-07", proposed: false },
      { job_id: 11, title: "DevOps Engineer (Azure)", client_name: "Klient Alfa", deadline: "2026-10-09", proposed: true },
    ] },
    { ...people.bartek, count: 1, proposed: 0, leave_until: null, requests: [
      { job_id: 12, title: "Data Engineer", client_name: "Klient Beta", deadline: "2026-10-02", proposed: false },
    ] },
    { ...people.celina, count: 2, proposed: 0, leave_until: null, requests: [
      { job_id: 21, title: "Senior Java Developer", client_name: "Klient Gamma", deadline: "2026-10-07", proposed: false },
      { job_id: 42, title: "Test Lead", client_name: "Klient Gamma", deadline: "2026-10-12", proposed: false },
    ] },
    { ...people.darek, count: 1, proposed: 0, leave_until: null, requests: [
      { job_id: 22, title: "Kotlin Developer", client_name: "Klient Delta", deadline: "2026-10-16", proposed: false },
    ] },
    // Urlop: obłożenie zostaje widoczne, ktoś przejmie requesty.
    { ...people.ewa, count: 1, proposed: 0, leave_until: "2026-10-09", requests: [
      { job_id: 51, title: "Product Owner", client_name: "Klient Gamma", deadline: "2026-10-19", proposed: false },
    ] },
  ],
  changes: [
    { at: "2026-10-05T06:30:00Z", kind: "assigned", job_id: 11, title: "DevOps Engineer (Azure)", client_name: "Klient Alfa", user_name: people.anna.name, reason: "propozycja automatu" },
    { at: "2026-10-03T12:05:00Z", kind: "assigned", job_id: 42, title: "Test Lead", client_name: "Klient Gamma", user_name: people.celina.name, reason: "dodane ręcznie" },
    { at: "2026-10-02T15:40:00Z", kind: "champion", job_id: 23, title: "React Developer", client_name: "Klient Alfa", user_name: null, reason: "Mamy championa" },
    { at: "2026-10-02T15:40:00Z", kind: "released", job_id: 23, title: "React Developer", client_name: "Klient Alfa", user_name: people.bartek.name, reason: "Mamy championa" },
    { at: "2026-10-02T11:20:00Z", kind: "assigned", job_id: 21, title: "Senior Java Developer", client_name: "Klient Gamma", user_name: people.anna.name, reason: "dodane ręcznie" },
    { at: "2026-10-02T08:10:00Z", kind: "released", job_id: 41, title: "Tester automatyzujący", client_name: "Klient Beta", user_name: people.ewa.name, reason: "urlop" },
  ],
};

export default function DailyPreview() {
  const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS);
  return (
    <main className="flex flex-col gap-5 bg-background p-4 md:p-6">
      <PageHeader
        title="Daily — requesty i obłożenie"
        description="Co zmieniło się od wczoraj, kto nad czym pracuje i komu brakuje rekrutera — kategoria po kategorii."
      />
      <RequestBoardView
        board={BOARD}
        variant="daily"
        today={TODAY}
        filters={filters}
        onFilters={setFilters}
        canStaff
        canDecide
        onAddPerson={noop}
        onRemovePerson={noop}
        onAcceptProposal={noop}
      />
    </main>
  );
}
