# Structured JSON for factual review

The completed synthetic run `34382090238-1` on runtime `4dd11828` passed 1/4 cases. Both Polish controls and the English negative control returned `invalid_json`; the English positive control passed. All four calls were metered (estimated USD 0.013773) and task cleanup was confirmed. This is a protocol failure diagnosis, not a full-CV quality score.

The verifier now sends its response schema through `output_config.format` on the existing shared, metered provider path. The installed Anthropic SDK 0.125.0 supports this API and its schema transformer. Provider grammar omits unsupported bounds; the original local Pydantic bounds, complete claim coverage, exact evidence and semantic rejection remain mandatory. Ordinary provider calls omit the option. The verifier version becomes 2, and results/receipts preserve a validated schema fingerprint alongside the unchanged prompt fingerprint. Old receipts remain readable.

Validation: 76 focused provider/verifier/transport/recovery tests, Ruff and diff check. Checks cover schema forwarding, unchanged plain calls, continued local rejection of oversized reviews, schema-fingerprint round trip and rejection of arbitrary content in that field. Actual-model success, latency/cost and primary/fallback acceptance remain to be measured after deployment. This change does not activate the final gate in recruitment generation or merge draft #1444.

API basis: [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). A schema constrains response syntax; it does not establish factual correctness. Refusals and truncation remain failures.
