# Reusable experiment workflows / Flujos de experimentos reutilizables

## Configure once

1. Open **Laboratory Notebook → Templates** in a notebook you can edit.
2. Create a template, or choose **Edit structure** on an existing template.
3. In **Reusable experiment workflow**, choose **Add workflow step**. Name the
   step and enter its instructions and completion criteria. Move steps up/down
   to set execution order.
4. Add fields with readable labels and unique keys within each step. Choose
   text, number, or yes/no; set required fields, numeric bounds, or an exact
   required value. For example: Concentration (`concentration`, number,
   minimum 10), or Confirmed (`confirmed`, yes/no, required value Yes).
5. Select a default responsible person, or leave it to each experiment. The
   person must be active and have notebook edit access. Assignment does not
   grant access; configure sharing under **Notebooks & sharing** first.
6. Choose **Save structure**, then **Use template** to create an experiment.

## Execute in the experiment

1. Open **Experiment workspace → Workflow**. The first unfinished step is ready;
   later steps remain blocked until their predecessors are complete.
2. If unassigned, select a responsible person, enter an assignment reason, and
   choose **Save assignment**. Editors can manage assignments; the assigned
   person, notebook owner, or administrator can record an assigned step.
3. Enter results in the labeled fields and choose **Save progress**. Draft
   values can be outside acceptance limits, so actual measurements are retained.
4. Before choosing **Complete step**, fill required fields, meet configured
   limits, enter a completion note, and confirm the stated criteria. Instructions
   and narrative criteria require the operator's confirmation; numeric bounds
   and exact values are checked by the server.
5. Complete the next step on the same screen. The next assignee receives a
   notification when their step becomes ready. No trip to Work Queue is needed.
6. When all steps are finished, use the experiment's **Complete** action to
   submit it for review. Review and locking remain separate actions.

Save progress before switching records or reloading. A conflicting save returns
an error and preserves the currently entered form values; compare them after
reloading before retrying. Completed steps are immutable. Clone the experiment
for a repeat or correction; the clone keeps the workflow definition and resets
all recorded values, completion notes, and completions. Revoked default assignees
are left unassigned on clones.

## What is preserved

- Each experiment snapshots its step definitions. Editing a template changes
  future experiments only. Existing experiments without a workflow stay unchanged.
- The experiment template cannot be switched after creation.
- Assignment changes, progress saves, and completion are audited with actor,
  before/after values, and reason/note. Saved step versions prevent stale writes.
- Review records include a workflow checksum as well as the content checksum;
  locking verifies both for experiments with workflows. PDF exports include step
  criteria, values, responsible people, completions, and the workflow checksum.
- Responsible people are included among the experiment's assignees so it appears
  in their experiment work list. Reassigning a step does not remove a person's
  existing experiment-level assignment.

These are ordered **notebook experiment** workflows. Existing sample pipelines
remain separate. This release does not connect sample pipeline execution to
notebook workflow execution, add branching to experiment workflows, or run lab
instruments automatically.

## Configurar y ejecutar en español

1. Abre **Laboratory Notebook → Templates** y crea una plantilla o elige
   **Editar estructura**.
2. En **Flujo de experimento reutilizable**, añade pasos, instrucciones y
   criterios. Ordénalos con **Subir/Bajar**.
3. Añade campos obligatorios de texto, número o sí/no. Configura límites o valores
   exigidos cuando corresponda. El responsable debe tener acceso de edición.
4. Guarda la estructura y crea un experimento con **Use template**.
5. Abre **Flujo de trabajo** en el experimento. Asigna al responsable, con un
   motivo, si aún no tiene uno.
6. Introduce mediciones y usa **Guardar progreso**. Para **Completar paso**, cumple
   los criterios, escribe una nota y confirma la finalización. Se desbloquea el
   siguiente paso; no necesitas ir a Work Queue.
7. Al terminar todos los pasos, completa el experimento y envíalo a revisión.

Guarda antes de cambiar de registro. Las plantillas modificadas solo afectan a
experimentos nuevos. Los pasos completados no se sobrescriben: clona el
experimento para repetir o corregir el flujo. Las asignaciones no conceden
permisos. Los flujos de muestras existentes siguen siendo independientes.

## Upgrade and validation

Run the normal backend migrations before serving the new frontend:

```bash
python manage.py migrate
```

Migration `notebook.0002` adds workflow definitions, execution steps, and the
review workflow checksum. Existing records start with no workflow. No data is
backfilled or sample status changed.

```bash
# backend, PostgreSQL configured
pytest notebook/tests
REQUIRE_POSTGRES_TESTS=1 pytest notebook/tests/test_concurrency.py
# frontend, development server running
node --test scripts/*.test.mjs
npm run build
cd e2e
npm test -- tests/experiment-workflows.spec.js tests/daily-workflow.spec.js tests/notebook-links.spec.js
```

Browser tests use controlled API responses. Backend tests cover real persistence,
permissions, criteria, stale saves, template isolation, cloning, rollback, and
completion/review. The PostgreSQL concurrency gate checks two competing workflow
saves; SQLite deliberately skips these row-locking tests.
