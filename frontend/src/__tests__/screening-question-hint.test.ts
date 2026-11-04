/**
 * Podpowiedź przy pytaniu Championa (23.10.2026): tak/nie i pytanie o metodę
 * dostają podpowiedź, pytanie o zrobioną pracę — nie.
 */

import { describe, expect, it } from "vitest";

import { screeningQuestionHint } from "@/lib/screening-question-hint";

describe("screeningQuestionHint", () => {
  it("pytanie tak/nie", () => {
    expect(screeningQuestionHint("Czy znasz Palo Alto?")).toMatch(/tak\/nie/);
    expect(screeningQuestionHint("czy masz doświadczenie z Kafką?")).toMatch(/tak\/nie/);
  });

  it("pytanie o metodę", () => {
    for (const question of [
      "Jak analizujesz NIC-i, adresy IP, VLAN-y i ścieżki ruchu?",
      "Jak identyfikujesz backup na niewłaściwej ścieżce Management?",
      "W jaki sposób testujesz API?",
    ]) {
      expect(screeningQuestionHint(question), question).toMatch(/metodę/);
    }
  });

  it("pytanie o zrobioną pracę i puste pole bez podpowiedzi", () => {
    for (const question of [
      "Jak weryfikowałeś/aś separację ruchu Data i Management?",
      "Jakie masz doświadczenie w migracjach sieci?",
      "Jak długo pracowałeś z Kubernetes?",
      "W jakim projekcie rozdzielałeś ruch Data i Management?",
      "Opisz migrację, którą prowadziłeś.",
      "",
      null,
    ]) {
      expect(screeningQuestionHint(question), String(question)).toBeNull();
    }
  });
});
