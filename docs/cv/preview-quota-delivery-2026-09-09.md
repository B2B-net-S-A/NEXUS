# CV-09 / CV-18: one admission for both preview variants

The client-rule trial previously admitted two single-unit operations sequentially,
although metering commits independently of the business transaction. With one
unit remaining, the second refusal left the first charge behind without a preview.
The handler now requests `units=2` once and passes that operation to the worker.
Two focused service tests cover insufficient and exactly sufficient capacity;
the hosted API lifecycle additionally checks 503 without a charge or generation,
then successful generation of both variants with one two-unit admission.
This does not establish global concurrent quota serialization or refund behavior
for provider failures, and does not complete durable jobs or same-facts previews.
