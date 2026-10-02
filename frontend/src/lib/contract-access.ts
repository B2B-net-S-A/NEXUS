/**
 * Bramki akcji na kontrakcie — JEDNO miejsce dla karty kontraktu
 * (`app/contracts/[id]/page.tsx`) i bocznego panelu rejestru
 * (`components/contracts/ContractSidePanel.tsx`). Dwie kopie tych warunków
 * rozjechałyby się przy pierwszej zmianie: panel pokazałby przycisk, który
 * karta chowa (albo odwrotnie), a backend i tak odmówi 403.
 *
 * Backend pozostaje arbitrem — to tylko lustro, które decyduje, czy przycisk
 * w ogóle się renderuje. Od 0410 lustrem są uprawnienia z ekranu Ustawienia →
 * Zespół i dostęp → Osoby i role (`lib/permissions.ts`), nie role.
 */
import { hasPermission } from "@/lib/permissions";
import { hasSectionAccess } from "@/lib/section-access";
import {
  canManageCandidateFinance,
  canManageContractStatus,
  canRecoverContractTermination,
  canViewClientFinance,
  hasAnalyticsCapability,
  hasRole,
  type User,
} from "@/store/auth";

export interface ContractAccess {
  isAdmin: boolean;
  /** Zmiana kwot kontraktu („Stawki i kwoty: zmiana”, u DL-a tylko klient z przypisania). */
  canManageFinance: boolean;
  /** Benchmark stawek — backend trzyma go za `view_finance` bez wyjątku portfela DL. */
  canViewBenchmark: boolean;
  canViewInvoices: boolean;
  canManageInvoices: boolean;
  /** Edycja pól operacyjnych, dokumentów, aneksów, usunięcie („Kontrakty i zamówienia: tworzenie i edycja”). */
  canEditContract: boolean;
  /** Sama zmiana kwot, bez edycji kontraktu: formularz ograniczony do kwot (`finance_amounts_only`). */
  financeAmountsOnly: boolean;
  /** Lista statusu i „Zakończ współpracę” („Zakończenie współpracy, zmiana statusu kontraktu”). */
  canEditContractStatus: boolean;
  /** „Cofnij zakończenie” / „Powrót po przerwie” (admin/Finanse/TCM — zostaje przy roli). */
  canRecoverTermination: boolean;
  /** Stawki i marża TEGO kontraktu („Stawki i kwoty: podgląd”, portfel DL liczony per klient). */
  canViewFinance: boolean;
  /** Dokumenty mogą nieść stawki — ta sama granica co finanse. */
  canViewContractDocuments: boolean;
  canEditContractDocuments: boolean;
  /** „Przepnij na innego klienta” — wyłącznie admin, nie w podglądzie. */
  canReassignClient: boolean;
}

export function contractAccess(
  user: User | null | undefined,
  options: { impersonating: boolean; clientId: number | null | undefined },
): ContractAccess {
  const { impersonating, clientId } = options;
  const isAdmin = hasRole(user, "admin");
  const canManageFinance = canManageCandidateFinance(user, clientId);
  const canViewBenchmark = hasAnalyticsCapability(user, "view_finance");
  // Sekcja jest sufitem trasy (zapis w Delivery); przy świeżym profilu wynika
  // z uprawnienia, stary wyjątek osoby potrafi ją jeszcze ograniczyć.
  const canEditContract =
    !impersonating &&
    hasPermission(user, "contracts_orders_edit") &&
    hasSectionAccess(user, "delivery", "write");
  const canViewFinance =
    clientId != null ? canViewClientFinance(user, clientId) : false;
  const canViewContractDocuments = canViewFinance;
  return {
    isAdmin,
    canManageFinance,
    canViewBenchmark,
    canViewInvoices: canViewBenchmark,
    canManageInvoices: hasAnalyticsCapability(user, "manage_finance"),
    canEditContract,
    financeAmountsOnly: !impersonating && !canEditContract && canManageFinance,
    canEditContractStatus: !impersonating && canManageContractStatus(user),
    canRecoverTermination: !impersonating && canRecoverContractTermination(user),
    canViewFinance,
    canViewContractDocuments,
    canEditContractDocuments: canEditContract && canViewContractDocuments,
    canReassignClient: isAdmin && !impersonating,
  };
}
