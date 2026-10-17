"use client";

/**
 * Harness „Opieka → Komunikaty” (makiety M7–M8, O12).
 *
 * Prawdziwa zakładka `AnnouncementsTab` (w aplikacji wpięta w `CareScreen`)
 * na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 *
 * Stany (`?state=`, wybrany komunikat w `?announcement=`):
 * - `head` (domyślnie) — head back office: lista z komunikatem czekającym na
 *   jego zatwierdzenie (124 osoby), wysłanym informacyjnym i wysłanym do
 *   klienta; karta komunikatu do zatwierdzenia;
 * - `report` — ta sama lista, raport wysłanego: 117 wysłanych, 2 odbite,
 *   5 wypisanych wcześniej, 1 nowy wypis, 23 odpowiedzi w Sprawach;
 * - `new` — opiekunka pisze nowy komunikat do wszystkich (126 w grupie,
 *   2 bez adresu, powyżej 20 osób → zatwierdzenie);
 * - `off` — wysyłka do konsultantów wyłączona (stan po wdrożeniu): szkic
 *   i podgląd działają, „Wyślij” do kolejki zablokowane.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { AnnouncementsTab } from "@/components/care/announcements/AnnouncementsTab";
import { announcementKeys } from "@/lib/api/care-announcements";

import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import {
  AUTHOR,
  CLIENT_SENT_ID,
  DRAFT_ID,
  HEAD,
  PENDING_ID,
  SENT_ID,
  detail,
  list,
  options,
  preview,
} from "./fixtures";

const KNOWN = ["head", "report", "new", "off"] as const;
type HarnessState = (typeof KNOWN)[number];

const STATES = [
  { key: "head", label: "Do zatwierdzenia", href: `?state=head&announcement=${PENDING_ID}` },
  { key: "report", label: "Raport wysłanego", href: `?state=report&announcement=${SENT_ID}` },
  { key: "new", label: "Nowy komunikat", href: "?state=new&announcement=new" },
  { key: "off", label: "Wysyłka wyłączona", href: "?state=off" },
] as const;

function prepare(params: URLSearchParams) {
  const state: HarnessState = pickState(params.get("state"), KNOWN, "head");
  const viewer = state === "new" || state === "off" ? "author" : "head";
  const client = harnessQueryClient();
  client.setQueryData(
    announcementKeys.list,
    list(viewer, state === "off" ? { sending_enabled: false } : {}),
  );
  for (const id of [PENDING_ID, SENT_ID, CLIENT_SENT_ID, DRAFT_ID]) {
    client.setQueryData(announcementKeys.detail(id), detail(id, viewer));
  }
  client.setQueryData(announcementKeys.options, options());
  for (const kind of ["mandatory", "informational"] as const) {
    client.setQueryData(announcementKeys.preview(kind, { group: "all" }), preview());
  }
  const user = viewer === "head" ? { ...HEAD, role: "delivery_lead" as const } : AUTHOR;
  return { user, client, value: { state } };
}

export default function HrAnnouncementsPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Opieka → Komunikaty"
      note="Dane fikcyjne, bez zapytań. Head back office zatwierdza komunikaty powyżej 20 osób; opiekunka pisze nowy. Nic nie wychodzi do konsultantów."
      states={STATES}
      current={state}
    >
      <div className="space-y-4">
        <PageHeader
          title="Opieka nad konsultantami"
          description="Komunikaty mailowe do grup konsultantów z administracja@."
          density="compact"
        />
        <AnnouncementsTab />
      </div>
    </HrHarnessShell>
  );
}
