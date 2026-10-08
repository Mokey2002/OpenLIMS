# Ask what comes next

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
