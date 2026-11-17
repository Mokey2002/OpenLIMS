# Barcode sample accessioning (v0.78.6)

Open **Receive → Receive sample**, or use the receiving link on Samples or an individual sample record. USB scanners must operate as keyboards and send Enter after each scan. Manual entry and Enter work too. A scan only looks up a record; it never registers, receives, or confirms a sample automatically.

## Receive a tube

1. Scan the tube into **Tube barcode**. An existing accessible code opens the sample in the receiving workspace, with a link to its full record. A new code opens registration. An inaccessible or ambiguous code returns a neutral message and cannot start registration.
2. For a new tube, choose a receiving project you belong to and a sample type. When the lab has published sample forms, choose a published type and complete its required fields and units. Without published forms, GENERAL is available. The barcode becomes the sample ID; registration is recorded separately from physical receipt.
3. Check the selected sample and enter a receipt note of at least 10 characters, then choose **Record receipt**. The server records the receiving account, timestamp, scanned code and reason in a custody event and audit event. It does not automatically change sample status, custodian, or location.
4. Choose a label size and **Download printable label**. Print the Code 128 PDF at **actual size / 100%**, then attach it to this tube. Available page sizes are 100 × 50 mm, 75 × 35 mm and A4. Codes or sample IDs that do not fit a small label require a larger size. The PDF contains the readable sample ID and barcode text. Existing labels can also be used if their code resolves unambiguously to this sample.
5. Scan the attached label into **Scan attached label** and press Enter. A matching scan records the confirming account and server time. A wrong label leaves both records unchanged and asks for correction. After confirmation, focus returns to the top scanner field for the next tube.

Existing receipt and verification details reappear on lookup. Use the existing Barcode Labels custody actions for later check-in, transfer, or storage moves. Repeated receipt and confirmation requests return the original records rather than duplicating them. If a request is interrupted, scan again to inspect the saved state before retrying; never invent another sample ID to work around an uncertain response.

## Identifiers and permissions

- New barcodes use 1–64 printable ASCII characters after trimming surrounding whitespace. The `OPENLIMS-SAMPLE-` namespace is reserved for existing generated labels. Sample IDs are unique without regard to case, including concurrent registration attempts.
- Registered barcode aliases are retained in the existing barcode registry. Printed aliases continue resolving if the readable sample ID is subsequently corrected through existing sample controls.
- Active administrators and technicians can register, receive, print, and confirm only within the applicable sample permissions. Receiving registration requires membership in the selected project, consistent with existing sample visibility. Linked-project visibility alone does not grant modification rights.
- Read-only users can look up accessible samples, but cannot register, receive, generate labels, or confirm them. Private records are not exposed through barcode lookup.
- Archived and cancelled samples cannot be received or label-confirmed. Looking up a sample does not advance its workflow or approve results.
- Existing custody RECEIVE events retain their original actor and time. The new workflow can attach label confirmation to an existing receipt without manufacturing another physical receipt.

## Deployment and audit

Run the normal Django migrations before using this screen. Migration `samples.0017_sampleaccession` adds one accession record per sample, linked to the existing receipt event, with separate label-verification actor/time. No package dependencies or credentials are added.

Registration uses the existing CREATED audit event. New physical receipt records SAMPLE_RECEIVED and a custody RECEIVE event; label verification records SAMPLE_LABEL_VERIFIED. PDF generation records SAMPLE_LABEL_GENERATED. Generating a PDF does **not** prove that a printer produced it or that it was attached; the subsequent scan is the explicit confirmation step. This workflow does not involve the assistant.

Software checks cover required fields, permission boundaries, repeated and concurrent requests, legacy receipts, stable barcode aliases, mismatched labels and PDF generation. Browser tests simulate scanner keyboard input. Validate your actual scanner, printer, label stock and scan reliability before routine laboratory use; direct printer-driver integration is not included.
