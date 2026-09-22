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

    // Osoba jest w tabeli (widok domyślny) także po przeładowaniu rekrutacji…
    await page.goto(`/jobs/${job.id}`);
    await page.reload();
    const table = page.getByRole("grid", { name: "Osoby w rekrutacji" });
    await expect(table.getByText(fullName)).toBeVisible();
    // …i na tablicy (przełącznik „Tablica"). Stary adres `?tab=pipeline`
    // nadal prowadzi do rekrutacji — ląduje na tabeli.
    await page.getByTestId("view-board").click();
    const board = page.getByTestId("pipeline-board");
    await expect(board.getByRole("link", { name: fullName })).toBeVisible();
    await page.goto(`/jobs/${job.id}?tab=pipeline`);
    await expect(page.getByRole("grid", { name: "Osoby w rekrutacji" })).toBeVisible();
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

  test("ruch etapu z TABELI: panel osoby → wybór etapu", async ({ admin, page }) => {
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

    await page.goto(`/jobs/${job.id}`);
    const table = page.getByRole("grid", { name: "Osoby w rekrutacji" });
    // Klik w lewą część komórki nazwiska — przy wąskim oknie reszta pola
    // bywa przykryta przez sąsiednią kolumnę.
    await table.getByText(fullName).click({ position: { x: 4, y: 4 } });
    const panel = page.getByRole("complementary", { name: "Wybrana osoba" });
    await expect(panel.getByText(fullName)).toBeVisible();

    // Ten sam `usePipelineMove` co tablica — ruch na „Screening" nie otwiera okna.
    await panel.getByLabel("Etap").selectOption({ label: "Screening" });
    await expect
      .poll(async () =>
        stageOf(
          await jsonOf<KanbanView>(
            await admin.api.get(`/api/pipeline/kanban/${job.id}`),
            200,
            "kanban po ruchu z tabeli",
          ),
          candidate.id,
        ),
      )
      .toBe("screening");
    // Panel zostaje otwarty na tej samej osobie i pokazuje nowy etap.
    await expect(panel.getByLabel("Etap")).toHaveValue(/.+/);
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
    const showEmpty = page.getByRole("button", { name: /Kolumny: pokaż puste/ });
    if (await showEmpty.isVisible()) await showEmpty.click();
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
