/**
 * Odpowiedzi asystenta w harnessie — bez sieci i bez modelu.
 *
 * Odpowiada jak trasa `cv-ai/command`: operacje na numerach wierszy, które
 * przysłał edytor. Dane są fikcyjne; reguły doboru proste i przewidywalne,
 * żeby dało się przeklikać każdy rodzaj operacji (Edytor CV 3, PR 4: także
 * dopisanie z pytaniem o źródło, pogrubienie i „Rozważany na stanowisko”).
 */

import type {
  CvCommandLine,
  CvCommandRequest,
  CvCommandResponse,
  CvEditorCommandApi,
  CvPlanOperation,
} from "@/lib/api/cvEditorCommand";

type Draft = Omit<CvPlanOperation, "id">;

function bulletsOfRole(lines: CvCommandLine[], role: number): CvCommandLine[] {
  return lines.filter((line) => line.kind === "bullet" && line.role === role);
}

function plan(body: CvCommandRequest): Draft[] {
  const { lines } = body;
  const text = (body.command ?? "").toLowerCase();
  const roles = [...new Set(lines.map((line) => line.role).filter((role): role is number => role != null))];
  const operations: Draft[] = [];

  // „dopisz terraform …” — fakt spoza CV: asystent pyta o źródło.
  if (text.includes("terraform")) {
    const first = roles[0];
    const bullet = first != null ? bulletsOfRole(lines, first)[0] : undefined;
    if (bullet) {
      operations.push({
        type: "add",
        lines: [bullet.id],
        text: "Infrastruktura jako kod w **Terraform**.",
        why: "Dopisany punkt z rozmowy z kandydatem.",
        loses: [],
        new_words: [],
        ask: "source",
        problem: "Terraform",
      });
    }
    return operations;
  }

  // „stanowisko: X” — cel rekrutacji w linii „Rozważany na stanowisko”.
  const target = /stanowisko:\s*(.+)$/i.exec(body.command ?? "");
  if (target) {
    const line = lines.find((item) => item.kind === "text" && item.text.startsWith("**Rozważany na stanowisko:**"));
    if (line) {
      operations.push({
        type: "considered_for",
        lines: [line.id],
        text: `**Rozważany na stanowisko:** ${target[1].trim()}`,
        why: "Nowe stanowisko, na które przedstawiamy kandydatkę.",
        loses: [],
        new_words: [],
      });
    }
    return operations;
  }

  // „pogrub …” — terminy, które stoją w CV.
  if (text.includes("pogrub") || body.preset === "more_requirements") {
    operations.push({
      type: "bold",
      lines: [],
      text: null,
      why: "Wymagania klienta widoczne na pierwszy rzut oka.",
      loses: [],
      new_words: [],
      terms: ["PostgreSQL", "Docker"],
    });
    return operations;
  }

  if (body.preset === "order_by_requirements" || text.includes("kolejno")) {
    for (const role of roles) {
      const bullets = bulletsOfRole(lines, role);
      if (bullets.length < 2) continue;
      operations.push({
        type: "reorder",
        lines: [...bullets.slice(1), bullets[0]].map((line) => line.id),
        text: null,
        why: "Punkty najbliższe wymaganiom klienta idą na początek.",
        loses: [],
        new_words: [],
      });
    }
    return operations;
  }

  if (body.preset === "unify_sentences" || text.includes("ujednoli")) {
    for (const line of lines) {
      if (line.kind !== "bullet" || !/^(Rozwój|Tworzenie|Optymalizacja) /.test(line.text)) continue;
      operations.push({
        type: "replace",
        lines: [line.id],
        text: line.text
          .replace(/^Rozwój /, "Rozwijała ")
          .replace(/^Tworzenie /, "Tworzyła ")
          .replace(/^Optymalizacja /, "Optymalizowała "),
        why: "Ta sama forma we wszystkich punktach.",
        loses: [],
        new_words: [],
      });
    }
    return operations;
  }

  if (body.preset === "drop_old_roles" || text.includes("stanowisk")) {
    const last = roles[roles.length - 1];
    if (roles.length > 1 && last != null) {
      operations.push({
        type: "remove_role",
        lines: lines.filter((line) => line.role === last).map((line) => line.id),
        text: null,
        why: "Najstarsze stanowisko, najdalej od wymagań klienta.",
        loses: ["JUnit"],
        new_words: [],
        ask: "loses",
      });
    }
    return operations;
  }

  // „Skróć”: ogólnik z podsumowania, połączenie dwóch punktów, sekcja języków.
  const general = lines.find((line) => line.kind === "bullet" && line.role == null && line.text.includes("lat doświadczenia"));
  if (general) {
    operations.push({
      type: "remove",
      lines: [general.id],
      text: null,
      why: "Ogólne zdanie, powtarza nagłówek CV.",
      loses: [],
      new_words: [],
    });
  }
  const first = roles[0];
  const bullets = first != null ? bulletsOfRole(lines, first) : [];
  if (bullets.length >= 3) {
    operations.push({
      type: "merge",
      lines: [bullets[1].id, bullets[2].id],
      text: `${bullets[1].text.replace(/\.$/, "")}; ${bullets[2].text.charAt(0).toLowerCase()}${bullets[2].text.slice(1)}`,
      why: "Dwa krótkie punkty o pracy w zespole w jednym.",
      loses: [],
        new_words: [],
    });
  }
  const languages = lines.find((line) => line.kind === "heading" && line.section === "languages");
  if (languages) {
    const next = lines.find((line) => line.id > languages.id && (line.kind === "heading" || line.kind === "title"));
    const end = next ? next.id : lines.length;
    operations.push({
      type: "remove_section",
      lines: lines.filter((line) => line.id >= languages.id && line.id < end).map((line) => line.id),
      text: null,
      why: "Języki są w wymaganiach rekrutacji — sekcja zostaje tylko, gdy klient o nią prosi.",
      loses: [],
        new_words: [],
    });
  }
  return operations;
}

export function memoryCommandApi(down: boolean): CvEditorCommandApi {
  return {
    plan: async (_stageId, body): Promise<CvCommandResponse> => {
      // Chwila zwłoki — widać stan „Asystent przygotowuje plan zmian…”.
      await new Promise((resolve) => setTimeout(resolve, 350));
      if (down) {
        return {
          status: "unavailable",
          operations: [],
          dropped: [],
          message: "Asystent jest chwilowo niedostępny. Popraw CV ręcznie albo spróbuj za chwilę.",
        };
      }
      const operations = plan(body).map((operation, id) => ({ id, ...operation }));
      if (operations.length === 0) {
        return {
          status: "empty",
          operations: [],
          dropped: [],
          message: "Asystent nie znalazł zmian, które odpowiadają temu poleceniu.",
        };
      }
      return {
        status: "ok",
        operations,
        dropped: [{ type: "replace", reason: "not_editable", problem: null }],
        message: null,
      };
    },
    // „Tak, dopisz”: w harnessie notatki nie ma gdzie zapisać — sama chwila zwłoki.
    confirmFact: async () => {
      await new Promise((resolve) => setTimeout(resolve, 150));
    },
  };
}
