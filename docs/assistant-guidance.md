# Ask what comes next

## Conversational follow-ups (v0.39.1)

Example conversation:

1. `What's holding this up?` → asks for a sample ID.
2. `DEMO-360-001` → reads its current workflow and missing requirements.
3. `What about step 2?` → narrows guidance to that numbered step, if unambiguous.
4. `Who is assigned?` → rereads that step's recorded work assignee. An assignee is not necessarily a QC reviewer; the assistant does not invent a reviewer.
5. `What next?` → returns to the sample's full workflow.
6. `Start over` → clears the sample conversation context.

Spanish: `¿Qué falta?` → `DEMO-360-001` → `¿Y el paso 2?` →
`¿Quién está asignado?` → `Empezar de nuevo`.

An explicit sample ID overrides the previous one and resets step focus. If a step
number occurs in multiple retained runs, open the linked sample to choose the run;
the assistant does not guess. Topic changes are not automatically treated as sample
follow-ups. Supported action requests continue through their existing routes.

This is a bounded rules-based conversation handler, not nearest-match search or
unrestricted language understanding. It recognizes supported question patterns,
retains a sample/step reference in chat context, checks access, and generates answers
from fresh records. It never fuzzy-matches sample identifiers. Other assistant
routes can optionally use OpenAI/Ollama for intent classification and tool-result
summarization; this workflow guidance bypasses external models. It does not add
cross-record semantic search, autonomous execution, or persistent chat memory.

## Supported workflow questions

In Assistant, try:

- `What next for sample DEMO-360-001?`
- `Why is sample DEMO-360-001 blocked?`
- `Explain the pipeline for sample DEMO-360-001`
- `¿Qué sigue para muestra DEMO-360-001?`
- `¿Por qué está bloqueada muestra DEMO-360-001?`

After a successful answer, `What next?` retains that sample and rereads current
records. An explicit new sample ID takes precedence over previous context. The
assistant asks for a single exact identifier when absent or ambiguous; it never
falls back to a different sample when the requested record is inaccessible.

Answers show sample status, storage, the latest five pipeline runs, up to 50 steps
per run, work assignment, unmet dependencies and missing/invalid required result
or form fields. They distinguish completing work from approving QC. Conditions
that need further inspection link back to the sample rather than inventing a
reason. Completed/cancelled runs are historical and do not propose new work.

Open the linked sample to perform actions. Guidance is read-only and generates no
action proposal. Other assistant operations retain their existing confirmation
flow. Read-only users can inspect guidance; that does not grant editing or QC
permissions. Every request—including a follow-up—checks sample access again.

The API includes `sample_guidance.as_of` and structured step evidence. Core guidance
is generated from application records and is not rewritten or sent to an external
model. It works with Rules mode and when OpenAI/Ollama is configured. It is a bounded
workflow helper, not unrestricted scientific reasoning or autonomous execution.
The normal assistant interaction telemetry still records the request metadata.

## Español

Pregunta `¿Qué sigue para muestra DEMO-360-001?`. El asistente indica campos
obligatorios pendientes, pasos anteriores sin terminar y revisión de QC necesaria.
Consulta los registros de nuevo en cada pregunta. Abre el enlace de la muestra para
trabajar; la respuesta no cambia resultados, estados ni aprobaciones.
