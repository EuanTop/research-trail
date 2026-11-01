---
name: exp-observer
description: Observe research in a local ExpObserver experiment with brief updates, original results and retained evidence. Use when asked to track or resume an experiment. Recording supports the user's work and does not prescribe the research process.
---

# ExpObserver

Follow the user's research objective, budget and deliverables. Choose methods from evidence; recording adds no research phases.

Keep the analysis itself in Observer: use native `summary`, `conclusion` and Markdown `notes`, rather than a parallel local report. Create a separate analysis document only when the user asks for it; scripts, data and figures remain local evidence.

Use `scripts/exp_observer.py` relative to this Skill with Python 3.10+. Examples use `python3`; on Windows use `py -3` or the installed interpreter. The default address is `http://127.0.0.1:4317`; `EXP_OBSERVER_URL` or global `--url URL` selects another server.

The client automatically reuses or starts the local platform. A complete portable Skill from the release carries its runtime for offline first use; source-only copies can provision the official release in the background. No installation detour is needed during research. If startup is blocked, keep working with the local queue. `--no-autostart` (before the command) or `EXP_OBSERVER_AUTOSTART=0` keeps deliberate offline operation; local `status` never starts a service.

## Join or begin an experiment

With an experiment ID, use `context --project ID` once. If unavailable, continue from research files and any dated cache; missing context does not mean an empty experiment. Keep the supplied ID.

For a new experiment without an ID, prepare it once:

```sh
python3 <skill>/scripts/exp_observer.py init --name "Research task"
```

Keep the returned ID across conversations. This works offline; `event --project ID` can also prepare a missing project without `init`. After a confirmed missing project (for example a cleared platform), the client restores its readable name from retained metadata when available. If that metadata is missing, use `init --id ID --name "Readable research name"` once, preserving the ID; this repairs a placeholder without replacing a human-renamed project. An offline connection is not evidence that the project was deleted.

Declare this conversation's maintenance association with `focus --project ID --node NODE_ID` (repeat `--node` for parallel work). Without a node, it joins the experiment first; update focus when the actual work moves. The client uses the host conversation marker when available, otherwise retains a local owner marker. Ordinary recording refreshes this association without extra model calls. Other conversations can independently maintain the same experiment. When you stop maintaining it, call `unfocus --project ID`; keep it open while genuinely continuing between turns. Ending focus changes no research status. If interrupted, the association expires as stale rather than claiming the work finished. See [focus and remote tasks](references/records.md#conversation-focus) for optional controls.

## Record at natural boundaries

Use `event` to retain actual research changes in the research's own wording. The client manages identities and references; no node numbering or predetermined script-to-finding mapping is needed.

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "What affects confirmation time?" --finding "Navigation backtracking offsets part of the gain"
```

`--question` alone opens a meaningful question as active; optional `--reason` explains why it matters. Its exact title or a retained ID reuses that question, including across ancestor queues and retained context. Titles are not matched approximately. Findings need no prior opening call: the same invocation can retain both a new question and its first finding.

Start with the suggested types **question, experiment, finding**. These are suggestions, not phases or a closed vocabulary: use `record --kind TYPE` for any research-specific type that communicates the work better. Use `--finding` for a substantive discovery or `--correction` when revising an earlier judgment, naming the earlier judgment with `--after` when known. Routine deploy, copy and backup success already belongs in execution/evidence; create a discovery when it changes the research judgment. Each change is a separate ordinary node linked to the stated question; earlier findings remain intact. `--after "Earlier finding title"` relates a change to a retained finding, defaulting to `revises` for a correction, `leads_to` for a direction or `related_to` for a finding; `--relation supports` can explicitly state support. No causal relationships are inferred from prose or recording order.

When opening a question, retain its source when known in the same call: `--origin-type goal --origin-node "Exact goal title/ID" --origin-reason "Why this question follows"`. Suggested sources are goal, finding, literature, user and independent; custom types are welcome. Repeat `--origin-node` for several inputs; literature can use `--origin-url` or `--origin-artifact`. Explicit independent exploration can use `--origin-type independent` with a brief reason. Mark a later reconstruction `--origin-retrospective`; do not invent a missing historical trigger. Containment alone does not establish a source. Omitted origin stays unknown and does not block research. See [question origins](references/records.md#question-origins) for details.

New follow-up questions are questions, not “direction” nodes. For parallel questions arising from one result, repeat `event --question "New question" --after "Earlier finding"`: each becomes a branch with its own state. The legacy `--direction` option remains for an explicit change of approach; do not use it as a default step or for every new branch.

When a result triggers a new question, include its title/ID with `--after` in that same record. Independent questions may remain roots. When an answer combines earlier findings, repeat `--summarizes "Finding title/ID"` on its `event --finding` call; this retains the reasoning links without treating every incorporated result as scientific support.

Retain different discoveries even when one script produced them. Repeat measurements of the same question reuse its identity; routine steps need no event. The last substantive finding can also update its question with `--status completed` or `--status paused --next-action TEXT`; `--pause-reason TEXT` and `--resume-when TEXT` retain why it stopped and what would restart it. Omitted fields preserve existing values. Do not invent stages, fill a node quota or create completion-only findings.

As you finish, check only questions you actually worked on: mark resolved work completed; pause unresolved work you are no longer advancing and leave its next action; keep genuinely ongoing work active. A turn ending does not pause the whole experiment or unrelated questions.

## Organize research by subproblem

The project overview is the outermost research graph with containers closed; it is the main research story. No separate important-node selection is needed. Use a meaningful question as a container when its exploration needs its own space. `event --container` keeps that question's findings inside it. `--parent "Exact parent title/ID"` nests a question and makes both it and its parent containers, preserving their research types. Later calls reuse that ownership from local records or dated context. Keep container titles concise and its summary/conclusion current with `record --node ID --summary TEXT --conclusion TEXT`; update `--next-action` when the remaining work changes. Do not create a second summary document.

```sh
python3 <skill>/scripts/exp_observer.py event --project ID --question "What affects confirmation time?" --container
python3 <skill>/scripts/exp_observer.py event --project ID --question "Does backtracking explain the delay?" --parent "What affects confirmation time?" --reason "Check the observed navigation detours"
python3 <skill>/scripts/exp_observer.py event --project ID --question "Does backtracking explain the delay?" --finding "Backtracking offsets part of the gain"
```

Containment expresses research ownership; `--after`, `--evidence` and `--summarizes` retain actual reasoning relationships separately. Independent work may stay at the outermost level. Add containers when useful, without grouping quotas or mandatory stages. `execute --parent "Question title/ID"` puts a new experiment inside that container; `execute --question "Question title/ID"` instead adds a run to the existing question without moving it. Parent titles must resolve exactly before a new command runs; explicit IDs remain subject to normal reference validation.

## Keep analysis in the experiment

Use `event --notes TEXT` for full reasoning, comparisons and limitations. Notes render Markdown headings, lists, tables and code blocks natively. `--notes-file PATH` loads existing UTF-8 analysis verbatim; `--notes-file -` reads stdin without creating a local report. Notes belong to the supplied change, or to the question when no change is supplied. They supplement the visible finding rather than hiding distinct discoveries in a shared script node. Omitted notes preserve existing notes.

Attach existing JSON with `--metrics-file results.json --artifact results.json`. Nested values are preserved; other root types use `result`. Files stay unchanged.

For a command you are about to run and want measured execution records for, use the capture entry instead of running the same command directly:

```sh
python3 <skill>/scripts/exp_observer.py execute --project ID --title "Actual command" -- python3 experiment.py
```

This captures timing, exit code and stdout/stderr independently of future findings. Add `--artifact PATH` for results. `event --evidence "Actual command"` links an actual finding to that captured evidence; several findings can reuse it. For repeated measurements, `execute --question "Exact question" --title "Actual measurement" -- COMMAND...` retains another run of the same question. Never rerun work just to split its findings.

For remote training or another detached job, local submission is not the job itself. Retain the remote task identity and actual lifecycle using `task start` / `task update` as described in the [record reference](references/records.md#remote-task-lifecycle). Preserve the original start and completion times; a local command finishing or focus ending does not finish remote work.

The older `record` entry remains available for direct edits. Its `--node` option replaces supplied fields on that node; omit `--title` to keep the current title. New records require a nonempty title; use `event` for a new finding or correction.

## Let recording recover separately

Call the client even offline: result files alone do not queue records. `init`, `event`, `record` and `execute` save locally; the application reads connected research directories, including new experiment subdirectories. No global-directory write is needed. Pending means saved locally, awaiting registration. Continue without polling.

The command's exit status describes the experiment; `pending` and `recordingWarnings` describe recording. If the host blocks client execution or local saving fails, continue and report recording unavailable; do not claim it was queued.

A workspace network denial is an expected local-queue mode. Do not request a sandbox exception, relax permissions or retry network access just to register observations. Continue the research and use the final local receipt to describe delivery.

Recovery never reruns experiments or rereads changed source evidence. Unresolved retained IDs wait in the queue rather than becoming new question titles. Do not reformat outputs, repeat experiments or diagnose IDs/retries merely to complete a record. Delivery failures are retained for the platform's sync view; manual `sync` is optional recovery.

Before your final brief result, call `status --project ID` once from the research working directory. It reads local receipts and dated context without HTTP or polling. `researchReview.openQuestions` prompts you to check locally known active/running questions you actually touched; it does not assess conclusions or prove global state. No local question/context means research review is unknown. Keep this review separate from `deliveryState`. Background recovery may have replaced an earlier pending receipt with `synced`; use this latest `deliveryState`, not an old `pending` response, when describing registration. Say registered for `synced`, or saved locally awaiting background reception for `pending`. This does not test HTTP reachability: a past client connection error is not evidence that the service is down, and historical warnings do not make an acknowledged record pending. Respect the reported local scope; unknown or partial status does not confirm registration. A synced receipt confirms registration rather than scientific success.

Execution counts refer to captured commands, not the number of research findings. A finding recorded after direct execution does not create command timing retroactively. Keep existing results and evidence; never rerun a completed experiment to fill missing statistics.

Host adapters collect provider-reported Token counters automatically from supported local runtimes; recording does not require the Agent to estimate or count tokens. Work-window attribution is separate from measured counters. Keep unavailable or ambiguous usage unknown, and do not bind a conversation exclusively to an experiment.

Label synthetic data honestly.

The [record reference](references/records.md) covers native analysis, optional edits, assessments and evidence reads.
