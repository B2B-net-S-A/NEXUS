"use client";

// Zakładka „Generator aneksów” (`?tab=annexes`): całe życie aneksu w jednym
// miejscu — kreator „Nowy aneks” (typ → osoba → treść) i pod nim rejestr
// aneksów (13.10.2026). Wejście z adresu (`&new=<typ>&parent=<id>` z wiersza
// rejestru umów, `&contract=<id>` z Kontraktów) otwiera kreator od razu;
// `&q=` filtruje rejestr (link z etykiety aneksu na wierszu umowy).
// Zakładkę widzi każdy użytkownik generatora — potwierdzający podpis
// i Finanse nie mają prawa generowania, a to oni oznaczają aneks jako
// podpisany; sam kreator wymaga uprawnienia „Generowanie”.

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useUrlWriter } from "@/lib/url-selection";
import { Loader2 } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useDocumentTypes, type DocumentItem } from "@/lib/api/b2bDocuments";
import { DOCUMENTS_INTENT_KEYS, parseDocumentsIntent } from "@/lib/b2b-documents";

import { AnnexRegister } from "./AnnexRegister";
import { BusinessDataAnnexQueue } from "./BusinessDataAnnexQueue";
import { DocumentWizard } from "./DocumentWizard";

export interface AnnexWizardState {
  key: number;
  type: string | null;
  parentId: number | null;
  contractId: number | null;
  /** „Popraw” z rejestru — kreator wczytuje zapisany aneks. */
  editId: number | null;
}

const EMPTY_WIZARD: Omit<AnnexWizardState, "key"> = {
  type: null,
  parentId: null,
  contractId: null,
  editId: null,
};

export function AnnexGeneratorTab({ canGenerate = true }: { canGenerate?: boolean }) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const { replaceUrl } = useUrlWriter();
  const intent = parseDocumentsIntent(searchParams);
  const [wizard, setWizard] = useState<AnnexWizardState>({ key: 0, ...EMPTY_WIZARD });
  const urlQuery = searchParams?.get("q") ?? "";
  const [search, setSearch] = useState(urlQuery);

  // Fraza z adresu steruje polem także przy miękkiej nawigacji na tej samej
  // stronie (klik w etykietę aneksu w „Umowach bieżących”).
  useEffect(() => {
    setSearch(urlQuery);
  }, [urlQuery]);

  useEffect(() => {
    if (!intent.newType && !intent.parentId && !intent.contractId) return;
    setWizard({
      key: Date.now(),
      type: intent.newType || null,
      parentId: intent.parentId,
      contractId: intent.contractId,
      editId: null,
    });
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    for (const key of DOCUMENTS_INTENT_KEYS) params.delete(key);
    const query = params.toString();
    replaceUrl(query ? `${pathname ?? ""}?${query}` : (pathname ?? ""));
    // Tylko wartości parametrów — zdjęcie ich z adresu nie może otworzyć
    // kreatora drugi raz.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent.newType, intent.parentId, intent.contractId]);

  const writeSearch = (next: string) => {
    setSearch(next);
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    if (next.trim()) params.set("q", next);
    else params.delete("q");
    const query = params.toString();
    replaceUrl(query ? `${pathname ?? ""}?${query}` : (pathname ?? ""));
  };

  return (
    <AnnexGeneratorContent
      canGenerate={canGenerate}
      wizard={wizard}
      onStart={(next) => setWizard({ key: Date.now(), ...EMPTY_WIZARD, ...next })}
      search={search}
      onSearch={writeSearch}
    />
  );
}

/** Treść bez routera — harness montuje ją z zasianym cache'em. */
export function AnnexGeneratorContent({
  canGenerate = true,
  wizard,
  onStart,
  search = "",
  onSearch = () => {},
}: {
  /** Kreator wymaga uprawnienia „Generowanie” — bez niego sam rejestr. */
  canGenerate?: boolean;
  wizard: AnnexWizardState;
  onStart: (next: Partial<Omit<AnnexWizardState, "key">>) => void;
  search?: string;
  onSearch?: (next: string) => void;
}) {
  const types = useDocumentTypes();
  return (
    <div className="space-y-4">
      {canGenerate ? (
        <>
          <p className="text-sm text-muted-foreground">
            Wybierz typ aneksu, potem osobę — pokażemy jej umowy i kontrakty.
            Aneks zapisuje się w rejestrze poniżej, a kontrakt zmienia się po
            „Oznacz jako podpisany”.
          </p>
          <BusinessDataAnnexQueue
            enabled
            onStart={(row) => onStart({ type: "annex_party_data", parentId: row.id })}
          />
          {types.data ? (
            <DocumentWizard
              key={wizard.key}
              mode="annexes"
              typesData={types.data}
              initialType={wizard.type}
              initialParentId={wizard.parentId}
              initialContractId={wizard.contractId}
              editDocumentId={wizard.editId}
              onClose={() => onStart({})}
            />
          ) : types.isError ? (
            <Alert
              variant="error"
              title="Nie udało się wczytać typów aneksów"
              description={apiErrorMessage(types.error, "Spróbuj ponownie za chwilę.")}
            >
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void types.refetch()}
              >
                Ponów
              </Button>
            </Alert>
          ) : (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Wczytuję typy aneksów…
            </p>
          )}
        </>
      ) : null}
      <AnnexRegister
        search={search}
        onSearch={onSearch}
        onEdit={(item: DocumentItem) =>
          onStart({ type: item.document_type, editId: item.id })
        }
      />
    </div>
  );
}
