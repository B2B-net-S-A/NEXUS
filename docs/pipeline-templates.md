# Pipeline Templates & Custom Stages

Nexus pipelines are **custom per job** — what Traffit calls "recruitment processes". This replaces the legacy hardcoded enum with a flexible `PipelineTemplate → PipelineStageDef` schema while keeping backward compatibility with the 12 legacy stages.

## Concepts

| Entity | Purpose |
|--------|---------|
| **PipelineTemplate** | A named preset of stages (e.g. "Default B2B", "Senior IT Fast-track", "Sales Project"). One template = one reusable process. |
| **PipelineStageDef** | One stage within a template. Has `name`, `order`, `category` (internal/external/terminal), optional `is_terminal` + `terminal_type` (hired/rejected/withdrawn), SLA `sla_max_days`, and an optional `scorecard_schema`. |
| **RejectionReason** | Per-template list of reasons users must pick when moving to a terminal stage (rejected/withdrawn). |
| **legacy_enum_value** | Each StageDef optionally maps to one of the 12 legacy `PipelineStage` enum values for reporting backward-compat. |

## UI

- `/settings/pipeline-templates` — list, clone, archive templates; drag-and-drop reorder stages; add/remove stages and rejection reasons.
- `AddJobModal` / `EditJobModal` — dropdown "Szablon procesu rekrutacyjnego" — pick which template the job uses.
- `KanbanBoard` — dynamically renders columns from the assigned template. Moving a candidate to a terminal stage prompts for a rejection reason. Moving to a non-terminal stage with a defined `scorecard_schema` opens the scorecard modal.

## Scorecard Schema Format

Stored as JSONB in `pipeline_stage_defs.scorecard_schema`. Example:

```json
{
  "title": "Technical Screening",
  "questions": [
    {
      "id": "tech_skills",
      "label": "Umiejętności techniczne",
      "type": "rating",
      "required": true
    },
    {
      "id": "communication",
      "label": "Komunikacja",
      "type": "rating"
    },
    {
      "id": "english",
      "label": "Poziom angielskiego",
      "type": "select",
      "options": ["A1", "A2", "B1", "B2", "C1", "C2"]
    },
    {
      "id": "notes",
      "label": "Dodatkowe uwagi",
      "type": "text",
      "description": "Co warto zapamiętać z rozmowy?"
    },
    {
      "id": "ready_for_client",
      "label": "Gotowy na rozmowę u klienta?",
      "type": "checkbox"
    }
  ]
}
```

Supported question types: `rating` (1-5 stars), `text` (multiline), `checkbox` (boolean), `select` (enum from `options`).

## Backward Compatibility

- The `candidate_stages.stage` enum column remains populated on every move. When a StageDef has `legacy_enum_value` set, that value is written; otherwise `PipelineStage.new` is used as a placeholder.
- All existing API routes (`/api/pipeline/move`, `/api/pipeline/kanban`, `/api/pipeline/overview`) accept either `stage` (legacy enum) or `stage_def_id` (new FK). Send both for safe forward/backward compat.
- Existing jobs without a `pipeline_template_id` fall back to the "default" template — seed-created on first migration.

## Creating a Custom Template — Example

```bash
# 1. Clone the default template
curl -X POST /api/pipeline-templates/1/clone?new_name=Senior%20Fast-track \
  -H "Authorization: Bearer $TOKEN"
# → { "id": 5, ... }

# 2. Remove intermediate stages, keep only screening → interview → hired/rejected
curl -X DELETE /api/pipeline-templates/5/stages/{stage_id}

# 3. Add a stage with scorecard
curl -X POST /api/pipeline-templates/5/stages \
  -H "Content-Type: application/json" \
  -d '{"name":"Tech interview","order":2,"category":"internal"}'

# 4. Attach scorecard schema (PUT on stage endpoint)
curl -X PUT /api/pipeline-stages/{stage_def_id}/scorecard \
  -d '{"title":"Tech interview","questions":[...]}'

# 5. Assign to job
curl -X POST /api/pipeline-templates/assign-to-job/123 \
  -d '{"template_id":5}'
```

## Reporting

The SLA alerts endpoint (`/api/pipeline/overview-sla`) flags candidate stages where `days_in_stage > sla_max_days` for the active StageDef — useful for dashboard widgets to nudge recruiters.

The funnel report (`/api/reports/funnel?template_id=...`) produces conversion rates per StageDef — compare templates by effectiveness.

## Migration Path (40k Traffit CVs)

When importing Traffit data:

1. Create a template matching the source process (e.g. "Traffit import — dev teams").
2. Map Traffit stages → StageDef via `legacy_enum_value` where possible.
3. Run the import loop — `POST /api/candidates` for each CV, then `POST /api/pipeline/move` with `stage_def_id` to place them in the correct stage.
4. Dedup is automatic via `find_candidate_duplicates()` — a match score ≥ 0.9 warns the importer.

See [`CHANGELOG.md`](../CHANGELOG.md) for the phase-by-phase rollout of the template system.
