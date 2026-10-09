"use client";

// Jeden ekran „Powiadomienia” zamiast trzech rozrzuconych po Ustawieniach:
// własne wyciszenia („Moje”), tabela rola × kategoria („Kto co dostaje”),
// firmowe przełączniki maili („Maile”) i wskazówka, gdzie są reguły etapów.
// Otwierają go DWIE pozycje rejestru (stare linki i link z dzwonka):
// „Moje powiadomienia” startuje na „Moje”, „Powiadomienia” w Systemie — na
// „Kto co dostaje”. Zakładka żyje w adresie (`?sub=`).

import { useMemo } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { TabbedNav, type TabbedNavItem } from "@/components/ds/TabbedNav";
import NotificationDeliverySettings from "@/components/settings/NotificationDeliverySettings";
import { NotificationPreferencesPanel } from "@/components/settings/NotificationPreferencesPanel";
import { NotificationRoleMatrix } from "@/components/settings/NotificationRoleMatrix";
import { hasSectionAccess } from "@/lib/section-access";
import {
  NOTIFICATIONS_SUBTAB_PARAM,
  useNotificationsSubTab,
  type NotificationsSubTab,
} from "@/lib/settings-notifications-subtab";
import { canSeeSettingsItem, findSettingsItem } from "@/lib/settings-registry";
import { hasRole, useAuthStore } from "@/store/auth";

const TAB_LABELS: Record<NotificationsSubTab, string> = {
  moje: "Moje",
  role: "Kto co dostaje",
  maile: "Maile",
  etapy: "Reguły etapów",
};

const TAB_ORDER: readonly NotificationsSubTab[] = ["moje", "role", "maile", "etapy"];

type SettingsUser = Parameters<typeof canSeeSettingsItem>[0];

/** Zakładki, które konto widzi — „Moje” zawsze, reszta lustrem bramek backendu. */
export function availableNotificationTabs(user: SettingsUser): NotificationsSubTab[] {
  // Ta sama reguła co `NotificationDeliverySettings` i trasy `/api/settings/*`.
  const companyWide =
    hasRole(user, "admin") && hasSectionAccess(user, "system_admin", "read");
  // Reguły etapów ustawia się w „Procesach rekrutacyjnych” — ta sama bramka.
  const stages = findSettingsItem("stages");
  const stageRules = !!stages && canSeeSettingsItem(user, stages);
  return TAB_ORDER.filter((tab) => {
    if (tab === "role" || tab === "maile") return companyWide;
    if (tab === "etapy") return stageRules;
    return true;
  });
}

function StageRulesCard() {
  return (
    <section
      className="rounded-xl border border-border bg-card p-5"
      aria-labelledby="notification-stage-rules-heading"
    >
      <h2 id="notification-stage-rules-heading" className="font-semibold text-foreground">
        Reguły etapów
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Reguły etapów mówią, kto dostaje powiadomienie, gdy kandydat wchodzi na
        dany etap rekrutacji. Ustawia się je przy etapie: Procesy rekrutacyjne
        → etap → „Powiadomienia”.
      </p>
      <Link
        href="/settings?item=stages"
        className="mt-4 inline-flex min-h-9 items-center rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-10"
      >
        Otwórz Procesy rekrutacyjne
      </Link>
    </section>
  );
}

export interface NotificationsSettingsProps {
  /** Zakładka, gdy adres nie niesie `?sub=` (zależy od pozycji Ustawień). */
  defaultTab: NotificationsSubTab;
}

export function NotificationsSettings({ defaultTab }: NotificationsSettingsProps) {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);
  const searchParams = useSearchParams();
  const available = useMemo(() => availableNotificationTabs(user), [user]);
  const [tab, selectTab] = useNotificationsSubTab(
    searchParams?.get(NOTIFICATIONS_SUBTAB_PARAM) ?? null,
    available,
    defaultTab,
  );

  // Uprawnienia konta dochodzą po hydratacji — do tego czasu nie zgadujemy,
  // które zakładki pokazać.
  if (!hydrated) return <p role="status">Ładowanie ustawień…</p>;

  const tabs: TabbedNavItem[] = available.map((value) => ({
    value,
    label: TAB_LABELS[value],
  }));

  return (
    <div className="space-y-4">
      {/* Jedna dostępna zakładka (większość kont) = bez paska zakładek. */}
      {tabs.length > 1 ? (
        <TabbedNav
          tabs={tabs}
          value={tab}
          onValueChange={(value) => selectTab(value as NotificationsSubTab)}
          ariaLabel="Powiadomienia"
        />
      ) : null}
      {tab === "moje" ? <NotificationPreferencesPanel /> : null}
      {tab === "role" ? <NotificationRoleMatrix /> : null}
      {tab === "maile" ? (
        <NotificationDeliverySettings onGoToMine={() => selectTab("moje")} />
      ) : null}
      {tab === "etapy" ? <StageRulesCard /> : null}
    </div>
  );
}

export default NotificationsSettings;
