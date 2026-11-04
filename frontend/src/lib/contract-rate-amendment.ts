/**
 * „Zmień stawkę” — aneks `rate_change` na kontrakcie. Jedna reguła dla
 * zakładki Aneksy (`ContractAmendmentsTab`) i menu „Aneks” bocznego panelu
 * (`ContractSidePanel`); dwie kopie rozjechały się już raz (audyt 24.09, S10).
 *
 * Lustro `can_manage_finance_amounts` (`backend/app/api/financial_access.py`):
 * uprawnienie „Stawki i kwoty: zmiana”. Konto rządzone portfelem Delivery
 * Leada zmienia kwoty wyłącznie u klientów z przypisania
 * (`data_scope.finance_client_ids`), pozostali posiadacze — u wszystkich.
 *
 * Samo prawo do aneksów (zapis na kontrakcie, tryb podglądu) sprawdza
 * wołający — ta funkcja odpowiada tylko na pytanie o kwoty.
 */
import { hasPermission, isDeliveryLeadGoverned } from "@/lib/permissions";
import type { User } from "@/store/auth";

type RateAmendmentUser =
  | Pick<User, "role" | "roles" | "effective_action_access" | "data_scope">
  | null
  | undefined;

export function canAmendContractRates(
  user: RateAmendmentUser,
  clientId: number | null | undefined,
): boolean {
  if (!hasPermission(user, "amounts_edit")) return false;
  if (!isDeliveryLeadGoverned(user)) return true;
  return (
    clientId != null &&
    (user?.data_scope?.finance_client_ids ?? []).includes(clientId)
  );
}
