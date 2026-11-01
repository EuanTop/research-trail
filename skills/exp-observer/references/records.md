# Record reference

For routine recording, prefer the semantic entry:

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "Is the measurement boundary complete?" --finding "Verification contributes to delivery time"
python3 <skill>/scripts/exp_observer.py event --project ID --question "Is the measurement boundary complete?" --correction "Include verification in delivery time" --after "Verification contributes to delivery time"
```

`event --question TEXT` retains an active question; optional `--reason` supplies context. The question can be a retained ID or exact title from this directory, its ancestor queues or a previously fetched compact context. An unseen title receives a stable identity derived from URL, project and the title with surrounding whitespace removed. Internal whitespace and case remain significant; ambiguous titles require an existing ID. There is no approximate matching or lookup inferred from analysis prose.

One optional `--finding TEXT`, `--correction TEXT` or `--direction TEXT` creates a separate ordinary node with that actual change as its title and conclusion. It is linked to the question by `has_finding`, `has_correction` or `has_direction`; these associations claim no scientific causality. Without containment options, question and event retain the legacy root-level behavior. A question marked `--container` owns its later findings; an explicit `--parent TITLE_OR_ID` nests the question and makes it a container as well. The referenced parent is promoted to a container without changing its research type, in the same atomic batch. Existing questions and earlier findings retain their metadata. Only an explicit `--status` changes question status. `--next-action`, `--pause-reason` and `--resume-when` update the question's `nextAction`, `pauseReason` and `resumeWhen`; omitted fields preserve their existing values. Supplied notes without a change update that question's native analysis. A final substantive finding can update these fields in the same invocation:

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "Is the measurement boundary complete?" --finding "The remaining condition has no measurements yet" --status paused --next-action "Measure that condition" --pause-reason "This round's authorized budget is spent" --resume-when "Further measurement is authorized"
```

As work ends, review only the actual questions you worked on. Resolved questions can be completed; unresolved work no longer advancing can be paused with a next action; real continuing work can remain active. Do not suspend the entire experiment or unrelated questions merely because a turn ends.

`--after ID_OR_EXACT_TITLE` without a change creates a `branches` relationship from that earlier node to the new question. With a change, it states a relationship to an earlier finding: defaults are `related_to` for a finding, `revises` for a correction and `leads_to` for a direction. `--relation supports` or another explicit relation overrides that meaning. Repeated `--evidence ID_OR_EXACT_TITLE` adds `supports` links from captured evidence to this event. Exact titles resolve locally or from retained context; missing or ambiguous optional relationship titles produce warnings while retaining the finding without those links. Explicit IDs are validated at delivery. No order-only edges are added by `event`.

A single captured execution can support several discoveries. Use its exact title in `--evidence` for each actual change, without rerunning it. Repeated measurements use `execute --question "Exact question" --title "Actual measurement" -- COMMAND...`; this adds a run to the same question, without creating a discovery. Existing JSON can be captured with `event --question "Exact question" --metrics-file result.json`. No per-tool start/finish events, fixed phases or node quotas are required.

IDs, evidence references and idempotent delivery are handled by the client. `--request-id` reuses the frozen event when retrying the same call; changed findings, reasons, references, analysis or question follow-up fields conflict with an existing request ID. Offline directories can independently retain the same question: atomic `node.ensure` creates it once while preserving existing metadata, together with each distinct event's frozen operations. Recovery performs no reclassification or source reread. Receipts expose `questionId`, `nodeId` and `eventType`.

The older `record --title TITLE` still creates a node; `record --node NODE --summary TEXT --conclusion TEXT` replaces only the fields supplied; omitting `--title` preserves the existing title without fetching it. Creating a record requires a nonempty title, and explicitly blank titles are rejected. Use it for deliberate edits, rather than a new discovery. `--conclusion`, `--kind`, `--parent` and explicit relationships remain available. New legacy records keep their automatic `recorded_after` connection unless `--independent` is supplied; this means recording order, not causality.

Keep conclusions and analysis in native platform fields by default. Do not create an additional `REPORT.md`, summary README or conclusion report unless the user explicitly requests a document. `event --notes TEXT` retains full analysis in `node.notes`. `--notes-file PATH` loads existing UTF-8 text, preserving its line breaks; `--notes-file -` reads stdin without requiring a new file. For example, in a POSIX shell:

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "Research question" --finding "Actual discovery" --notes-file - <<'ANALYSIS'
Retain the actual reasoning, alternatives and limitations here.
ANALYSIS
```

Notes are frozen metadata in the queued operation; they are not automatically attached as evidence. Omit notes to preserve the previous value, or supply an empty value to clear it. Reusing a request ID with changed notes or type is a conflict; use a new request ID for a deliberate revision. Background recovery and `sync` use the frozen notes without rereading the source analysis file. Repeating `event` or `record` validates the supplied intent: if its notes file is missing or unreadable, the same explicit request ID, file path and other arguments can reuse the frozen analysis; a readable file with changed text remains a conflict. Missing notes cannot create a new record. Keep scripts, original measurements and images as local evidence. Metrics retain their original JSON structure, including nested objects, arrays, empty containers and nulls. Non-object roots use `result` while the original file is preserved.

## Question origins

Question provenance is optional native metadata, distinct from containment, support and recording order. Set it while opening a question or editing an existing question:

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "Can the public implementation support a fair comparison?" --parent "Fair comparison" --origin-type goal --origin-node "Fair comparison" --origin-reason "Check whether the required baseline can actually be reproduced"
python3 <skill>/scripts/exp_observer.py record --project ID --node QUESTION_ID --origin-type finding --origin-node FINDING_ID --origin-reason "This observed failure raises the follow-up question" --origin-retrospective
```

`--origin-type` accepts a custom nonblank type; suggested types are goal, finding, literature, user and independent. Repeat `--origin-node` for several exact retained node IDs/titles, and `--origin-artifact` for original evidence IDs; `--origin-url` can reference an HTTP(S) source. A brief `--origin-reason` explains the connection; an explicitly supplied origin may reuse `--reason` when no separate origin reason is provided. Origin fields attach to the question even if that call also creates a finding.

The client freezes `questionOrigin` and its `recordedAt` before delivery. `--origin-retrospective` distinguishes a later evidence-based reconstruction from a contemporary record. Omitting these options preserves previous metadata and historical request fingerprints. Unresolved explicit IDs wait for registration; missing/ambiguous natural titles do not become new nodes. Declaring an origin does not fabricate semantic edges. Conversely, parentage, any incoming support link or creation order does not automatically establish why a question was raised. Independent exploration is an explicit declaration, not a guess from missing links. Legacy absence stays “Source not recorded”; a source removed later stays unresolved with its original identity.

## Conversation focus

An experiment can have several independent conversation associations, each with one or more focused nodes:

```sh
python3 <skill>/scripts/exp_observer.py focus --project ID --node NODE_ID --label "Compare candidate mechanisms"
python3 <skill>/scripts/exp_observer.py focus --project ID --node NODE_A --node NODE_B
python3 <skill>/scripts/exp_observer.py unfocus --project ID
```

`focus` with no nodes joins the experiment, retaining a previous selection when resuming. Nodes accept retained IDs or exact titles. `--owner` overrides the marker for that focus command. For ordinary writes too, set `EXP_OBSERVER_OWNER_ID` in that conversation’s process environment; it takes precedence over the native `CODEX_THREAD_ID`. A persisted workspace marker is the final fallback. Different conversations can use the same node; a conversation can maintain several experiments. Without a host marker, independent conversations sharing a directory should set distinct `EXP_OBSERVER_OWNER_ID` values. A one-off `--owner` does not change the owner used by subsequent ordinary writes.

Ordinary writes refresh an existing association while preserving the explicitly chosen node set; they do not create an association for historical clients. Update focus when the research moves. End only this conversation's association when it stops maintaining that experiment, rather than at every turn. Neither joining, expiry nor ending changes a scientific node, finishes a remote task, or closes another conversation's association. The default liveness window is 900 seconds (`--ttl-seconds` accepts 60–3600); prolonged analysis without a checkpoint can appear stale. A deliberate `focus` refresh is available without creating a research event.

Focus commands use a separate durable outbox. Frozen observation time determines expiry even when offline records arrive late. Per-lease sequence numbers reject old updates, and ended leases cannot revive. Restarting creates a new lease; a delayed end for the old one cannot close it. Heartbeats update separate operational storage, without adding research revisions or allocating Token counts. The frontend's **Current work** action jumps to one active node or offers a per-conversation list when several nodes are active. Stale associations remain distinguishable from current work.

## Remote task lifecycle

`execute` captures a local command. Submitting a cloud job is a separate command from the job's lifetime. Retain a known remote task without running or polling anything through Observer:

```sh
python3 <skill>/scripts/exp_observer.py task start --project ID --node NODE_ID --title "Candidate training" --task-ref JOB_ID --remote-identity "Training host / experiment directory" --started-at 2026-10-29T01:00:00Z --request-id candidate-job-start
python3 <skill>/scripts/exp_observer.py task update --project ID --run RETURNED_RUN_ID --status completed --finished-at 2026-10-29T02:15:00Z --request-id candidate-job-finish
```

Use actual original timestamps and a stable task identity from the executor. `--status` accepts queued, running, paused, completed, failed and cancelled. A terminal state requires its actual finish timestamp; an optional `--duration-ms` retains the executor’s reported finite, nonnegative duration. The UI separately derives elapsed time from wall-clock start/finish, so rounding, clock adjustment or a different timer does not require rewriting either measurement. Original start, owner and remote identity stay immutable. A terminal task cannot restart or change its finish through an ordinary update; its reported duration may be corrected or enriched while retaining earlier values in history. An update may attach measured JSON via `--metrics-file`; unreported GPU time, billing and Token usage stay unknown. A completed lifecycle does not decide the scientific question. Offline registration reuses frozen operations and never resubmits the remote job.

## Availability and recovery

`init --name NAME [--id ID]` saves a project plan before contacting the service. Keep the returned ID, including when the receipt is pending. An explicit project passed to `event` or `record` can also prepare a missing project. Recovery creates the project only if absent; it never replaces an existing project's metadata.

`context` returns an explicitly unavailable response when the service cannot be reached, together with any dated remote cache and a summary of local pending work. An unavailable response is not an empty remote experiment. Continue from research files when context is unavailable; preserve the supplied experiment ID.

Compact context exposes `hasNotes` without expanding every analysis. Use `context --project ID --node NODE` to read that node's native notes and its descendants' notes in full. This works online and offline: offline `localNodes` folds the available frozen node updates, preserving earlier notes through later summary-only revisions; `localPendingNodes` provides the corresponding view alongside pending work when the service is available. Summary and conclusion previews are limited to 512 characters with explicit `*Truncated` flags. The receipt lists remain bounded to 20 entries, while `localNodes` can still read older retained notes. A record's `localTaskPath` also identifies its original durable JSON. No separate report is needed.

The client writes only within the working directory. Application setup connects the research directory once; the running application discovers queues there, including future experiment subdirectories, without requiring the research agent to write a global registry. Discovery stays inside explicitly connected directories and never executes experimental commands. Queue contents, timestamps and staged evidence are frozen before submission; retries reuse stable identities. A child experiment reuses its ancestor's prepared project identity and metadata. A command blocked before execution cannot leave a durable record.

Manual recovery remains available from the original working directory:

```sh
python3 <skill>/scripts/exp_observer.py sync --project ID
```

`sync` reports pending registration separately from experimental outcomes and never reruns an experiment. Automatic recovery does not cover low-level `apply`, `artifact` or evidence reads; use those optional online operations only when appropriate. A real command's return code remains its own, even if registration is pending.

Before the final brief result, read the current local receipts and research-review hints once:

```sh
python3 <skill>/scripts/exp_observer.py status --project ID
```

`status` is read-only: it makes no HTTP requests, does not poll, run commands or retry submissions. It checks this working directory's queue and ancestor queues for this URL/project, without scanning sibling research. `source`, `scope` and `checkedAt` identify that local snapshot; `records` contains the latest receipts (up to 20), while counts cover all matching records. Project preparation is reported separately. `pendingCount` means queued records awaiting acknowledgement, and `incompleteCount` means capture did not finish and will not be rerun. `deliveryState: unknown` means no matching durable receipt was found; `partial` includes unreadable entries listed in `localReadWarnings`. Neither confirms full registration.

`researchReview` is separate from delivery. It folds node patches in captured order, retains omitted fields, and never reopens an existing question through `node.ensure`. Dated cached context can supersede older acknowledged state; still-pending changes overlay the cached snapshot. Its `openQuestions` contains locally known `active`/`running` question IDs, titles, status and follow-up fields. Use these as prompts to review questions actually involved in this work. `source`, `scope`, `coverage: local_snapshot_only` and `cachedContexts` identify the evidence and its dates; a dated cache remains a past snapshot. This is neither a scientific assessment nor a global experiment-state check. `needsReview` is true for known open questions, false only for the known local view without them, and null when unknown or incomplete with no known open question. `availability` reports available, unknown or partial local knowledge. No status read changes a question.

`deliveryState` describes recording, not connectivity; `transportChecked` is always false. For `synced`, report that the records were registered. For `pending`, say they are saved locally awaiting background reception. A past HTTP exception is a transport diagnostic, not evidence that the service is down. Historical `recordingWarnings` can remain in an acknowledged receipt and do not change its delivery state. A synced receipt confirms registration, not research success. Do not describe an earlier pending response as still pending after this snapshot says synced. Do not repeatedly call status or diagnose the platform to obtain a preferred result.

`execute --project ID --title TITLE -- COMMAND...` also works without a pre-existing node: it retains a new record and the real execution together. Supply `--node NODE` only to attach an existing record. A supplied missing node remains an invalid reference awaiting correction, rather than causing the client to invent it.

The following lower-level operations are optional adapter details.

For low-level atomic writes use `apply --project ID`, JSON input from stdin or `--file`. `context` returns the current `revision`. Supply `--expected-revision` for edits and a stable `--request-id` for safe retries. The batch is atomic: either all operations validate or none are saved.

```json
[
  {"op":"node.add","data":{"id":"study","kind":"group","title":"Retrieval study"}},
  {"op":"node.add","data":{"id":"baseline","parentId":"study","kind":"experiment","title":"Recorded scan result","status":"completed"}},
  {"op":"node.add","data":{"id":"index","parentId":"study","title":"Investigate indexing","status":"active"}},
  {"op":"edge.add","data":{"source":"baseline","target":"index","relation":"leads_to"}}
]
```

Any node kind is allowed. Parent IDs and relationship endpoints must exist in the resulting batch. Containment cycles are rejected; semantic revisit cycles are allowed.

Node states describe work, rather than scientific truth:

| Status | Meaning |
|---|---|
| `proposed` | Planned or untried; no execution implied |
| `active` | Currently being investigated |
| `paused` | Started, intentionally parked |
| `completed` | Research unit completed, including useful negative results |
| `rejected` | Deliberately excluded from this study |
| `failed` | Execution error prevented completion |

Runs retain their own status. Execution failure is distinct from a research conclusion. Legacy importance fields remain readable for compatibility; the project overview now comes from the outermost hierarchy with containers closed.

Example of parking started work while opening another direction, in one atomic batch:

```json
[
  {"op":"node.update","data":{"id":"EXISTING-NODE","status":"paused","pauseReason":"A newly observed counterexample changes the next priority","resumeWhen":"After the counterexample is explained","nextAction":"Finish the remaining repeated measurements"}},
  {"op":"node.add","data":{"id":"counterexample-review","title":"Explain the observed counterexample","status":"proposed"}},
  {"op":"edge.add","data":{"id":"pivot-review","source":"EXISTING-NODE","target":"counterexample-review","relation":"leads_to","basis":"observed","label":"Investigate the retained conflicting output"}}
]
```

Describe a relationship's basis honestly: `observed` for an actual observation, `hypothesis` for an untested relationship, or omit it when unknown.

Operations:

| Operation | Data |
|---|---|
| `node.add` | id?, title, kind?, status?, parentId?, isContainer?, collapsed?, summary?, conclusion?, notes?, nextAction?, importance?, importanceReason?, pauseReason?, resumeWhen?, tags? |
| `node.ensure` | explicit id plus creation fields; existing ID or alias preserves all metadata |
| `node.update` | id plus changed fields; omitted fields preserved |
| `node.merge` | id, target; folds a leaf into existing work, preserving runs, evidence, observations and decisions; original metadata remains in history |
| `node.delete` | id; removes subtree and associated execution records; recoverable from history |
| `edge.add/update/delete` | id, source/target/relation/label/basis as needed |
| `run.add` | id?, nodeId, title, status, configuration, metrics?, origin |
| `run.update` | id plus changed fields |
| `run.event` | runId, event: {id?,type,message,at?,...} |
| `assessment.add` | id?, runId, rubric, metrics, conclusion, limitations, supersedes?, artifactIds? |
| `decision.add` | id?, nodeId, title, conclusion, scope, nextAction, runIds, artifactIds |
| `project.update` | name?, description?, sourceRoots? |

Register actual evidence with `artifact`, rather than supplying hashes in metadata. Multiple files can be registered with `artifact --project ID --path result.json timing.csv`. Export with `export --project ID --output project.json`.

## Read evidence

Read registered evidence through the Skill client:

```sh
python <skill>/scripts/exp_observer.py read --project ID --artifact ARTIFACT_ID
python <skill>/scripts/exp_observer.py read --project ID --artifact ARTIFACT_ID --offset 262144 --limit 262144
python <skill>/scripts/exp_observer.py read --project ID --artifact ARTIFACT_ID --offset 0 --limit 4096 --output result-part.bin
```

The server verifies the full artifact's SHA-256 and byte count before returning the requested range. `read` defaults to the first 262144 bytes; `--offset` is a zero-based byte position and `--limit` is capped at 1048576 bytes. Default output is UTF-8 text; invalid or split characters use replacement characters. `--output` preserves the original range bytes and prints a concise file acknowledgement. Use it for binary evidence or exact bytes. Reads do not update experiment records. For direct adapters, `/api/projects/ID/artifacts/ARTIFACT/content?offset=0&limit=262144` provides the same bounded bytes, and `/metadata` verifies identity without returning content.

Assessment example, using an existing run:

```json
[{"op":"assessment.add","data":{"id":"eval-v1","runId":"ACTUAL-RUN-ID","rubric":"exact-query-v1","metrics":{"consistent":true,"mean_ms":0.2},"conclusion":"Exact output equality on the recorded fixture","limitations":"One machine and one fixed corpus; inspect repeated measurements","artifactIds":["REGISTERED-RESULT-ID"]}}]
```

The example values above illustrate shape only; replace with actual results. Use one rubric to compare measurement boundaries consistently. If preparation time was omitted, revise the assessment using the existing raw evidence when possible, linking `supersedes`. If new execution is needed, create a new run.

HTTP routes and storage contract: see the repository's `docs/contract.md` when developing an adapter. Agent research generally needs only this reference and the client.

## Node types and research hierarchy

The suggested types are `question`, `experiment`, `finding`; `record --kind TYPE` also accepts domain-specific types. Parallel follow-up questions remain questions, with explicit reasoning links; no required research phases are added.

The outermost cards, with containers closed, form the main research story. `event --container` makes its question a container; `record --container` does so for any typed node. `event --parent TITLE_OR_ID` nests the question, marks it as a container and retains its findings/corrections inside it, including later calls. `record --parent TITLE_OR_ID` attaches that record. `execute --parent TITLE_OR_ID` attaches a new experiment; with `--question` or `--node` it moves the existing execution owner only when explicitly requested. A referenced parent becomes `isContainer:true` without changing `kind`.

Parents resolve by exact retained ID or unique title from local ancestor queues and dated context, without extra online lookups. Missing or ambiguous parent titles fail clearly before execution; explicit unresolved IDs retain their identity pending ordinary server validation. The client does not invent ownership. Containment adds no causal edges. Keep a concise current `summary`/`conclusion` on the container via a deliberate `record --node ID` update. Nested subproblems may have their own containers, without another importance workflow. Omitted hierarchy options preserve legacy stable request fingerprints and existing frozen retries.

## Catalog recovery and collection diagnostics

The client retains a small readable project metadata snapshot alongside its context cache. If an existing ID is absent after a platform reset, recovery uses the retained name and description. With no metadata, it creates an unnamed placeholder and reports that gap. `init --id ID --name NAME` can upgrade an implicit plan and repair a placeholder; it does not replace a real remote name. Metadata recovery does not reconstruct files that were deleted from the research directory.

`GET /api/projects/ID/usage-status` exposes collector states and counts for matched captures, discovered/read logs, native usage events and imported records. Missing logs, unmatched receipts and no host usage are separate states. This endpoint diagnoses collection rather than scientific progress. Codex sessions are found by thread filename across creation dates; long logs are streamed once, then incrementally read. Windows Python runtime options such as `-X utf8 -B` are supported.

`event --summarizes TITLE_OR_ID` may repeat to connect earlier findings to a resulting answer using the `summarizes` relation. It is distinct from `--evidence` (supporting execution/evidence) and `--after` (the explicit related predecessor). For a new question derived from a finding, a question-only `event --after FINDING` retains its origin as `branches`. Independent questions remain valid roots.

Portable startup uses `scripts/bootstrap.py` and the release Skill's `assets/platform.zip` plus checksum. A fresh machine needs Python but no frontend build tools. Existing installations and data are reused; failed startup leaves normal capture queued. `--no-autostart` or `EXP_OBSERVER_AUTOSTART=0` disables startup, and local `status` never attempts it.
