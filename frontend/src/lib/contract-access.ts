/**
 * Bramki akcji na kontrakcie — JEDNO miejsce dla karty kontraktu
 * (`app/contracts/[id]/page.tsx`) i bocznego panelu rejestru
 * (`components/contracts/ContractSidePanel.tsx`). Dwie kopie tych warunków
 * rozjechałyby się przy pierwszej zmianie: panel pokazałby przycisk, który
 * karta chowa (albo odwrotnie), a backend i tak odmówi 403.
 *
 * Backend pozostaje arbitrem — to tylko lustro, które decyduje, czy przycisk
 * w ogóle się renderuje.
 */
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
  /** Zmiana kwot kontraktu (admin/Finanse z `manage_finance`). */
  canManageFinance: boolean;
  /** Benchmark stawek — backend trzyma go za `view_finance` bez wyjątku portfela DL. */
  canViewBenchmark: boolean;
  canViewInvoices: boolean;
  canManageInvoices: boolean;
  /** Edycja pól operacyjnych, dokumentów, aneksów, usunięcie (admin/DL + zapis Delivery). */
  canEditContract: boolean;
  /** Finanse bez roli admin/DL: edycja ograniczona do kwot (`finance_amounts_only`). */
  financeAmountsOnly: boolean;
  /** Lista statusu i „Zakończ współpracę” (admin/DL/TCM). */
  canEditContractStatus: boolean;
  /** „Cofnij zakończenie” / „Powrót po przerwie” (admin/Finanse/TCM). */
  canRecoverTermination: boolean;
  /** Stawki i marża TEGO kontraktu (portfel DL liczony per klient). */
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
  const canManageFinance = canManageCandidateFinance(user);
  const canViewBenchmark = hasAnalyticsCapability(user, "view_finance");
  const canEditContract =
    !impersonating &&
    hasRole(user, "admin", "delivery_lead") &&
    hasSectionAccess(user, "delivery", "write");
  const canViewFinance =
    clientId != null ? canViewClientFinance(user, clientId) : false;
  const canViewContractDocuments = clientId != null && (isAdmin || canViewFinance);
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
