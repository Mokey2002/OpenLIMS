# OpenLIMS v0.26 Registry and Molecular Biology v2

## Registry types and schemas

Directors configure registry types through `RegistrySchema`. A type can model a
plasmid, oligo, primer, RNA, protein, antibody, cell line, strain, organism,
vector, construct, or a laboratory-specific material. Each schema version is a
separate record identified by the same `code` and an increasing `version`.
Once a schema is referenced by a record, its definition is immutable; directors
create a new schema version instead.

Registry v1 validates the useful JSON Schema subset needed for structured
metadata: object properties, required fields, string/number/integer/boolean/
array/object types, and enumerated values. `matching_fields` selects schema
properties used during duplicate detection.

## Records and immutable history

`RegistryRecord` owns the stable `registry_id` and `public_id`. Metadata changes
create `RegistryRecordVersion` snapshots rather than modifying prior versions.
Each version records the exact schema version, structured data, optional linked
sequence revision, sequence checksum, author, timestamp, and change summary.

Records support:

- aliases and external identifiers;
- owner-only, project, or institution visibility;
- project ownership and tags;
- directed registry relationships (`derived_from`, `contains`, `expresses`,
  `binds`, `component_of`, or a custom relation);
- shared links to samples, sequences, inventory lots, projects, work items,
  results, workflow runs, and attachments.

## Registration lifecycle

The lifecycle is `DRAFT → IN_REVIEW → REGISTERED → RETIRED`. Directors approve
or reject pending registration reviews. Duplicate detection runs when a review
is submitted and again immediately before approval. Every creation, version,
relationship, review, registration, and retirement event uses the v1 common
audit payload and stable public IDs.

## Duplicate detection

The duplicate service checks accessible records by registry ID, case-insensitive
alias, sequence checksum, catalog number, and the fields configured on the
record's schema. The preflight endpoint is:

`POST /api/v1/registry-records/duplicate-check/`

Registration is blocked when unresolved candidates exist.

## Molecular Biology v2

The existing `Sequence` API remains available. It is now the editable current
workspace for an immutable `SequenceRevision` history. A revision captures the
validated sequence, type, topology, checksum, annotations, primers, source
metadata, Registry link, author, and change summary.

Supported molecular operations include:

- strict IUPAC DNA, RNA, and protein alphabet validation;
- linear and circular topology;
- revision comparison and restore-as-new-revision;
- reverse complement, transcription, translation, and six-frame ORF search;
- GC percentage, molecular weight, primer GC and melting temperature;
- common restriction-enzyme site search and linear/circular virtual digest;
- ordered fragment assembly with optional reverse complement and overhangs;
- reusable project-scoped feature definitions;
- FASTA and GenBank import/export through Biopython, preserving GenBank feature
  coordinates, strand, type, label, qualifiers, molecule type, and topology.

Linking an existing sequence revision to a Registry record creates a new linked
immutable revision; it never modifies the original revision.

## Migration toolkit

Registry migrations reuse `MigrationProfile`, `MigrationDataset`,
`MigrationFieldMapping`, `MigrationJob`, immutable preview fingerprints,
conflict policies, and reconciliation rows. CSV profiles and read-only database
datasets can map registry identity, schema, name, project, aliases, catalog
number, lifecycle, tags, structured fields, external identifiers, and sequence.
The commit is rejected if source rows or mappings differ from the reviewed
preview.

## Permissions and feature flag

Registry remains controlled by the instance-wide Registry feature flag.
Directors configure schemas and approve registrations. Technicians/scientists
with project access create and version records. Project members can read project
records; private records remain owner-only. All object resolution, links, and
attachments use the v0.25.1 shared project permission contract.
