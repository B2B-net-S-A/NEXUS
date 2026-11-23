"use client";

/**
 * „Umowa przedwstępna z kandydatami” na `/jobs/new`, w sekcji „Warunki” pod
 * „Procesem u klienta” (0762, decyzje Artura 23.11.2026; domyślnie wyłączone).
 * Idzie w `POST /api/jobs` jako `pre_contract_rule`; po utworzeniu edycja
 * w nagłówku rekrutacji. Ustawia Delivery Lead albo Head of Recruitment.
 */

import { PreContractRuleEditor } from "@/components/v2/jobs/PreContractRuleEditor";
import type { PreContractRuleDraft } from "@/lib/job-request-intake";
import { canSetPreContractStop } from "@/lib/pre-contract-stop";
import { useAuthStore } from "@/store/auth";

interface NewJobPreContractFieldProps {
  value: PreContractRuleDraft | null;
  onChange: (next: PreContractRuleDraft | null) => void;
}

export function NewJobPreContractField({ value, onChange }: NewJobPreContractFieldProps) {
  const canSet = canSetPreContractStop(useAuthStore((st) => st.user));
  return (
    <div className="flex flex-col gap-2 border-t border-border pt-4" data-testid="new-job-pre-contract">
      <p className="text-sm font-medium">
        Umowa przedwstępna z kandydatami <span className="font-normal text-muted-foreground">· opcjonalnie</span>
      </p>
      <PreContractRuleEditor value={value} onChange={onChange} idPrefix="new-job-pre-contract" disabled={!canSet} />
      {!canSet ? (
        <p className="text-xs text-muted-foreground">Ustawia Delivery Lead albo Head of Recruitment.</p>
      ) : null}
    </div>
  );
}
