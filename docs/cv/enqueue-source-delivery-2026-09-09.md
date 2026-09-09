# Recruitment inputs captured before enqueue

The recruitment generator previously loaded the client rule in its worker and loaded candidate inputs again for the automatic second language. A later edit could therefore change the rule, CV, notes or requirements used by another output from the same request.

The request now captures owned source values and its immutable rule before quota and enqueue. Both language renders reuse those values; requirement maps receive the captured requirement list instead of reading the current job. Missing source files and changed candidate/stage/job/client context are rejected before charging or creating a pending row. Required inputs are checked against the captured source as well.

Validation: 35 focused host-native tests, including actual HTTP admission with controlled persistence (capture-before-charge, unavailable source and changed context), a two-language worker check proving no rule/source reload, and existing source/readiness regressions. Ruff and diff check pass. Hosted CI and production acceptance remain required.

This captures raw sources in worker memory. It does not provide durable restart/retry persistence, explicit user selection of source files, one shared AI-extracted ledger across both languages, or enqueue-time capture for client-rule trial previews. Those remain within CV-08/09/18/20. Depends on the shared source loader and readiness packages included in #1467.
