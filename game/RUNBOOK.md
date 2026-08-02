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

**This is the guard working, not a fault.** A section is *sealed* when any pin in
its header — `engine`, `build`, `wad`, `mapping` — no longer matches the running
toolchain, which happens whenever the engine, the WAD, the mapping version or the
recorded build hash is bumped. Rather than append moves to a section it can no
longer reproduce, the game refuses to advance that section and says so. Sealing
is computed at run time by comparison; it is never stored or configured, so there
is no flag to unset.

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
jq '{engine: .engine.commit_sha, wad: .wad.sha256,
     build: .engine.build_sha256.value, build_status: .engine.build_sha256.status}' game/toolchain.json
jq -r '.mapping_version' game/mapping/v1.json
```

A `build` that differs while `engine` matches usually means the recorded engine
build hash is still the provisional local value and the canonical `ubuntu-24.04`
hash has not been captured yet.

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
| Sealed with no toolchain change | check recent commits to `game/toolchain.json` and `game/mapping/v1.json` |
| Sealed before anyone has ever played | expected while the build hash is provisional; the first reset clears it |

For the first two, stop the game
([section 3](#3-emergency-stop-gh-workflow-disable)) and treat it as a bug.

**What not to do.** Do not hand-edit `game/state/log.txt`, and do not rewrite a
section header to make the pins agree. The rollover is the only runtime recovery
and it is designed to need no privileged intervention; editing authoritative
committed state to step around a guard is precisely how a timeline forks. If the
pins themselves are wrong, fix `game/toolchain.json` (or revert the bump) and let
a reset roll the section over.

---

## Appendix: what the pieces are

| Path | Role |
|---|---|
| `game/state/log.txt` | **The game state.** Append-only sections; the only source of truth. |
| `game/state/stream.txt` | Derived: `expand(ledger)` for the current section. Regenerated every run. |
| `game/mapping/v1.json` | Versioned token→frame table, canonical titles, and every operational knob. |
| `game/toolchain.json` | Determinism pins: engine commit + build hash, WAD hash, ffmpeg URL/hashes, runner label, encode recipe. |
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
# Current section header (engine/build/WAD/mapping pins in force).
grep '^#section' game/state/log.txt | tail -1

# Last 10 applied moves.
grep -v '^#section' game/state/log.txt | tail -10

# Is a given issue already consumed?
grep -c '#<number>$' game/state/log.txt

# Everything the game will drain on the next run.
gh issue list --repo "$REPO" --state open --search 'doom: in:title' --limit 50
```
