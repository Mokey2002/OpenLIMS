# One sample, five users / Una muestra, cinco usuarios

The central sample is **DEMO-360-001**, in project **DEMO-360**. All results are
synthetic training fixtures. One child aliquot demonstrates lineage and a reference
sequence enables comparison; these are supporting records, not unrelated demos.

## Create it

After installing this version, run on the intended demo server:

```sh
docker compose -f deploy/docker-compose.yml exec api python manage.py seed_demo --connected-only
```

This requires existing active accounts `director`, `peter`, `maria`, `michael` and
`viewer` with their usual demo roles. It does not create accounts, change passwords,
send email, run instruments or change global feature flags. New accounts created by
the full `seed_demo` have no usable password; use the existing account setup flow.
Do not rerun the full seed just to create this sample on an established installation.

The command prints the sample/project URLs and adds an in-app notification for all
five users. Enable Notebook/Registry and other desired modules in Settings if hidden.
If this demo already exists, rerunning leaves user edits and membership untouched.
Conflicting reserved IDs fail and roll back instead of overwriting existing data.

## Walkthrough

| User | What to demonstrate |
| --- | --- |
| director | Open project DEMO-360, review membership, pipeline/experiment templates and the SOP. The draft service request is available for a separate request demonstration. |
| peter | Open DEMO-360-001. Extraction is complete with concentration 43 ng/uL and synthetic import provenance. Open PCR, add STRING result `amplification_status` = `PASS`, then mark the work item COMPLETED. |
| maria | Open the completed Sequence QC work item. Michael entered `quality_score` = 98. Approve QC with a review reason. This is distinct from marking work complete. |
| michael | Explore the linked sequence, registry revision, simulated alignment and MS summary. After Peter completes PCR and Maria approves QC, open the newly activated Interpretation work, assign it to yourself, add STRING `interpretation` = `PASS`, and complete it. |
| viewer | Read the same sample, results, experiment, sequences and files; download the synthetic PDF. Sample changes and QC approval are unavailable. |

In the Notebook, open **DEMO-360 live team walkthrough**. Peter fills the required
`observations` field and completes **Document results**. Maria completes **Review
interpretation** with `accepted = true`. Complete the experiment, then demonstrate
review/sign-off and locking with director. Export the real notebook PDF after review.
The attached initial PDF is clearly marked as an unapproved synthetic summary.

## Connected capabilities

| Area | Fixture or action |
| --- | --- |
| Sample tracking | Main sample, custom fields, storage box, barcode, custody event and child aliquot. |
| Workflows | Completed extraction, active PCR, pending QC and blocked interpretation with dependencies. |
| Results/imports | Measured fields, actor attribution, linked synthetic import and CSV source file. |
| QC | Michael's completed work awaits Maria's independent approval. |
| Inventory | Reagent lot, location, container and project reservation. |
| Molecular biology/Registry | Sample-linked sequence, immutable revision and a registered-material draft linked to that revision. |
| Alignment/MS | Explicitly simulated results for visual inspection; no external processing claimed. |
| BLAST | Reference FASTA, NEW database and unexecuted query. Build the database through BLAST, then run a new search if BLAST binaries are installed. |
| Notebook | Reusable template, assigned required steps, sample/material/procedure links, revision history and team access. |
| Requests | Draft sample-linked sequencing request. Approving it may start a separate pipeline; the sample already has a walkthrough run. |
| Files/reports | CSV, FASTA, walkthrough text and valid PDF attached directly to the sample. |
| Collaboration/audit | All five project members, role-specific notifications, project post and a synthetic-setup audit marker. |
| Assistant | Ask about DEMO-360-001 using the configured assistant; answers/actions depend on the enabled provider and supported operations. |

This scenario demonstrates the connected scientific workflow. It does **not** claim
to exercise every administrative feature: backups, upgrades, user invitations,
migration rollback, real instrument ingestion and provider setup require separate
demonstrations. No live deployment is changed just by adding this command to GitHub.

## Español

Ejecuta el comando anterior en el servidor de demostración y busca **DEMO-360-001**.
Peter completa PCR (`amplification_status = PASS`); Maria aprueba el trabajo de QC
de Michael; Michael termina interpretación (`interpretation = PASS`). Director
revisa la bitácora y viewer consulta los datos sin editarlos. La bitácora tiene dos
pasos adicionales: observaciones de Peter y aceptación de Maria. Todos los datos
son ficticios; volver a ejecutar el comando conserva las modificaciones del equipo.
