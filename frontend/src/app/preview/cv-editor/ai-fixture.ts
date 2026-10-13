// Fikcyjne „AI na zaznaczeniu” dla harnessu `/preview/cv-editor`.
//
// Zero sieci i zero modelu: propozycje to proste przekształcenia tekstu — tyle,
// żeby przeklikać obieg zaznaczenie → propozycja → „Przyjmij / Jeszcze raz /
// Doprecyzuj / Odrzuć”. Prawdziwa kontrola „bez nowych faktów” jest na serwerze
// (`services/cv_selection_ai.py`).

import type { CvAiRequest, CvAiResponse, CvEditorAiApi } from "@/lib/api/cvEditorAi";

const EN: ReadonlyArray<[RegExp, string]> = [
  [/Rozwój/g, "Development of"],
  [/Tworzenie/g, "Building"],
  [/Optymalizacja/g, "Optimisation of"],
  [/Przeglądy kodu/g, "Code reviews"],
  [/wdrażanie młodszych programistów/g, "onboarding of junior developers"],
  [/mikroserwisów płatności/g, "payment microservices"],
  [/usług/g, "services"],
  [/zapytań/g, "queries"],
  [/Integracje z systemami zewnętrznymi przez kolejki komunikatów/g, "Integrations with external systems via message queues"],
  [/Testy jednostkowe i integracyjne/g, "Unit and integration tests"],
  [/ w /g, " in "],
  [/ i /g, " and "],
];

function reply(action: string, overrides: Partial<CvAiResponse>): CvAiResponse {
  return {
    status: "ok",
    action,
    proposed_text: null,
    verified: false,
    sources: [],
    cautions: [],
    reason: null,
    problem: null,
    message: null,
    ...overrides,
  };
}

function propose(body: CvAiRequest): CvAiResponse {
  const { action, fragment } = body;
  const attempt = (body.previous?.length ?? 0) + 1;
  if (action === "shorten") {
    const words = fragment.replace(/\*\*/g, "").split(" ");
    if (words.length < 3) {
      return reply(action, {
        status: "rejected",
        reason: "not_shorter",
        message: "Propozycja nie była krótsza od zaznaczonego tekstu. Spróbuj jeszcze raz.",
      });
    }
    const keep = Math.max(2, Math.ceil(words.length * (attempt > 1 ? 0.5 : 0.7)));
    return reply(action, { proposed_text: words.slice(0, keep).join(" ").replace(/[,;]$/, "") });
  }
  if (action === "proofread") {
    const fixed = fragment.replace(/Github/g, "GitHub").replace(/Javie 11/g, "Java 11");
    return fixed === fragment
      ? reply(action, { status: "rejected", reason: "unchanged", message: "AI nie zmieniło tekstu — nie ma tu nic do poprawienia." })
      : reply(action, { proposed_text: fixed });
  }
  if (action === "translate") {
    const text = EN.reduce((out, [pattern, word]) => out.replace(pattern, word), fragment);
    return reply(action, { proposed_text: text });
  }
  if (action === "expand") {
    if (fragment.includes("Testy jednostkowe")) {
      return reply(action, {
        proposed_text: `${fragment.replace(/\.$/, "")} oraz testy API w Postman i RestSharp.`,
        verified: true,
        sources: [{ kind: "original", quote: "Testy API w Postman i RestSharp" }],
      });
    }
    if (fragment.includes("kolejki")) {
      return reply(action, {
        proposed_text: `${fragment.replace(/\.$/, "")} — **Kafka** w projekcie płatności przez około 3 lata.`,
        verified: true,
        sources: [{ kind: "notes", quote: "Kafka w projekcie płatności przez około 3 lata" }],
      });
    }
    return reply(action, {
      status: "rejected",
      reason: "no_quote",
      message:
        "AI nie wskazało zdania z oryginalnego CV ani z notatek, na którym można oprzeć rozwinięcie. Jeśli kandydat to robił, zapytaj go i zapisz w notatce.",
    });
  }
  const hint = body.instruction ? ` (${body.instruction})` : "";
  const plain = fragment.replace(/^Rozwój /, "Rozwijała ").replace(/^Tworzenie /, "Tworzyła ").replace(/^Optymalizacja /, "Optymalizowała ");
  return reply(action, { proposed_text: attempt > 1 ? `${plain} — wersja ${attempt}${hint}` : `${plain}${hint}` });
}

export function memoryAiApi(down: boolean): CvEditorAiApi {
  return {
    propose: async (_stageId, body) => {
      // Chwila zwłoki — widać stan „AI przygotowuje propozycję…”.
      await new Promise((resolve) => setTimeout(resolve, 350));
      if (down) {
        return reply(body.action, {
          status: "unavailable",
          message: "Podpowiedź AI jest chwilowo niedostępna. Popraw fragment ręcznie albo spróbuj za chwilę.",
        });
      }
      return propose(body);
    },
  };
}
