# Assistant v0.71 — Natural conversation follow-ups

The v0.70 conversation review found that several ordinary follow-ups fell through to an unknown response and lost the active read scope. Concept explanations could also be mistaken for sample comparisons. This release fixes those cases in both chat surfaces without requiring a language model.

## Supported conversations

| Start | Follow-up | Behavior |
| --- | --- | --- |
| What should I work on today? | Why that one? | Rereads current priorities and explains their recorded reasons. |
| Daily work | Show me the unassigned work instead → Only project ALPHA → Only the overdue ones | Changes the owner/project/focus while preserving the remaining filters. |
| Daily work with filters | Show me my tasks again | Returns to the current user's work, retaining the project and focus. |
| Summarize project ALPHA | Which samples are overdue? → Only the unassigned ones | Opens current work-item priorities for that project's accessible samples; a sample may have multiple work items. |
| Investigate BETA's QC failures | Which ones failed? → Why? → Group by instrument | Shows actual flagged evidence and recorded reasons in the same project/window. Missing reasons stay explicitly unknown. |
| Project investigation | Actually use ALPHA | Changes the exact project and preserves other filters. An earlier export proposal is not repeated. |
| Project investigation | Export as CSV | Prepares a new export preview for explicit confirmation. |
| Show me sample S-100 | What do I need to do next? → What's blocking it? | Resolves one accessible sample and reads current workflow requirements. Multiple samples still require clarification. |
| Sample explanation | No, I meant S-101 → What about its QC? | Corrects the exact sample and shows its current evidence. Pronouns are not treated as replacement identifiers. |
| Explain the difference between a sample and a work item | Can you give me a simple example? | Explains application concepts with a clearly labeled illustrative example, without searching records. |
| Project overview | Actually, I meant BETA → Thanks, can you show me its samples? | Corrects the project and reads its accessible sample list. |
| Recent named project | Go back to ALPHA | Reopens an accessible named topic from the user's signed read-topic history. |

Informal help, “how are you?”, “whats going on with project ALPHA”, and “can u show me overdue samples in ALPHA” also work. New documented phrases are in English; existing Spanish routes are retained. This is bounded interpretation of supported operations, not unrestricted understanding of every paraphrase.

## Scope, permissions and confirmations

- Unknown wording retains only a validated read scope. Daily and investigation views fetch current data again; sample/project references are rechecked for access. Malformed, missing or revoked scopes are cleared rather than keeping a protected panel visible.
- A supported new topic replaces the prior active scope. “Start over”, “never mind” and “cancel” close the conversation topic. Existing action previews have their own Cancel button; a conversational reset does not silently cancel, confirm or reverse database actions.
- Follow-ups do not replay actions or generate artifacts. Assignment, completion, QC review and report exports still use the existing preview/confirmation path.
- Daily explanations show at most five displayed work reasons. Investigation explanations show at most ten flagged results and five work gates, with excerpt limits disclosed. Existing query caps, permissions and separate check/review/gate semantics remain authoritative.
- Project-overview follow-ups about overdue/unassigned/blocked work use the daily-work engine and disclose its work-item scope and scan limits. Existing explicit pipeline queries retain their own dependency and step semantics.
- Public concept explanations store a small concept key list, separate from lab evidence. Saved concept conversations restore definitions and example context without replaying lab reads or writes.

## Language model configuration

These corrections work with the rules-based assistant. Open-ended general conversation still requires an enabled, reachable OpenAI or Ollama provider. Provider adapter tests use simulated responses. The development environment used for this release has its provider disabled and no OpenAI key; live-model fluency is not claimed.

## Validation and deployment

Regression coverage includes the original failed conversation examples, multi-turn chains, exact project changes, sample ambiguity, malformed contexts, revoked access, live rereads, saved concept history, no unintended writes, and both provider adapters. A real authenticated HTTP/SSE test exercises daily explanations, unknown-message recovery, QC follow-ups, revocation and concept examples.

Release validation results are recorded in the pull request. Root `VERSION` and the generated footer are **0.71.0**. English and Spanish READMEs contain exactly the v0.71, v0.70 and v0.69 release updates. Rebuild the API and frontend images to apply the release. No database migration, dependency, service or scheduled automation is added.
