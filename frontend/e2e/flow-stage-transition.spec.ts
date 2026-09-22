/**
 * Pipeline: kandydat w rekrutacji → screening → konflikt wersji → odrzucenie.
 *
 * `@stack` — zakłada własnego klienta, rekrutację i kandydata. Dawna wersja
 * celowała w `SAMPLE_JOB_ID = 1`, wołała nieistniejące endpointy
 * (`POST /api/jobs/{id}/candidates`, `POST /api/candidate-stages`), pomijała
 * się przy każdym błędzie i akceptowała 401/403/404/422 jako sukces.
 */
import { test, expect, expectStatus, jsonOf } from "./helpers/api";
import { createCandidate, createClient, createJob } from "./helpers/entities";

interface StageResponse {
  candidate_id: number;
  stage: string;
  process_state_version: number;
}

interface KanbanView {
  columns: Array<{ stage: string; items: Array<{ candidate_id: number }> }>;
}

function stageOf(kanban: KanbanView, candidateId: number): string | undefined {
  return kanban.columns.find((column) =>
    column.items.some((item) => item.candidate_id === candidateId)
  )?.stage;
}

test.describe("Pipeline rekrutacji @stack", () => {
  test("ruch na screening, odmowa przy nieaktualnej wersji i odrzucenie z powodem", async ({
    admin,
    page,
  }) => {
    const client = await createClient(admin.api);
    const job = await createJob(admin.api, client.id);
    const candidate = await createCandidate(admin.api);
    const fullName = `${candidate.name} ${candidate.lastname}`;

    const screening = await jsonOf<StageResponse>(
      await admin.api.post("/api/pipeline/move", {
        data: { candidate_id: candidate.id, job_id: job.id, stage: "screening" },
      }),
      200,
      "ruch na screening"
    );
    expect(screening.stage).toBe("screening");

    const kanbanAfterMove = await jsonOf<KanbanView>(
      await admin.api.get(`/api/pipeline/kanban/${job.id}`),
      200,
      "kanban po ruchu"
    );
    expect(stageOf(kanbanAfterMove, candidate.id)).toBe("screening");

    // Osoba jest na Tablicy także po przeładowaniu rekrutacji. Tryb „Tabela"
    // usunięty 22.09.2026 — rekrutacja to Tablica, a stare adresy
    // (`?tab=people`, `?tab=pipeline`) też na nią prowadzą.
    await page.goto(`/jobs/${job.id}`);
    await page.reload();
    const board = page.getByTestId("pipeline-board");
    await expect(board.getByRole("link", { name: fullName })).toBeVisible();
    await page.goto(`/jobs/${job.id}?tab=pipeline`);
    await expect(page.getByTestId("pipeline-board")).toBeVisible();
    await expect(page).not.toHaveURL(/tab=pipeline/);

    // Ruch z nieaktualną wersją procesu jest odrzucany bez zapisu (F05).
    const stale = await admin.api.post("/api/pipeline/move", {
      data: {
        candidate_id: candidate.id,
        job_id: job.id,
        stage: "prep_call",
        expected_state_version: screening.process_state_version + 1,
      },
    });
    await expectStatus(stale, 409, "ruch z nieaktualną wersją");
    expect((await stale.json()).detail.code).toBe("PIPELINE_VERSION_CONFLICT");
    // …i naprawdę nic nie zapisał: osoba dalej stoi na screeningu.
    const kanbanAfterStale = await jsonOf<KanbanView>(
      await admin.api.get(`/api/pipeline/kanban/${job.id}`),
      200,
      "kanban po odmowie ruchu"
    );
    expect(stageOf(kanbanAfterStale, candidate.id)).toBe("screening");

    const template = await jsonOf<{
      rejection_reasons: Array<{ id: number; category: string }>;
    }>(
      await admin.api.get(`/api/pipeline-templates/${job.pipeline_template_id}`),
      200,
      "szablon pipeline'u"
    );
    const reason = template.rejection_reasons.find((item) => item.category === "rejected");
    expect(reason, "szablon domyślny ma powód odrzucenia").toBeDefined();

    const rejected = await jsonOf<StageResponse>(
      await admin.api.post("/api/pipeline/move", {
        data: {
          candidate_id: candidate.id,
          job_id: job.id,
          stage: "rejected",
          rejection_reason_id: reason!.id,
          expected_state_version: screening.process_state_version,
        },
      }),
      200,
      "odrzucenie"
    );
    expect(rejected.stage).toBe("rejected");

    const kanbanAfterReject = await jsonOf<KanbanView>(
      await admin.api.get(`/api/pipeline/kanban/${job.id}`),
      200,
      "kanban po odrzuceniu"
    );
    expect(stageOf(kanbanAfterReject, candidate.id)).toBe("rejected");
  });

  test("ruch etapu z panelu osoby na Tablicy: główna akcja doku", async ({ admin, page }) => {
    const client = await createClient(admin.api);
    const job = await createJob(admin.api, client.id);
    const candidate = await createCandidate(admin.api);
    const fullName = `${candidate.name} ${candidate.lastname}`;
    await jsonOf<StageResponse>(
      await admin.api.post("/api/pipeline/move", {
        data: { candidate_id: candidate.id, job_id: job.id, stage: "new" },
      }),
      200,
      "dodanie do rekrutacji",
    );

    // `?candidate=` otwiera dok tej osoby na Tablicy (jak link z powiadomienia).
    await page.goto(`/jobs/${job.id}?candidate=${candidate.id}`);
    const panel = page.getByRole("complementary", { name: "Karta kandydata" });
    await expect(panel.getByText(fullName)).toBeVisible();

    // Ten sam `usePipelineMove` co przeciąganie — ruch na „Screening" nie otwiera okna.
    await panel.getByRole("button", { name: /Przenieś na etap: Screening/ }).click();
    await expect
      .poll(async () =>
        stageOf(
          await jsonOf<KanbanView>(
            await admin.api.get(`/api/pipeline/kanban/${job.id}`),
            200,
            "kanban po ruchu z doku",
          ),
          candidate.id,
        ),
      )
      .toBe("screening");
    // Dok zostaje otwarty na tej samej osobie.
    await expect(panel.getByText(fullName)).toBeVisible();
  });

  test("ruch etapu na TABLICY: przeciągnięcie karty (klawiatura)", async ({ admin, page }) => {
    const client = await createClient(admin.api);
    const job = await createJob(admin.api, client.id);
    const candidate = await createCandidate(admin.api);
    const fullName = `${candidate.name} ${candidate.lastname}`;
    await jsonOf<StageResponse>(
      await admin.api.post("/api/pipeline/move", {
        data: { candidate_id: candidate.id, job_id: job.id, stage: "new" },
      }),
      200,
      "dodanie do rekrutacji",
    );
    const before = stageOf(
      await jsonOf<KanbanView>(
        await admin.api.get(`/api/pipeline/kanban/${job.id}`),
        200,
        "kanban przed przeciągnięciem",
      ),
      candidate.id,
    );

    await page.goto(`/jobs/${job.id}?tab=board`);
    const board = page.getByTestId("pipeline-board");
    const card = board
      .locator("[data-rfd-draggable-id]")
      .filter({ has: page.getByRole("link", { name: fullName }) })
      .first();
    await expect(card).toBeVisible();
    // Puste kolumny są domyślnie ukryte (store/ui.ts hideEmptyKanbanColumns),
    // a świeża rekrutacja ma tylko jedną niepustą — bez celu strzałka nic nie robi.
    // Przełącznik „Ukryj puste kolumny" (aria-pressed = puste ukryte) wyłączamy
    // jawnie; do 22.09.2026 nazywał się „Kolumny: pokaż puste" i test po
    // zmianie nazwy nic nie klikał, więc karta nie miała dokąd pojechać.
    // Od 22.09.2026 przełącznik siedzi w „Filtry ▾" (makieta 2).
    await page.getByRole("button", { name: /^Filtry/ }).click();
    const hideEmpty = page.getByRole("button", { name: "Ukryj puste kolumny" });
    await expect(hideEmpty).toBeVisible();
    if ((await hideEmpty.getAttribute("aria-pressed")) === "true") await hideEmpty.click();
    await expect(hideEmpty).toHaveAttribute("aria-pressed", "false");
    // Przeciąganie klawiaturą (@hello-pangea/dnd): Spacja podnosi kartę,
    // strzałka przenosi ją do sąsiedniej kolumny, Spacja upuszcza.
    await card.focus();
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Space");

    await expect
      .poll(async () =>
        stageOf(
          await jsonOf<KanbanView>(
            await admin.api.get(`/api/pipeline/kanban/${job.id}`),
            200,
            "kanban po przeciągnięciu",
          ),
          candidate.id,
        ),
      )
      .not.toBe(before);
  });

  test("stawka ponad budżet nie tworzy „Pending” — karta jest aktywna z odznaką", async ({
    admin,
  }) => {
    // Decyzja 17.09.2026: bramka akceptacji stawki ponad budżet wyłączona.
    // Ruch przechodzi, stawka zostaje zapisana, a przekroczenie budżetu jest
    // wyłącznie informacją (`budget_exceeded`) — nikt nie musi niczego akceptować.
    const client = await createClient(admin.api);
    const job = await createJob(admin.api, client.id, { salary_min: 8000, salary_max: 10000 });
    const candidate = await createCandidate(admin.api);

    const verified = await jsonOf<StageResponse & {
      verification_status: string;
      budget_exceeded: boolean;
    }>(
      await admin.api.post("/api/pipeline/move", {
        data: {
          candidate_id: candidate.id,
          job_id: job.id,
          stage: "verified",
          expected_rate_value: 30000,
          expected_rate_unit: "monthly",
          expected_rate_currency: "PLN",
        },
      }),
      200,
      "ruch na Zweryfikowany ze stawką ponad budżet"
    );
    expect(verified.verification_status).toBe("active");
    expect(verified.budget_exceeded).toBe(true);

    // Trasy kolejki akceptacji nie istnieją — bramka „Oczekuje" została
    // usunięta razem ze swoim kodem (17.09.2026).
    const queue = await admin.api.get("/api/pipeline/pending-verifications");
    await expectStatus(queue, 404, "kolejka akceptacji nie istnieje");
  });

  test("rekruter spoza zespołu rekrutacji nie przesunie kandydata", async ({ admin, apiAs }) => {
    const client = await createClient(admin.api);
    const job = await createJob(admin.api, client.id);
    const candidate = await createCandidate(admin.api);
    const recruiter = await apiAs("recruiter");

    const move = await recruiter.api.post("/api/pipeline/move", {
      data: { candidate_id: candidate.id, job_id: job.id, stage: "screening" },
    });
    await expectStatus(move, 403, "ruch rekrutera spoza zespołu");

    const kanban = await jsonOf<KanbanView>(
      await admin.api.get(`/api/pipeline/kanban/${job.id}`),
      200,
      "kanban po odmowie"
    );
    expect(stageOf(kanban, candidate.id)).toBeUndefined();
  });
});
