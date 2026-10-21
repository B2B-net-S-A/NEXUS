// Lustro `ContractDocumentType` z backendu (`app/models/contract_document.py`).
export const DOC_TYPES: { value: string; label: string }[] = [
  { value: "contract", label: "Umowa" },
  { value: "annex", label: "Aneks" },
  { value: "nda", label: "NDA" },
  { value: "nip", label: "NIP" },
  { value: "zus_certificate", label: "Zaświadczenie ZUS" },
  { value: "oc_policy", label: "Polisa OC" },
  { value: "order", label: "Zamówienie" },
  // 0367: załącznik z okna „Zakończ współpracę" (rozwiązanie umowy B2B).
  { value: "termination_notice", label: "Wypowiedzenie" },
  { value: "termination_agreement", label: "Porozumienie" },
  { value: "other", label: "Inne" },
];

export const DOC_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  DOC_TYPES.map((d) => [d.value, d.label]),
);
