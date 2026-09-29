"use client";

// Zakładka „Generator aneksów” (`?tab=annexes`, ticket 29.09.2026): całe
// tworzenie aneksów w jednym miejscu. Typ aneksu → umowa z „Umów bieżących”
// albo „Umowa spoza Nexusa” → formularz → podgląd / DOCX. Wejście z adresu
// (`&new=<typ>&parent=<id>` z wiersza rejestru, `&contract=<id>` z Kontraktów)
// otwiera kreator od razu; efekt działa na WARTOŚCI parametrów.

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useDocumentTypes } from "@/lib/api/b2bDocuments";
import { DOCUMENTS_INTENT_KEYS, parseDocumentsIntent } from "@/lib/b2b-documents";

import { BusinessDataAnnexQueue } from "./BusinessDataAnnexQueue";
import { DocumentWizard } from "./DocumentWizard";

interface AnnexWizardState {
  key: number;
  type: string | null;
  parentId: number | null;
  contractId: number | null;
}

export function AnnexGeneratorTab() {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const intent = parseDocumentsIntent(searchParams);
  const [wizard, setWizard] = useState<AnnexWizardState>({
    key: 0,
    type: null,
    parentId: null,
    contractId: null,
  });

  useEffect(() => {
    if (!intent.newType && !intent.parentId && !intent.contractId) return;
    setWizard({
      key: Date.now(),
      type: intent.newType || null,
      parentId: intent.parentId,
      contractId: intent.contractId,
    });
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    for (const key of DOCUMENTS_INTENT_KEYS) params.delete(key);
    const query = params.toString();
    router.replace(query ? `${pathname ?? ""}?${query}` : (pathname ?? ""), {
      scroll: false,
    });
    // Tylko wartości parametrów — zdjęcie ich z adresu nie może otworzyć
    // kreatora drugi raz.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent.newType, intent.parentId, intent.contractId]);

  return (
    <AnnexGeneratorContent
      wizard={wizard}
      onStart={(next) => setWizard({ key: Date.now(), ...next })}
    />
  );
}

/** Treść bez routera — harness montuje ją z zasianym cache'em. */
export function AnnexGeneratorContent({
  wizard,
  onStart,
}: {
  wizard: AnnexWizardState;
  onStart: (next: Omit<AnnexWizardState, "key">) => void;
}) {
  const types = useDocumentTypes();
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Wybierz typ aneksu, potem umowę z listy „Umowy bieżące” albo „Umowa
        spoza Nexusa”. Aneks do umowy z listy zapisuje się przy niej i od razu
        zmienia jej wiersz w rejestrze; kontrakt zmienia się po „Oznacz jako
        podpisany” w zakładce Dokumenty.
      </p>
      <BusinessDataAnnexQueue
        enabled
        onStart={(row) =>
          onStart({ type: "annex_party_data", parentId: row.id, contractId: null })
        }
      />
      {types.data ? (
        <DocumentWizard
          key={wizard.key}
          mode="annexes"
          typesData={types.data}
          initialType={wizard.type}
          initialParentId={wizard.parentId}
          initialContractId={wizard.contractId}
          onClose={() => onStart({ type: null, parentId: null, contractId: null })}
        />
      ) : types.isError ? (
        <Alert
          variant="error"
          title="Nie udało się wczytać typów aneksów"
          description={apiErrorMessage(types.error, "Spróbuj ponownie za chwilę.")}
        >
          <Button variant="outline" size="sm" className="mt-2" onClick={() => void types.refetch()}>
            Ponów
          </Button>
        </Alert>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Wczytuję typy aneksów…
        </p>
      )}
    </div>
  );
}
