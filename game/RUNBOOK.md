# DOOM operator runbook

Operating procedures for the playable-README game (`.github/workflows/doom.yml`).
Every command below is runnable as written; substitute nothing but the values in
`<angle brackets>`.

The one thing to internalize before anything else:

> **A failed run never loses a move.** Moves are consumed only when their issue
> number lands in the committed ledger (`game/state/log.txt`). Unprocessed
> moves stay open as issues, and the next green run — a new move, the 6-hourly
> sweep, or a manual dispatch — drains them in ascending issue order. There is
> no state to hand-repair after a red run.

Conventions used throughout:

```sh
REPO=nikitastetskiy/nikitastetskiy   # the sandbox rehearsal repo is nikitastetskiy/doom-sandbox
```

Quick reference:

| # | Situation | Section |
|---|---|---|
| 1 | A run went red | [1. Red-run procedure](#1-red-run-procedure) |
| 2 | Stuck on UNAVAILABLE, or moves are backed up | [2. Manual dispatch](#2-manual-dispatch-drain-re-render-and-unavailable-recovery) |
| 3 | Something is actively wrong — stop the game now | [3. Emergency stop](#3-emergency-stop-gh-workflow-disable) |
| 4 | A bad commit landed on the profile | [4. Rollback by revert](#4-rollback-by-revert-commit) |
| 5 | The sweep stopped firing | [5. Re-enabling the sweep after the 60-day auto-disable](#5-re-enabling-the-sweep-after-the-60-day-auto-disable) |
| 6 | Every run aborts with a marker error | [6. Marker repair (the fail-safe brick)](#6-marker-repair-the-fail-safe-brick) |
| 7 | Receipts stopped appearing | [7. Receipt degradation](#7-receipt-degradation-under-secondary-rate-limits) |
| 8 | The README image is stale | [8. Camo PURGE (use sparingly)](#8-camo-purge-use-sparingly) |
| 9 | Runs are green but moves are bounced with "the arcade is being upgraded" | [9. Sealed section (pin mismatch)](#9-sealed-section-pin-mismatch) |
| 10 | Runs are green but moves are bounced with "log full" | [10. Section cap (the LOG_FULL screen)](#10-section-cap-the-log_full-screen) |
| 11 | A run went red at *Encode the GIF* | [11. Publish-gate refusals (exit 11, 12, 13)](#11-publish-gate-refusals-exit-11-12-13) |

---

## 1. Red-run procedure

**Symptom.** A `doom` workflow run has a red X. After two consecutive failures the
sweep opens (or comments on) an issue labelled `doom-maintenance` assigned to Nik
— workflow-failure email goes to the *player who opened the issue*, not to the
owner, which is exactly why that alert exists.

**What is already true, without you doing anything.**

- Game state is intact. The failure-path write contract keeps the ledger and the
  GIF untouched by any failed run.
- Every unprocessed move is still an open issue.
- The README shows either the last good LIVE frame or the UNAVAILABLE screen.
  UNAVAILABLE means *"moves are not being processed right now"* — it does **not**
  mean the displayed frame is wrong. An untouched prior frame is accurate history.

**Diagnose.**

```sh
# The failing runs, newest first.
gh run list --repo "$REPO" --workflow doom.yml --limit 10

# Full logs for one run.
gh run view <run-id> --repo "$REPO" --log-failed

# Which moves are waiting.
gh issue list --repo "$REPO" --state open --search 'doom: in:title' --limit 50
```

Read the failing step name — it maps directly onto a write-contract row:

| Failing step | Class | What was written |
|---|---|---|
| Drain / Apply / Simulate / Encode | pre-push | nothing; best-effort UNAVAILABLE swap |
| Apply moves — exit 7 | refuse-to-run | nothing → [section 9](#9-sealed-section-pin-mismatch) |
| Encode the GIF — exit 11 / 12 / 13 | pre-push, publish gate refused | nothing → [section 11](#11-publish-gate-refusals-exit-11-12-13) |
| Rewrite the README game block | marker validation | nothing at all, swap suppressed → [section 6](#6-marker-repair-the-fail-safe-brick) |
| Push the game state | push failure | GIF may be on `output`; ledger is not on the default branch |
| Close issues and post receipts | post-push | everything landed; only receipts failed → [section 7](#7-receipt-degradation-under-secondary-rate-limits) |

**Exit 7 from *Apply moves* is not an ordinary failure.** It means a
frame-contributing move was about to land in a **sealed** section — a section
whose pins no longer match the running toolchain. Under SPEC §5.5 the drain is
supposed to prevent that from ever reaching `apply_moves.py`, so seeing exit 7
means the drain misbehaved: treat it as a pipeline bug, not an operational
event. Nothing was written either way. Go to
[section 9](#9-sealed-section-pin-mismatch), which covers both the normal
(self-healing) pin-mismatch path and this anomaly.

**A green run that appended nothing is not a failure.** When every move a run
drained was rejected in band — all sealed-rejected, or all cap-rejected — the run
**succeeds** with zero ledger appends, no GIF publish, and a display-only swap to
SEALED or LOG_FULL (SPEC §10, degraded-mode note). The run summary says so
explicitly under *Degraded mode — this run SUCCEEDED*. Nothing failed and no game
state was ever eligible to change, so there is nothing to repair:
[section 9](#9-sealed-section-pin-mismatch) and
[section 10](#10-section-cap-the-log_full-screen) describe how each clears.

**Recover.** Fix the cause if there is one, then run a normal dispatch
([section 2](#2-manual-dispatch-drain-re-render-and-unavailable-recovery)). If
the cause is transient (rate limit, runner loss, GitHub incident), do nothing:
the next sweep drains the backlog within 6 hours.

**Close the maintenance issue** once a green run lands — the sweep reuses an open
`doom-maintenance` issue rather than opening a new one, so leaving it open
suppresses future alerts.

---

## 2. Manual dispatch: drain, re-render, and UNAVAILABLE recovery

`workflow_dispatch` is the operator's single lever. It runs the identical drain →
render → publish path as a real move, in the same concurrency group, and it is
the documented way back out of UNAVAILABLE.

**Drain the backlog / re-render / recover from UNAVAILABLE:**

```sh
gh workflow run doom.yml --repo "$REPO" --ref main
gh run watch "$(gh run list --repo "$REPO" --workflow doom.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --repo "$REPO"
```

That is the whole recovery. The run re-reads every open move from the API (the
drain invariant — a run never trusts its own event payload), applies whatever is
pending, and rewrites the README back to LIVE.

**Rehearse without touching anything** — full drain ordering, TOCTOU
re-validation and parse path against the real open issues, with every push,
close, reaction and comment disabled:

```sh
gh workflow run doom.yml --repo "$REPO" --ref main -f dry_run=true
```

**Push one synthetic title through the parser** (accepted only together with
`dry_run=true`; a synthetic issue number is used so it can never collide with a
real one):

```sh
gh workflow run doom.yml --repo "$REPO" --ref main \
  -f dry_run=true -f simulate_title='doom: turn-left x3'
```

**Note on branches.** `issues:` events only ever run the workflow file from the
default branch, so the move loop cannot be exercised from a feature branch.
`workflow_dispatch` has no such restriction — `--ref <branch>` runs the branch's
copy — which is why the dry-run path exists and why the full loop is rehearsed in
`nikitastetskiy/doom-sandbox` before anything reaches the profile.

---

## 3. Emergency stop (`gh workflow disable`)

Use when the game is actively misbehaving: a runaway loop, an abuse wave, a
corrupt render being republished, or anything you do not yet understand.

```sh
# Stop accepting moves. Takes effect immediately; queued runs still finish.
gh workflow disable doom.yml --repo "$REPO"

# Confirm.
gh workflow list --repo "$REPO"

# Cancel anything already running.
gh run list --repo "$REPO" --workflow doom.yml --status in_progress \
  --json databaseId --jq '.[].databaseId' \
  | xargs -r -n1 gh run cancel --repo "$REPO"
```

While disabled, players can still open `doom:` issues; nothing processes them and
nothing closes them. They queue harmlessly and drain when you re-enable.

**Show players an honest state while it is off** (optional but kind) — hand-edit
`README.md` between the markers, or push a PAUSED render:

```sh
python3 game/scripts/rewrite_readme.py \
  --readme README.md --mapping game/mapping/v1.json \
  --state PAUSED \
  --image-url "game/assets/screens/paused.png"
git add -- README.md && git commit -m 'chore(doom): pause the game' && git push
```

**Re-enable:**

```sh
gh workflow enable doom.yml --repo "$REPO"
gh workflow run doom.yml --repo "$REPO" --ref main   # drain what queued up
```

---

## 4. Rollback by revert commit

The game commits only text to the default branch (ledger, stream, README), so
rollback is an ordinary revert. **Never force-push the profile's default branch**
— it is Nik's identity page and its history is shared.

```sh
git fetch origin main && git switch main && git pull --ff-only

# Inspect what the game has been doing.
git log --oneline -20 -- game/state README.md

# Undo one bad game commit.
git revert --no-edit <sha>
git push origin main
```

Reverting a game-state commit un-applies those moves from the ledger. Their
issues are already closed, so they will **not** be re-drained (closed issues are
not listed) — the moves are simply gone from the timeline. That is usually what
you want during a rollback. If you want them back, reopen the issues:

```sh
gh issue reopen <number> --repo "$REPO"
gh workflow run doom.yml --repo "$REPO" --ref main
```

**The GIF needs no rollback.** The `output` branch is force-pushed every run and
holds exactly one file; the next successful run replaces it. If the README ends
up pointing at a `?run=` id whose GIF is gone, just dispatch a re-render
([section 2](#2-manual-dispatch-drain-re-render-and-unavailable-recovery)).

**Rolling back the pipeline itself** (workflow or scripts) is the same revert,
but disable the workflow first ([section 3](#3-emergency-stop-gh-workflow-disable))
so no run picks up a half-reverted tree.

---

## 5. Re-enabling the sweep after the 60-day auto-disable

GitHub disables `schedule` triggers after **60 days without repository
activity**. The sweep is both the straggler net and the mechanism that shows
PAUSED after a quiet spell, so it is exactly the thing that dies during the quiet
spell it exists to handle.

Mitigation already in the workflow: after `IDLE_PAUSE_DAYS` (45) without a
game-state commit, the sweep pushes the PAUSED screen. That is an honest display
*and* repository activity. **Do not rely on it** — a bot push does not reliably
reset GitHub's activity clock. Check periodically:

```sh
# state: active | disabled_inactivity | disabled_manually
gh api "repos/$REPO/actions/workflows/doom.yml" --jq '.state'
```

Re-arm:

```sh
gh workflow enable doom.yml --repo "$REPO"

# Verify it took, and drain anything that piled up while the sweep was dead.
gh api "repos/$REPO/actions/workflows/doom.yml" --jq '.state'
gh workflow run doom.yml --repo "$REPO" --ref main
```

`issues:`-triggered runs are **never** affected by this — real moves keep working
throughout. Only the sweep sleeps.

---

## 6. Marker repair (the fail-safe brick)

**Symptom.** Every run fails at *Rewrite the README game block*, the README is
byte-untouched, no UNAVAILABLE screen appears, and moves pile up as open issues.
The rewriter emitted a `marker_error` on stdout.

**Cause.** `game/scripts/rewrite_readme.py` validates the marker pair *before*
writing anything: `<!-- DOOM:START -->` and `<!-- DOOM:END -->` must each appear
**exactly once**, in that order, each on its own line. Anything else aborts with
exit 6 and suppresses the state-screen swap — writing inside markers that just
failed validation is exactly what must never happen. It is fail-safe by design,
and it bricks the game until a human fixes it.

The classic trigger is a **false positive**: quoting the marker strings anywhere
else in the README — in prose, a code block, or a "how this works" section — makes
the count 2.

**Diagnose.**

```sh
grep -n 'DOOM:START\|DOOM:END' README.md
grep -c '<!-- DOOM:START -->' README.md   # must be exactly 1
grep -c '<!-- DOOM:END -->'   README.md   # must be exactly 1
```

The classes the rewriter reports: `missing-start`, `missing-end`,
`duplicate-start`, `duplicate-end`, `reversed`.

**Repair.** Edit `README.md` so the file contains exactly one well-formed pair:

```markdown
<!-- DOOM:START -->
<!-- DOOM:END -->
```

- Both markers on their own lines, START before END.
- Delete or reword every other mention. If you must document the markers in prose,
  break the literal (for example `DOOM:` + `START`) so it cannot be counted.
- Do not touch anything outside the pair — everything outside is Nik's identity
  content and is byte-invariant across every game commit.

**Verify before pushing** (the rewriter is safe to run locally; it writes only
between the markers and is idempotent):

```sh
python3 game/scripts/rewrite_readme.py \
  --readme README.md --mapping game/mapping/v1.json \
  --state PAUSED \
  --image-url "game/assets/screens/paused.png"
echo "exit: $?"   # 0 = repaired, 6 = still broken

python3 -m pytest game/tests/test_rewriter.py -q
```

Then commit, push, and dispatch a run
([section 2](#2-manual-dispatch-drain-re-render-and-unavailable-recovery)) to
drain everything that queued up.

---

## 7. Receipt degradation under secondary rate limits

**Expected behaviour, not a bug.** Every drained move spends roughly three
content writes (reaction + comment + close), which puts the sustained ceiling
around **150–170 moves/hour** before GitHub starts answering 403. The workflow
degrades on purpose, in this order:

1. **First denial** → reactions are dropped for the rest of the run
   (`::warning::reaction denied …`).
2. **Second denial** → comments are dropped too
   (`::warning::comment denied twice …`).
3. **Closes are always attempted.** A close that fails is not an error you need to
   fix: the issue stays open, the next run sees its number already in the ledger,
   and closes it as close-only cleanup without re-applying the move.

So under a front-page day you will see moves applied, the GIF updating, and
issues closing with no receipt. **The ledger is never affected** — receipts are
UX, and close-eligibility never decouples from the committed ledger.

**Confirm it is only receipts:**

```sh
gh run view <run-id> --repo "$REPO" --log | grep -E 'reaction denied|comment denied|close failed'

# Moves that landed anyway:
git log --oneline -10 -- game/state/log.txt
```

**If closes themselves fail**, the step exits non-zero and the run goes red; the
UNAVAILABLE swap is deliberately suppressed because the push already succeeded
and the LIVE frame is correct. Wait for the limit to lapse (usually minutes) and
dispatch a run — it will do close-only cleanup and touch nothing else.

Also note honestly: under drain batching a receipt shows the state **after the
batch containing that move**, not the move in isolation.

---

## 8. Camo PURGE (use sparingly)

Normally unnecessary. Every run rewrites the README with a fresh
`?run=<run_id>` query, which is a new Camo cache key — that is the whole
cache-busting design, and it beats the measured 5-minute `max-age` structurally.

Reach for PURGE only when the README points at a URL you know is current but
GitHub keeps serving an old image (a hand-repaired README, a re-pushed `output`
branch under an unchanged buster).

```sh
# 1. Get the camo.githubusercontent.com URL for the game image.
curl -sL "https://github.com/$REPO" \
  | grep -o 'https://camo.githubusercontent.com/[A-Za-z0-9/._-]*' | sort -u

# 2. Purge it.
curl -X PURGE '<camo-url>'
```

**Sparing use is the rule** — it is an undocumented escape hatch, not an API.
Prefer a re-render, which changes the URL and needs no purge at all:

```sh
gh workflow run doom.yml --repo "$REPO" --ref main
```

---

## 9. Sealed section (pin mismatch)

**Symptom.** Runs are **green**, but every move comes back closed with
`the arcade is being upgraded — press New game to continue`, the README shows the
SEALED screen, the ledger stops growing and no new GIF is published.

**This is the guard working, not a fault.** A section is *sealed* when one of its
**sealing pins** — `engine`, `wad`, `mapping` (SPEC §5.2, mirrored as
`sealing_pins` in `game/mapping/v1.json`) — no longer matches the running
toolchain, which happens whenever the engine commit, the WAD or the mapping
version is bumped in a default-branch commit. Rather than append moves to a
section it can no longer reproduce, the game refuses to advance that section and
says so. Sealing is computed at run time by comparison; it is never stored or
configured, so there is no flag to unset.

**`build` is not a sealing pin** (SPEC §5.9). The header still carries it, as a
record of which binary produced that section's frames, but nothing compares it:
a binary's SHA-256 is a property of the **runner image version**, which GitHub
rotates on its own schedule, and sealing on it would answer an infrastructure
event by demanding a `new game` — discarding a live session's history to repair
nothing. Determinism is pinned on the **replay** instead
([section 12](#12-engine-replay-equivalence-spec-59)). So a `build=` that differs
from `game/toolchain.json` seals nothing and is not why you are here.

**It clears itself.** `doom: new game` contributes zero frames, so it provably
cannot alter the sealed section's replay output — which makes it the one
admissible move while sealed. The first reset submitted closes the sealed section
and opens a fresh one carrying the running pins; play resumes immediately, and
any later moves in the same batch land in the new section and simulate normally.
The 30-minute new-game cooldown does **not** apply while sealed, so recovery can
never be rate-limited away. **No operator action is required** — the normal
outcome is that a player presses New game within an ordinary play window and the
game heals in band.

**Confirm that is what you are looking at** — the runs should be green, and
exactly one pin should differ:

```sh
gh run list --repo "$REPO" --workflow doom.yml --limit 5      # green, not red
grep '^#section ' game/state/log.txt | tail -1                # the header in force
# Only the three sealing pins are comparands. `build` is deliberately absent.
jq '{engine: .engine.commit_sha, wad: .wad.sha256}' game/toolchain.json
jq -r '.mapping_version' game/mapping/v1.json
jq -r '.sealing_pins | join(", ")' game/mapping/v1.json        # engine, wad, mapping
```

The run log states the section's state outright, on every run — including one
that drained nothing:

```sh
gh run view <run-id> --repo "$REPO" --log | grep -o 'section=[a-z]*'   # sealed | capped | open
```

**To clear it now** — because nobody is playing, or because you just bumped the
toolchain and want the game live again — submit the reset yourself. It is an
ordinary move, not a privileged operation:

```sh
gh issue create --repo "$REPO" \
  --title 'doom: new game' \
  --body 'Unsealing after a toolchain bump.'
```

The title must be byte-exact. Then confirm the rollover landed:

```sh
gh run watch "$(gh run list --repo "$REPO" --workflow doom.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --repo "$REPO"
git pull --ff-only
grep -c '^#section ' game/state/log.txt      # one more section than before
grep '^#section ' game/state/log.txt | tail -1   # pins now match the toolchain
```

**When to escalate.** Each of these means a code defect, not an incident:

| Observation | Meaning |
|---|---|
| A `doom: new game` was submitted but the section did not roll over | the drain is not applying the sealed-mode exemption |
| *Apply moves* fails with **exit 7** | a frame-contributing move reached `apply_moves.py` while sealed; the drain should have rejected it first. Defense in depth caught it and wrote nothing — but the drain is wrong |
| Sealed with no toolchain change | check recent commits to `game/toolchain.json` and `game/mapping/v1.json` for a move in `engine`, `wad` or `mapping_version` |
| Sealed after an engine cache miss or a runner image rotation, with no pin commit | a defect. `build` is not a comparand (SPEC §5.9), so a rebuilt binary cannot seal anything. Two sealed sections appearing one per reset is the livelock signature §5.9 records — stop the game |
| The run failed instead of sealing | not this section. A hard failure at *Restore the pinned toolchain* is [section 12](#12-engine-replay-equivalence-spec-59) |

For the first two, stop the game
([section 3](#3-emergency-stop-gh-workflow-disable)) and treat it as a bug.

**What not to do.** Do not hand-edit `game/state/log.txt`, and do not rewrite a
section header to make the pins agree. The rollover is the only runtime recovery
and it is designed to need no privileged intervention; editing authoritative
committed state to step around a guard is precisely how a timeline forks. If the
pins themselves are wrong, fix `game/toolchain.json` (or revert the bump) and let
a reset roll the section over.

### How the SEALED screen gets there

The workflow **looks the screen up** from `drain.py`'s section state — a
top-level `"section": {"state": "sealed"|"capped"|"open"}` in the drain's action
plan, unconditional on every exit-0 drain (SPEC §5.8). The `work` step maps
`sealed` → `SEALED`, `capped` → `LOG_FULL`, `open` → no screen, validating the
value against `game/mapping/v1.json` `section_states` first. It is a **lookup,
not a predicate**: the pin comparison lives in `drain.py`, which owns it, and is
never re-derived in YAML (§0.5). Player-visible guidance prose is never matched
either — those messages are written for humans and may be reworded (§5.7).

An unmapped state, or a **missing** `section` member, fails the run loudly and
writes no step output. That asymmetry is deliberate: `open` is the value that
says *nothing to report*, absence says *the drain never told me*, and defaulting
absence to "no screen" would turn a broken producer into a silent one in exactly
the case the field exists to close.

**Precedence (SPEC §11) — at most one screen per run, first rule wins:**

| # | Rule | Effect |
|---|---|---|
| 1 | The abuse halt writes PAUSED and stops (§6) | nothing below runs |
| 2 | A run that **publishes a frame** shows LIVE | the section's condition surfaces next run |
| 3 | Otherwise the **section state** selects the guidance screen, outranking PAUSED | SEALED / LOG_FULL |
| 4 | UNAVAILABLE, only on a §10 failure row | never over a guidance screen this run pushed |

So the condition is **state selects the screen, a publish suppresses it** — not
"the batch was all rejected". Two consequences worth knowing:

- **A quiet blocked game now shows its screen.** A section sealed by a
  default-branch commit with an empty queue rejects nothing, so the old
  all-rejected gate left exactly that visitor staring at a stale live frame. The
  idle sweep swaps it in now, and the idle-PAUSED step is suppressed by the same
  state, because a section that is blocked is not idle — it is being played and
  answered.
- **LOG_FULL can legitimately be one run late.** Rule 2 strictly precedes rule 3,
  and it is reached by the common case: a batch whose applied moves carry the
  section past the frame cap ends `capped` *and* publishes a frame. That run
  shows LIVE; the LOG_FULL screen appears on the next run, which is also the next
  moment a player can act on it. This never delays SEALED — while sealed the only
  admissible move is the zero-frame rollover, and applying it un-seals.

The run stays green throughout.

**The swap is best effort, exactly like the UNAVAILABLE swap.** Its push can lose
a race with another writer, and it carries `continue-on-error: true` because
turning a spec-defined *success* red over a cosmetic push would also trip the
sweep's consecutive-failure alert. If the run summary shows
`swap outcome: failure`, the issues were still closed correctly and the ledger is
still right — only the displayed screen is stale. Force it by hand:

```sh
python3 game/scripts/rewrite_readme.py \
  --readme README.md --mapping game/mapping/v1.json \
  --state SEALED \
  --image-url "game/assets/screens/sealed.png"
git add -- README.md && git commit -m 'chore(doom): show the sealed screen' && git push
```

Or just dispatch a run ([section 2](#2-manual-dispatch-drain-re-render-and-unavailable-recovery)).
Any completed run re-renders it, including one with nothing pending — the screen
follows the section's state, not the traffic.

---

## 10. Section cap (the LOG_FULL screen)

**Symptom.** Runs are **green**, but every move comes back closed with
`log full — start a new game`, the README shows the LOG_FULL screen, the ledger
stops growing and no new GIF is published.

**This is the cap working, not a fault.** A section stops accepting
frame-contributing moves once its accumulated frames reach
`knobs.section_cap_frames` in `game/mapping/v1.json`. It is the same in-band
rejection mechanic as a sealed section ([section 9](#9-sealed-section-pin-mismatch))
and it takes the same recovery: `doom: new game` contributes zero frames, closes
the full section and opens a fresh empty one.

The two are distinguishable and never ambiguous — the section cap is about
**length**, sealing is about **toolchain pins**:

| | LOG_FULL | SEALED |
|---|---|---|
| Cause | the section hit its frame cap | a **sealing pin** (`engine`, `wad`, `mapping`) no longer matches the running toolchain |
| Section state (§5.8) | `capped` | `sealed` |
| Drain reason code | `section-cap` | `sealed` |
| Player message | `log full — start a new game` | `the arcade is being upgraded — press New game to continue` |
| `new game` cooldown | **applies** (30 min) | **does not apply** (§5.5 rule 6) |
| Clears by | `doom: new game` | `doom: new game` |

`sealed` wins where both hold at once, which is the order the drain already
applies when admitting moves, so the reported state and the admission decision
cannot disagree.

**The screen can lag the cap by exactly one run, and that is correct.** The state
is reported as of the **end of the batch**, so a run whose applied moves carried
the section past the cap reports `capped` *and* published a frame. SPEC §11 rule
2 precedes rule 3, so that run shows LIVE and LOG_FULL appears on the next run —
which is also the next moment a player can do anything about it. If you see a
`capped` state in the log and a LIVE frame on the profile from the same run,
nothing is broken.

**Confirm that is what you are looking at:**

```sh
# Frames accumulated in the current section vs. the cap.
jq -r '.knobs.section_cap_frames' game/mapping/v1.json
python3 - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "game/scripts")
import gamelog
mapping = gamelog.load_mapping(pathlib.Path("game/mapping/v1.json"))
log = gamelog.parse_log(pathlib.Path("game/state/log.txt").read_text(), mapping)
frames = gamelog.token_frames(mapping)
current = log.sections[-1]
print("current section frames:", sum(frames.get(e.token, 0) * e.count for e in current.entries))
PY
```

**No operator action is required** — the first `doom: new game` a player submits
clears it. Unlike sealing, the 30-minute cooldown **does** apply here, so a reset
submitted within 30 minutes of the previous one is itself rejected; that is
anti-grief behaviour on a live game, not a fault. To clear it yourself, submit an
ordinary reset:

```sh
gh issue create --repo "$REPO" --title 'doom: new game' --body 'Rolling the section over at the cap.'
```

---

## 11. Publish-gate refusals (exit 11, 12, 13)

**Symptom.** A run went red at *Encode the GIF through the budget ladder*. The
run summary carries a `### Refused: …` block naming the exit code.

All three are **pre-push** failures: the ledger, the stream and the `output`
branch are byte-untouched, every drained move is still an open issue, and the
best-effort UNAVAILABLE swap fires. There is no state to repair. What differs is
**where you look first** — which is the entire reason SPEC §12.1 spends separate
integers on them instead of one generic "the encode failed".

| Exit | Verdict | What it means | Ladder descent | Look at |
|---|---|---|---|---|
| 11 | `ceiling` | A complete GIF that is still over 4,000,000 bytes at the **last** ladder rung — there is nothing smaller left to try | exhausted | the ladder constants in `game/mapping/v1.json` vs. the measured encode rate in `game/toolchain.json` |
| 12 | `floor` | **The encode collapsed.** The artifact *is* a complete GIF — it is just far too small to be a real clip (at or below `budget.floor_bytes`, 16,000) | **no** — a smaller re-encode makes a collapse smaller, not better | the palette path: the pinned `-pix_fmt bgr0` on the rawvideo input, and the rung's filtergraph in `game/toolchain.json` |
| 13 | `structure` | **The artifact is not the complete output of a GIF writer.** Either it is the wrong *kind* of file (a PNG, an HTML error page saved under a `.gif` name), or the encoder **started a GIF and did not finish it** — a truncated write | **no** — a re-encode cannot complete a file the encoder abandoned | the encoder itself: the pinned ffmpeg binary, its `-f gif` output, whether the rawvideo pipe carried frames, and whether the runner ran out of disk mid-write |

**12 and 13 are not degrees of the same problem.** 12 says *the encoder ran to
completion and the GIF it produced is wrong* — a palette or `pix_fmt` fault, and
the first suspect is the `bgra` / `bgr0` trap that silently renders every pixel
transparent. 13 says *what came out is not a finished GIF*, which points at the
encoder, the pipe, or the runner rather than at the encode recipe. Size is
irrelevant to 13 and central to 12; conflating them sends you to the wrong file.

**Step precedence: the first violated step alone produces the verdict.** An
artifact can violate more than one — a 2,470-byte PNG is both structurally
invalid *and* sub-floor — and the answer is always the lowest-numbered violation,
so that case is **13, never 12**. This is not a tie-break convenience: a non-GIF's
byte count is a property of the wrong file, and reporting it as a floor violation
would send you into the palette path for a fault that is not in the encoder's
colour handling. Size is only a meaningful question once the artifact is
established to be a GIF at all.

> **What exit 13 establishes, and what it leaves open.** The check is
> **head and tail**: the file is non-empty, **begins** with the `GIF89a` magic
> (bytes 0–5) and **ends** with the GIF trailer byte `0x3B`. The magic proves a
> GIF writer *started*; the trailer is the last byte the muxer emits, so it proves
> one *finished*. Two seeks, seven bytes, no decoder. Both constants are read at
> runtime from `game/mapping/v1.json` (`budget.structure.magic_hex`,
> `budget.structure.trailer_hex`), so they are authored once.
>
> This **does** catch truncation, which head-only evidence structurally could not
> — truncation removes bytes from the end, and the magic lives at the start. It
> does **not** prove the block chain between the two ends is intact. Per SPEC §0,
> the residual is stated rather than implied:
>
> - **truncation at an offset that happens to hold a `0x3B` byte** still passes —
>   measured at ~0.3 % of offsets in a reference L0 artifact (2,064 in 705,961
>   bytes). That narrows the hole by roughly two orders of magnitude; it does not
>   close it;
> - **corruption strictly between head and tail** — damaged or interleaved blocks
>   with both ends intact — is not covered. Walking the block chain would put a
>   decoder dependency inside the publish gate, judged disproportionate for a
>   corruption mode this pipeline has never produced;
> - **a structurally complete but visually degenerate GIF** (palette collapse) is
>   deliberately not step 1's job — that is size-detectable and belongs to the
>   floor (exit 12).
>
> So: a green publish gate is good evidence that the encoder finished, and it is
> **not** a guarantee that the GIF is valid. Per §12.1's standing lesson, a clean
> exit code remains the weakest available evidence.

**Diagnose.**

```sh
# The refusal block names the verdict, the size, and the constant it was compared to.
gh run view <run-id> --repo "$REPO" --log-failed | grep -E '^\{"rung"|::error::'
```

The gate emits a machine-readable verdict on stdout before it exits, which the
workflow echoes into the log:

```json
{"rung": "L0", "ceiling": 4000000, "floor": 16000, "publish": false,
 "size": 106, "hard_fail": true, "next": null, "reason": "floor"}
```

**Reproduce locally** against any artifact, without the pipeline:

```sh
python3 game/scripts/budget.py --mapping game/mapping/v1.json --rung L0 --file <path>
echo "exit: $?"   # 0 publish / 10 re-encode / 11 ceiling / 12 floor / 13 structure
```

`--size` substitutes a byte count for a real file, which is the quick way to check
ladder arithmetic without encoding anything. Three things to keep straight:

- **`--size` is never a publication path.** With no artifact behind it, step 1 has
  nothing to read, so structural evidence there is not *skipped* — it is
  unavailable, and a gate that cannot establish its property has not passed it.
  Its exit code is a **size verdict only**. This is why `--size 0` yields **12**
  while a 0-byte *file* yields **13**: two different questions, not a
  contradiction. The workflow's publish step passes `--file` and must keep doing so.
- **The floor is exclusive** (`size > floor` to publish) while the **ceiling is
  inclusive** (`size <= ceiling`). The asymmetry is deliberate.
- **A nonexistent `--file` is a usage error (exit 2)**, not an artifact verdict — a
  malformed invocation is not a malformed artifact.

**Recover.** Fix the cause, then dispatch a run
([section 2](#2-manual-dispatch-drain-re-render-and-unavailable-recovery)). If the
cause was transient, the next sweep drains the backlog within 6 hours.

**Where the predicate lives.** In exactly one place: `game/scripts/budget.py`,
reading its constants from `game/mapping/v1.json`. The workflow does **not**
re-implement it. It used to — a `head -c 6` test in `doom.yml` under a comment
claiming it caught "a 0-byte or truncated GIF" while reading no byte past offset
5 — and that copy was logged as failure instance five in SPEC §12.1. Re-typing a
normative predicate into shell, in a file with no unit tests, is how the same hole
came to exist in two places at once. What the workflow keeps is the *diagnosis*:
the `### Refused: …` summary blocks. If you are tempted to add a "quick check"
before the gate, don't — extend the gate.

---

## 12. Engine replay-equivalence (SPEC §5.9)

**What is pinned.** Not the engine binary's bytes — the **replay**. The gate lives
in exactly one place, `.github/actions/doom-toolchain`: when the engine is built
from source, it replays the committed fixture `game/tests/fixtures/golden.stream`
and checks the recorded framebuffer digest against
`game/tests/fixtures/golden.expected.json`. A binary **restored from cache** does
not pay it — it was already verified byte-exact against the recorded pin, and
byte identity implies behavioural identity.

Every invocation logs one greppable line, whether it passes or fails:

```sh
gh run view <run-id> --repo "$REPO" --log | grep 'doom-toolchain:'
# doom-toolchain: engine-build-sha256=... pin-status=canonical pin-agrees=false
#   origin=built-from-source replay=match replay-sha256=... runner-image=ubuntu24/...
```

### The two things you will actually see

**A. `pin-agrees=false` with `replay=match`, run green.** A *provenance
divergence*, and **not a fault**. The runner image rotated, so the same pinned
commit compiled to different bytes; the replay proved the game is unchanged. The
run proceeds, the action does **not** rewrite the pin (a runtime that re-pins
itself certifies nothing), and it **skips the cache save**, because the key names
a hash the binary does not carry. Nothing is broken and no section is sealed.

The only cost is one rebuild per run until an operator re-pins. Do it at leisure:

```sh
gh run view <run-id> --repo "$REPO" --log | grep -o 'engine-build-sha256=[0-9a-f]*'
# then, in a reviewed commit, set .engine.build_sha256.value to that hash
jq -r '.engine.build_sha256.value' game/toolchain.json
```

Re-pinning is honest housekeeping — it keeps the `build=` written into new
section headers a true record of the binary that will actually render them — not
a repair of anything load-bearing. **Do not** bump `engine.commit_sha`, the WAD
or `mapping_version` to "fix" it: those are sealing pins, and moving one forces
every player to start a new game for an infrastructure event.

**B. `replay=divergent`, job red at *Restore the pinned toolchain*.** A
**toolchain fault**. The engine built from the pinned commit renders *different
frames* from the committed history. This is deliberately a hard failure and not a
seal: its repair is an operator re-pinning a broken build environment, not a
player pressing New game, and sealing it would ask a visitor to discard a live
session to work around a broken runner.

The run takes the **pre-push** row of the write contract (§10) — ledger, stream
and `output` branch byte-untouched, drained issues left open, best-effort
UNAVAILABLE swap — and consecutive failures trip the sweep's owner alert.

```sh
gh run view <run-id> --repo "$REPO" --log-failed | grep -E '::error::|doom-toolchain:'
jq -r '.recorded_stream_sha256' game/tests/fixtures/golden.expected.json
```

Where to look, in order:

1. **The runner image.** Compare `runner-image=` against
   `.engine.runner_image_sensitivity.runner_image`. An image rotation explains a
   changed *binary*; it should **not** change the replay, so a divergence here is
   a genuine finding about the compiler or libc, not routine drift.
2. **The engine commit.** Did `.engine.commit_sha` or `build_cmd_linux` move? A
   deliberate engine bump changes frames by design — but it must land as a
   **sealing-pin** commit, which rolls the section over in band, not as a silent
   rebuild.
3. **The fixture itself.** `fixture-corrupt` (rather than `divergent`) means
   `golden.stream` failed its own `fixture_sha256` — a bad checkout, not a bad
   engine.

Any verdict other than `match` or `byte-identical-pin` fails the job, including
the ones that mean the gate could not be *evaluated* (`gate-input-unavailable`,
`replay-failed`, `no-capture`, `frame-count`). That is intentional: a gate that
cannot establish its property has not passed it (§0), and an absent verdict is
never a passing one.

**Do not** work around a divergence by relaxing the gate or by re-pinning
`build_sha256` — the build hash is provenance and re-pinning it does not touch
what failed. Stop the game
([section 3](#3-emergency-stop-gh-workflow-disable)) and treat it as a bug in the
toolchain pin.

> **Residual (§0.3).** The fixture exercises one input stream through one level
> path (966 tics, 700 recorded frames of continuous run/turn/strafe/fire). A
> binary that diverges only on code the fixture never reaches — a weapon it does
> not fire, a monster it does not meet, a map it does not enter — passes this gate
> and could still fork a live timeline. DOOM's replay path is fixed-point integer
> arithmetic with no wall-clock or floating-point dependence, which is why the
> cross-architecture agreement is as strong as it is, but the remainder is
> narrowed rather than closed. **Re-verify the fixture's coverage whenever the
> engine commit changes.**

---

## Appendix: what the pieces are

| Path | Role |
|---|---|
| `game/state/log.txt` | **The game state.** Append-only sections; the only source of truth. |
| `game/state/stream.txt` | Derived: `expand(ledger)` for the current section. Regenerated every run. |
| `game/mapping/v1.json` | Versioned token→frame table, canonical titles, and every operational knob. |
| `game/toolchain.json` | Engine commit, WAD hash, ffmpeg URL/hashes, runner image **label**, encode recipe — plus the engine build hash, which is **provenance, never a comparand** (§5.9). |
| `game/tests/fixtures/golden.*` | The determinism gate's evidence: one committed input stream and the framebuffer digest it must reproduce (§5.9). Single authoring site for that constant. |
| `game/SPEC.md` | Normative value tables, grammars, and the write contract. |
| `game/scripts/` | All game logic, unit-tested standalone. The workflow only orchestrates. |
| `.github/workflows/doom.yml` | The move loop: gate job + heavy job + sweep. |
| `.github/workflows/ci.yml` | Seven named checks, including `actionlint` and `zizmor`. |
| `.github/actions/doom-toolchain/` | Exact-key cache restore with SHA-256 verify-or-rebuild. |
| `output` branch | Force-pushed, one file (`doom.gif`). Keeps blobs out of the default branch forever. |

### The one feature flag

`.github/workflows/doom.yml` carries `CONTROLS_ENABLED` in the `play` job's
`env:`. It ships `'false'`: every render the workflow produces shows the
placeholder line instead of the control table, which is the cutover mechanic —
the markers and the PAUSED screen go live first, and the controls are switched on
last, in one reviewable one-line commit.

```sh
grep -n 'CONTROLS_ENABLED' .github/workflows/doom.yml
```

Flipping it to `'true'` is what opens the arcade. Flipping it back to `'false'`
is a softer alternative to the emergency stop: the game keeps processing anything
already open, but the README stops handing out new control links. Either way the
next render applies it — no other file changes.

Useful one-liners:

```sh
# Current section header. Sealing compares engine/wad/mapping only; `build` is
# provenance and is never a comparand (SPEC 5.9).
grep '^#section' game/state/log.txt | tail -1

# Last 10 applied moves.
grep -v '^#section' game/state/log.txt | tail -10

# Is a given issue already consumed?
grep -c '#<number>$' game/state/log.txt

# Everything the game will drain on the next run.
gh issue list --repo "$REPO" --state open --search 'doom: in:title' --limit 50
```
