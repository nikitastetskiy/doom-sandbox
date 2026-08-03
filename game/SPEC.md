# Game spec — normative value tables (v1)

Plan-time spec artifact designated by RFC 001 (`.yui-soul/rfcs/approved/001-playable-doom-readme/`, "Normative contracts"). The RFC defines the **shapes** (anchored `\A...\z` full match, ASCII-only, closed enum, bounded count, enumerated reject classes); this file fills the **values**. Consumed verbatim by the parser, expander, rewriter, budget check, drain, workflow gate, control-table renderer, and the E3 test suite. Machine-readable mirror: `game/mapping/v1.json` (`mapping_version: 1`) — on any discrepancy between the two files, treat it as a build error and fix the discrepancy; neither silently wins.

Engine timing basis: DOOM runs at **35 tics/sec**; one doomreplay input frame = one tic. Approximate durations below use 35 fps.

## 0. How this document specifies a gate (normative)

Several sections here define a **gate**: the parse rule (§4), the seal (§5.5), the section cap (§6), the publish gate (§12.1). Each exists because some artifact or input was wrong in a way nothing downstream noticed. Gates have a characteristic failure mode of their own, and this plan has now hit it twice: **a gate gets specified against the instance that prompted it rather than the class it must cover.** The drift is invisible, because the predicate passes its own motivating example and ships.

The second instance is this document's. §12.1 was written after "the gate that was meant to catch them" was logged as failure instance four; §12.1 then named *a truncated GIF* as a motivating case and specified a predicate structurally incapable of detecting one. Naming the right class in the prose did not produce a predicate that covers it, because the enumeration underneath was still a list of rejects.

Therefore a gate in this document is specified as three things, in this order:

1. **The positive property it establishes** — stated as a property an accepted artifact *has*, never as a list of artifacts it turns away. "The file carries the header a GIF encoder writes first and the terminator it writes last" is a property; "the file is not empty and not a PNG" is a list.
2. **The evidence it reads** — the exact bytes, fields, or comparisons, and their cost.
3. **The residual it does not cover** — what can still be wrong in an artifact that passes, and why closing that remainder was judged disproportionate. **A gate with no stated residual is unfinished, not perfect.**

Enumerations of known-bad artifacts are **illustrative only**. They motivate a predicate and they belong in tests; they are never the definition, and a predicate is never complete merely because it rejects every example printed beside it.

**The review question for any new or amended gate**: *does the predicate establish the stated property, or does it only reject the examples named next to it?* If the second, the gate is not specified yet. Applied to §12.1's original step 1: the stated property was "well-formed GIF", the evidence was the leading magic, and the magic cannot speak to any byte after offset 5 — so the property was never established, and the residual (everything after the header) was never written down where a reader could see it.

## 1. Token enum and canonical title literals

Closed set. Title literals are exact byte strings — case-sensitive, single `0x20` space after `doom:` and around `x<count>`, no leading/trailing whitespace.

| Token id | Canonical title literal | Keys/frame | Frames | ~Duration | Repeatable | Control label |
|---|---|---|---|---|---|---|
| `forward` | `doom: forward` | `u` | 18 | ~0.51 s | yes | ⬆️ Forward |
| `back` | `doom: back` | `d` | 18 | ~0.51 s | yes | ⬇️ Back |
| `turn-left` | `doom: turn-left` | `l` | 10 | ~0.29 s (~45–60°) | yes | ⬅️ Turn left |
| `turn-right` | `doom: turn-right` | `r` | 10 | ~0.29 s (~45–60°) | yes | ➡️ Turn right |
| `fire` | `doom: fire` | `f` | 8 | ~0.23 s (≥1 shot) | yes | 🔫 Fire |
| `use` | `doom: use` | `p` | 4 | ~0.11 s (1 press) | no | 🚪 Use |
| `run-forward` | `doom: run-forward` | `su` | 18 | ~0.51 s (~2x distance) | yes | 🏃 Run forward |
| `new-game` | `doom: new game` | — (0 frames) | 0 | — | **no** | 🔄 New game |

- **Menu/quit keys `e`/`x` are unexpandable by construction**: no token maps to them, `game/mapping/v1.json` contains no `e`/`x` key characters, and the expander refuses any mapping entry containing them. Any menu navigation required to get the engine from boot into gameplay is a **fixed engine-invocation constant owned by the toolchain** (`game/toolchain.json` / engine bootstrap, step E2) — it is not part of the public grammar and never appears in the ledger or the expanded stream.
- `new-game` is a **ledger control directive**, not an input expansion: it closes the current section and opens a new one (RFC component 2). It contributes zero frames.

## 2. Repeat syntax and bounds

- Syntax: `doom: <token> x<count>` — exactly one space before `x`, no space inside `x<count>`.
- Bounds: `<count>` is an integer in **[2, 9]** (single ASCII digit; `x1` is invalid — the bare token already means once; `x0`, multi-digit, signed, or padded forms are malformed).
- Repeatable tokens: `forward`, `back`, `turn-left`, `turn-right`, `fire`, `run-forward`. Non-repeatable: `use`, `new-game`.
- Semantics: `x<count>` repeats the token's full frame sequence `<count>` times, concatenated consecutively (e.g., `doom: forward x5` = 90 `u` frames ≈ 2.6 s).

### 2.1 `doom: new game` exact-literal rule (normative)

`doom: new game` admits **no `x<count>` suffix** and no other variation. It is matched as an **exact literal via full-string set membership** — never by tokenizing/splitting the title. `doom: new game x2` is a reject (unlisted-token class), not "new game twice".

## 3. Canonical title set (gate set)

The full canonical set = 8 base literals + (6 repeatable tokens × counts 2–9) = **56 literals**. `game/mapping/v1.json` `canonical_titles` enumerates all 56 explicitly; that array is the single machine source for the workflow's optional `fromJSON` set-membership gate, the control-table renderer, and the self-consistency test. Generation rule (for cross-check only): for each token take its literal; for each repeatable token additionally emit `<literal> x<n>` for n = 2..9.

- **Primary job-level gate** (RFC D15): `startsWith(github.event.issue.title, 'doom: ')` — cheap prefix filter, expression-native. Set membership against the 56 literals is the optional stricter variant; the authoritative match is always the parser script.
- **Informative regex** (the implementation matches by set membership, which is strictly stronger): `\A(doom: (forward|back|turn-left|turn-right|fire|run-forward)( x[2-9])?|doom: use|doom: new game)\z`

## 4. Parse rule and reject classes (values)

Shape per RFC (anchored full match, ASCII-only, no unicode normalization, env/JSON transport only). Values:

- **Title byte cap: 64 bytes.** Longer titles are rejected before matching (GitHub allows ~256; the parser bounds itself).
- Reject classes (each closes with the fixed rejection message; all are E3 test cases): empty title; > 64 bytes; any non-ASCII byte; bare `doom:` or `doom: `; unlisted token; malformed or out-of-bounds repeat (`x1`, `x0`, `x10`, `x05`, `x-3`, missing/extra spaces); prefix + trailing garbage (e.g., `doom: forward && rm -rf` — fails the anchored match); `doom: new game` with any suffix; duplicated/conflicting sequences (any title not byte-equal to a canonical literal).

## 5. Serialization (canonical, byte-exact)

Common rules: **ASCII (UTF-8 subset), LF newlines, files end with exactly one trailing LF**. No tabs; single `0x20` separators.

### 5.1 Files

- `game/state/log.txt` — **the authoritative game state** (RFC D13): a sequence of sections; each section = one header line followed by zero or more ledger lines. Append-only; sections are never truncated or rewritten — one narrow, human-authored exception in **§5.6**, which applies only to a section nobody has played. A section with zero ledger lines is valid (fresh game).
- `game/state/stream.txt` — **derived artifact**: the doomreplay input stream for the **current section only**, regenerated from the ledger on every run (`stream == expand(ledger, mapping_version)` is a CI invariant; on mismatch the stream is regenerated — the ledger wins). Empty section ⇒ empty stream file (zero frames, no commas, single LF).

### 5.2 Section header grammar

One line, space-delimited, exactly 6 fields:

```
#section <n> engine=<40-hex> build=<64-hex> wad=<64-hex> mapping=<int>
```

- `<n>`: section number, decimal, starts at 1, strictly increasing by 1.
- `engine=`: immutable engine commit SHA (40 lowercase hex). `build=`: engine build-artifact SHA-256. `wad=`: `freedoom1.wad` SHA-256 (both 64 lowercase hex). `mapping=`: mapping version (this spec: `1`).
- Any mismatch between the current section's header pins and the running toolchain ⇒ the section is **sealed**: refuse to advance it. The one sanctioned in-band exception is the zero-frame rollover defined in **§5.5**, which is what keeps the RFC's "engine bump ⇒ forced `new game`" reachable without an operator.

### 5.3 Ledger line grammar

One line per accepted move, space-delimited, exactly 5 fields, in RFC-mandated order:

```
<YYYY-MM-DDTHH:MM:SSZ> <handle> <token-id> <count> #<issue-number>
```

- Timestamp: UTC, second precision, literal `T`/`Z`. Handle: `[a-zA-Z0-9-]{1,39}` (sanitized; never `@`-prefixed). Token id: from the closed set in section 1 (ids, not title literals — ids contain no spaces). Count: decimal `1`–`9` (`1` = no suffix; `new-game` and `use` are always `1`). Issue number: `#` + decimal — **the exactly-once idempotency key (RFC D14)**.
- Example: `2026-07-30T14:02:11Z nikitastetskiy forward 5 #17`
- Example (reset): `2026-07-30T15:00:00Z somevisitor new-game 1 #23` — immediately followed by the next section's header line.

### 5.4 Frame-stream grammar

doomreplay input format: frames separated by `,`; a frame is zero or more key characters from `{u,d,l,r,f,p,s,<,>,0-9}` (v1 expansions use only `u,d,l,r,f,p,s`).

- **Canonical multi-key order: ascending ASCII byte order within a frame** (thus run-forward is `su`, never `us`).
- **No trailing separator**: a stream of N frames contains exactly N−1 commas. The file ends with one LF, no comma before it.
- **Empty frame**: zero characters between separators. **Worked example: `u,,u` is exactly 3 frames** — frame 1 = `u`, frame 2 = no keys, frame 3 = `u`. The grammar admits empty frames; v1 token expansions never emit them (every token's sequence is non-empty), so an empty frame in a v1-generated stream is a consistency-check failure.
- Stream generation: concatenate each ledger line's expansion (frames × count) in ledger order, joined with single `,`; **no inter-move padding frames**.
- Worked example: ledger lines `fire 1` then `turn-left 2` ⇒ `f,f,f,f,f,f,f,f,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l,l` (8 + 20 = **28 frames, 27 commas**).

### 5.5 Pin mismatch: sealed sections and the sanctioned zero-frame rollover (normative)

A section is **sealed** when any field of its header (`engine`, `build`, `wad`, `mapping`) does not match the running toolchain. Sealing is computed at run time by comparing the current section's header against `game/toolchain.json`; it is never configured or stored.

**Why this rule exists.** §5.2 requires refusal on a pin mismatch; the RFC requires an engine (or mapping) bump to force a `new game`. Because §5.3 places the `new-game` directive as the **last line of the closing section**, a literal refusal would block the very recovery the RFC prescribes, leaving the game permanently unable to advance without a human hand-editing committed state. The rule below satisfies both.

**The rule.**

1. **Sealed sections never advance and are never re-simulated.** No line that contributes frames may be appended to a sealed section. Its `stream.txt` is not regenerated and the section is not replayed while sealed. Its committed pins are preserved verbatim — a sealed section always remains reproducible against the archived build that produced it.
2. **The sole admissible move is `doom: new game`.** It contributes **zero frames** (§1), so it provably cannot alter the sealed section's replay output and therefore cannot fork the timeline. It is appended as that section's final line, and the next section header is written with the **running** toolchain's pins — this is the only legitimate way a pin change enters the log.
3. **Everything else is rejected, not fatal.** In sealed mode the drain closes every other valid move with the fixed message **`the arcade is being upgraded — press New game to continue`** (verbatim, no interpolation) and the `sealed` reason code — the same mechanics already used at the section cap (§6, `log full`). Rejection, not run failure, is required: refusing the batch would livelock the loop, because the drain processes issues in ascending number order, so a lower-numbered frame-contributing issue would be re-drained and re-refused on every subsequent run, forever.
4. **Defense in depth.** `game/scripts/apply_moves.py` independently enforces invariant 1: if any frame-contributing line would land in a sealed section it **refuses with exit code 7** and leaves the ledger byte-unchanged, even though correct drain behavior means it should never see such a batch. A frame-contributing move ordered *ahead* of a reset in the same batch is refused by this path.
5. **Moves after the rollover apply normally.** Once the reset opens a fresh section, that section's pins match the running toolchain by construction, so later moves in the same batch land in it and are simulated normally.
6. **Recovery is always reachable**: the `new game` cooldown (§6) does **not** apply while the current section is sealed. A sealed game cannot advance, so the cooldown's purpose — preventing reset-griefing of a live game — is inapplicable, and a visitor cannot induce a mismatch (pins change only through a default-branch commit).
7. **Player-visible state.** While sealed, the README game block shows the **SEALED** guidance screen (§11). A run that **appends no ledger line to a sealed section** is a **successful run with zero ledger appends**: it performs a display-only swap to SEALED and commits no game state (§10). The governing property is "no frame-contributing line landed", not "a rejection was issued" — the sealed-reject batch of rule 3, a batch that is entirely duplicates (§5.3 idempotency key), and a batch with nothing admissible in it at all are the *same* case and take the *same* path. In particular rule 1's prohibition is **unconditional**: `stream.txt` is not regenerated in any of them. Regeneration is never contingent on whether the run had something to reject — a sealed section is never re-simulated, full stop.

**Rollover recovery render.** The fresh section is empty, so the recovery run replays zero frames and renders the game-start view — the same path already exercised by the initial committed state (§5.1).

**Alternative considered and rejected.** Moving the `new-game` directive to the *first* line of the opening section would dissolve the contradiction without an exception. Rejected: it rewrites the §5.3 serialization contract that committed tests and implementation already encode, it degrades the audit trail (the new section's first line would describe an event that preceded its existence), and it does not remove the need for degraded-mode handling of frame-contributing moves anyway.

### 5.6 Authoring exception: re-initializing an entry-less section (normative)

A section with **zero ledger lines** contains no player history: its replay output is empty under any pins, so rewriting its header rewrites nothing anyone played and cannot alter any rendered frame. For that section only, the header may be **re-initialized in place** — pin fields updated, section number preserved, no new section created.

Strictly bounded:

1. **Human-authored only — never a runtime behavior.** The workflow, drain, and `apply_moves.py` must never re-initialize a header. Their only recovery is the §5.5 rollover, so the automated path stays single-pathed and self-healing.
2. **Preconditions, all required**: the target section has zero ledger lines **and** is the last section in the file. Otherwise the §5.5 rollover applies.
3. **Authorized commit.** Re-initialization lands in an explicit, reviewed commit that also updates the toolchain pins it is aligning to — the header and `game/toolchain.json` move together, or the run that follows is sealed again for the same reason.
4. **The append-only guarantee is unweakened.** It exists to protect played history; an entry-less section has none. No section that ever held a ledger line may be rewritten, ever.

**First application (plan D9 / step E7).** The committed section 1 is entry-less and carries a provisional macOS `build=` hash, so the first `ubuntu-24.04` run seals it on the `build` field before any move can apply. The canonical capture re-initializes that header in the same authorized commit that records the canonical build hash in `game/toolchain.json`. Preferred over burning a rollover: it keeps section numbering meaningful (a section 2 here would record "the toolchain changed before anyone played"), and it spares the profile's first-ever visitor a rejection message.

**The rollover remains the guarantee.** If an entry-less section is ever left un-re-initialized — at cutover or after any future bump — §5.5 still heals it in band without an operator. §5.6 is an optimization for the authoring case, never a dependency.

### 5.7 Drain reason codes (normative closed enum)

Every drained issue closes with exactly **one** reason code. The workflow branches on these codes — `section-cap` selects the LOG_FULL state screen and `sealed` selects SEALED (§11) — so the code, not the player-visible prose, is the machine contract. **No consumer may string-match a player-visible message**: those are written for humans and may be reworded; the codes may not.

| Reason code | Issue action | Emitted when | Player-visible message |
|---|---|---|---|
| `applied` | `close-applied` | the move parsed, passed every guard, and its ledger line landed | receipt (§10) |
| `duplicate` | `close-duplicate` | the issue number is already present in the ledger — the §5.3 exactly-once idempotency key (RFC D14) | receipt |
| `grammar` | `close-reject` | the title failed the §4 parse rule (any reject class) | fixed rejection message (§4) |
| `cooldown` | `close-reject` | a `new game` inside the §6 cooldown window; never applies while sealed (§5.5 rule 6) | fixed cooldown message |
| `section-cap` | `close-reject` | the section is at the §6 log-section cap; only `doom: new game` is accepted | `log full — start a new game` (§6, verbatim) |
| `sealed` | `close-reject` | the current section is sealed by a pin mismatch (§5.5 rule 3) | `the arcade is being upgraded — press New game to continue` (§5.5, verbatim) |

- **Closed set of six.** The enum is exhaustive: a drained issue that matches no row is a bug, not a seventh outcome. Adding a code is a spec change, and it lands here, in `game/mapping/v1.json` `reason_codes`, and in the drift guard together.
- **Reason and action never disagree**, because the action is *derived* from the reason rather than passed alongside it — one field cannot drift from the other if only one is authored.
- **Reason codes are run-local diagnostics.** They are carried in the drain's JSON output and in receipts; they are **never serialized into `game/state/log.txt` or `game/state/stream.txt`** (a ledger line is exactly the 5 fields of §5.3). They are therefore **not** section 1/2/5 *values*, and mirroring an already-implemented code into the mapping does **not** bump `mapping_version` and does **not** force a `new game`. Changing a code's *string*, however, changes a runtime contract the workflow reads, and requires the same coordinated commit as any other mirrored constant.

## 6. Knob values (RFC OQ5 — resolved here, not post-launch)

| Knob | Value | Notes |
|---|---|---|
| `new game` cooldown (RFC D16) | **30 minutes** | Resets within 30 min of the last applied reset are rejected with the fixed message. **Does not apply while the current section is sealed** (§5.5 rule 6) — the sanctioned rollover is always immediately reachable |
| Per-user move cooldown | **0 (disabled in v1)** | Valid-move floods are "someone playing"; drain amortizes. Knob exists in config, default off |
| Per-run drain cap | **20 issues** | ≈ 60 receipt writes worst case — under the 80/min secondary content-write limit |
| Log-section cap | **120,000 expanded frames** (unit: engine frames ≈ 57 min gameplay) | At cap, only `doom: new game` is accepted; others get the fixed guidance comment ("log full — start a new game") |
| Push retry attempts | **3** (fetch → reset → regenerate → commit → push) | Then fail per the write contract |
| Sweep cron | **`17 */6 * * *`** (every 6 h at :17) | Off-peak minute to dodge busy-window delivery lag; no-ops cheaply when idle |
| Sweep owner-alert threshold | **2 consecutive failed heavy runs** | Opens/updates the maintenance issue assigned to Nik |
| Trailing-24h abuse run-count threshold | **200 workflow runs / 24 h** | Sweep flips README to PAUSED and alerts (RFC must_have 7 defense) |
| Idle-to-PAUSED threshold | **45 days** | Days since the last game-state commit before the sweep swaps the block to PAUSED (§11). Comfortably inside the 60-day scheduled-workflow auto-disable, so the swap always happens while the workflow is still alive to perform it. Mirrors `knobs.idle_pause_days` |
| Title byte cap | **64 bytes** | Section 4 |
| Receipt degradation trigger | **first secondary-limit 403 in a run** ⇒ drop reactions for the rest of the run; **second 403** ⇒ drop comments too | Issue closes are always attempted; a failed close is retried next run as close-only cleanup (never decoupled from the ledger) |

## 7. Latency measurement (must_have 3)

- **Metric**: issue `created_at` → committer timestamp of the game-state push to `main` (the commit that appends the move's ledger line).
- **Window**: trailing **20 accepted moves**, p50.
- **Defect rule**: trailing-window p50 > **3 minutes** = sustained defect. Target < 2 min; stretch (non-blocking) p50 < 60 s.

## 8. Death and level-exit semantics (RFC OQ4, plan D8 — resolved)

**Engine-native, no auto-section.** On death the engine shows the death view; DOOM natively restarts the level on a subsequent key press, so `doom: use` or `doom: fire` respawns — no special casing. Level exits proceed natively into the next level within the same section. `doom: new game` (cooldown-guarded, section 6) is always available as the explicit reset. No automatic section rollover on death or level exit.

## 9. Control-table rendering (plan D5)

- Rendered **only** by `game/scripts/rewrite_readme.py` from `game/mapping/v1.json` (self-consistent by construction — the self-consistency test parses every rendered title).
- Layout: **3 columns**, 4 rows (mobile-safe per RFC profile-page constraints). Cells link to `https://github.com/nikitastetskiy/nikitastetskiy/issues/new?title=<url-encoded canonical literal>&body=Just%20press%20Submit%20%E2%80%94%20your%20move%20runs%20automatically.`
- Rendered links (12, in this order): `forward`, `forward x5`, `run-forward x5`, `back`, `turn-left`, `turn-right`, `turn-left x3`, `turn-right x3`, `fire`, `fire x3`, `use`, `new game`. Labels/emoji per section 1 (repeat links append ` x<n>` to the label).
- `--controls-enabled` flag (cutover stage 1): when disabled, the rewriter renders this exact placeholder line instead of the table: `🕹️ Controls are being wired up — the arcade opens soon.`

## 10. Failure-path write contract (implementation table)

Copied from RFC 001 ("Failure-path write contract", normative there), with the game-state-push-failure cell amended per Rin's round-1 re-verify note. Game state = ledger (`main`) + GIF (output branch); display state = README marker block.

| Outcome | Ledger (`main`) | GIF (output branch) | README game block | Move issues | Recovery |
|---|---|---|---|---|---|
| Success | Appended + pushed | Pushed (before `main`) | → LIVE, same game-state commit | Closed + receipt, strictly after push | — |
| Pre-push failure (parse/sim/encode/budget) | Untouched | Untouched | Best-effort display-only swap → UNAVAILABLE (must itself pass marker validation; its own push may fail — tolerated) | Left open | Sweep or next move re-renders → LIVE |
| Marker-validation failure | Untouched | Untouched | **No write — swap suppressed** | Left open | Operator repairs markers (runbook); fail-safe brick |
| Game-state push failure (after 3 retries) | Not landed | **May have landed — mostly harmless with one honest caveat**: the GIF already on the output branch means the old-buster URL can transiently serve a frame ahead of the committed ledger after Camo TTL; converges to correctness next run since the same open issues re-append in the same ascending order | Best-effort swap → UNAVAILABLE | Left open | Sweep / manual dispatch / next move |
| Post-push failure (close/receipt/reaction) | Landed | Landed | **Already LIVE — never overwritten** | Closed next run as close-only cleanup (idempotency key) | Automatic, next run |
| Runner loss / cancelation / infra kill | Untouched | Untouched | No step runs ⇒ no swap; prior frame remains accurate | Left open | Sweep or next move |

Degraded-mode note (§5.5, §6 cap): a run whose drained moves are **all** rejected — every move sealed-rejected, or cap-rejected at the section cap — is a **success** outcome with zero ledger appends and no GIF publish. It closes the rejected issues with their fixed guidance message and performs a display-only swap to SEALED or LOG_FULL. It is not a failure row above: nothing failed, and no game state was eligible to change.

## 11. State screens (v1)

- **LIVE** — the game GIF (normal state after a move).
- **PAUSED** — default "press play" idle state (swapped by the sweep after inactivity, well before the 60-day scheduled-workflow auto-disable).
- **UNAVAILABLE** — failure/limit guard. Semantics: **"moves are not being processed right now"** — not "the frame is wrong"; an untouched prior frame is still accurate history.
- **LOG-FULL guidance** (`LOG_FULL`) — shown at the section cap: only `doom: new game` accepted.
- **SEALED guidance** (`SEALED`) — shown while the current section is sealed by a pin mismatch (§5.5): only `doom: new game` accepted, and it is exempt from the cooldown. Distinct from UNAVAILABLE (moves *are* being processed) and from LOG_FULL (the section is not full — its toolchain moved). Adds one rewriter state value, one screen asset, and one drain reason code, parallel to LOG_FULL in every respect.
- **LOADING** — defined but **off by default in v1** (costs an extra push per move).

## 12. GIF budget constants (RFC D7)

- **Hard byte ceiling: 4.0 MB = 4,000,000 bytes** (single exact constant; under the 5 MB Camo reference cap with headroom).
- **Hard byte floor: 16,000 bytes** (mapping `budget.floor_bytes`). An artifact at or below the floor is treated as a **broken encode, never as a small one**.
- Re-encode ladder (checked-in budget script; hard-fail, no publish, if L2 still exceeds the ceiling):
  - **L0**: 15 s tail @ 320 px wide / 12 fps / 128 colors (bayer dithered)
  - **L1**: 12 s tail @ 320 px / 12 fps / 128 colors
  - **L2**: 12 s tail @ 256 px / 10 fps / 64 colors
### 12.1 Publication requires positive structural evidence (normative)

The publish gate must **affirmatively establish that the artifact is a well-formed, non-degenerate GIF**. The absence of a ceiling violation is not evidence of anything: a 0-byte file, a truncated file, and a palette-collapsed file all satisfy "not too large". This plan has now produced **five** failure instances in which exit status and byte count both reported success while the artifact was wrong: `bgr0` palette collapse, the title-screen preamble, the 0-byte GIF, the gate that was meant to catch them, and — instance five — **this section's own first predicate**, which named a truncated GIF as its motivating case and then specified head-only evidence, which cannot detect one. Verified 2026-08-03 against the committed gate: a 1.5 MB file consisting of a valid `GIF89a` header followed by unterminated data returned **exit 0, publish: true**. **Treat a clean exit code as the weakest available evidence** — and treat a gate's own prose about what it catches as no evidence at all until the predicate is checked against it (§0).

Gate order, all three required before publication:

1. **Structural validity** — *positive property*: the artifact is the **complete** output of a GIF writer. *Evidence*: the file exists, is non-empty, **begins** with the `GIF89a` magic (bytes 0–5) **and ends** with the GIF trailer byte `0x3B`. Head **and** tail, because the two ends establish different halves of the property and neither substitutes for the other: the magic proves a GIF writer **started**; the trailer is the last byte the GIF muxer emits, so it proves a writer **finished**. Head-only evidence is structurally incapable of detecting truncation — truncation removes bytes from the *end*, and the magic lives at the *start*, so no amount of care in reading the header can speak to a single byte after offset 5. *Cost*: two seeks and seven bytes; no decoding, no dependency, the same **kind** of evidence as the magic rather than a new class of check. Constants are mirrored in `game/mapping/v1.json` (`budget.structure.magic_hex`, `budget.structure.trailer_hex`) and read at runtime, so the literal is authored once rather than repeated in the script, the workflow, and this file. May additionally be enforced in the workflow (where it fails faster and logs better), but `budget.py` enforces it **independently and unconditionally** before any size verdict — the script never assumes an upstream gate ran. Same defense-in-depth precedent as §5.5 rule 4.
2. **Floor** — `size > floor_bytes` (§12).
3. **Ceiling / ladder** — `size <= ceiling_bytes`, otherwise descend the ladder (§12).

**What step 1 does not establish (residual, per §0.3).** Head-and-tail evidence proves a writer started and finished. It does **not** prove the block chain between them is intact. Three things can still be wrong in an artifact that passes:

- **(a) Truncation at an offset whose byte happens to be `0x3B`.** Measured at ~0.3 % of offsets in a reference L0 artifact (2,064 occurrences in 705,961 bytes), so this narrows the truncation hole by roughly two orders of magnitude rather than closing it. A partially written encode essentially never stops there, but it can.
- **(b) Corruption strictly between head and tail** — damaged or interleaved blocks with both ends intact.
- **(c) A structurally complete but semantically degenerate GIF** — palette collapse, blank frames. Deliberately **not** step 1's job: that failure is size-detectable and belongs to the floor (§12), and its root cause is prevented upstream by the pinned `bgr0` input declaration (`game/toolchain.json`).

Closing (a) and (b) requires walking the GIF block chain — a decoder dependency inside the publish gate, run against an artifact the same job produced seconds earlier. **Rejected as disproportionate**: it adds a dependency and a new failure surface of its own to cover a corruption mode this pipeline has never produced, whereas truncation — a partially written encode — is a mode it *can* produce, and head-and-tail does catch it. Revisit if an artifact that passed this gate is ever observed to render broken.

**Step precedence.** The steps are ordered and **the first violated step alone produces the verdict.** An artifact may violate more than one — a 2.4 KB PNG is both structurally invalid and sub-floor — and the verdict is the lowest-numbered violation: `13`, never `12`. This is not a tie-break convenience. The exit codes name *different faults with different first debugging steps* (below), and structural invalidity is the **upstream** fault: a non-GIF's byte count is a property of the wrong file, so reporting it as a floor violation would send the operator into the palette/`pix_fmt` path for a problem that is not in the encoder's colour handling. Size is only a meaningful question once the artifact is established to be a GIF at all.

**`--size` is not a publication path.** `--size` asserts a byte count with no artifact behind it, so step 1 has nothing to read. Structural evidence there is not *skipped* — it is **unavailable**, and by §0 a gate that cannot establish its property has not passed it. Therefore: **a publication decision is made only from `--file`.** `--size` is a tuning and diagnostic entry point (ladder arithmetic, threshold checks) and its exit code is a **size verdict only**. This is why `--size 0` yields `12` while a 0-byte *file* yields `13`: not a contradiction, but two different questions — the first asks "is this number below the floor?", the second asks "is this artifact a GIF?". The workflow's publish step passes `--file` and must continue to.

**`GIF89a` is matched exactly, and that is a declared toolchain dependency.** The version block is not wildcarded to also accept `GIF87a`. The pinned encoder (`game/toolchain.json` `ffmpeg`, invoked `-f gif`) writes the 89a block unconditionally — verified 2026-08-03 on ffmpeg 8.1.2 with the §12 L0 filtergraph, which produced a `GIF89a`-headed, `0x3B`-terminated artifact — so an 87a file is not something this pipeline can emit, and an artifact that is *not what the pinned toolchain produces* is itself the structural fault this gate exists to catch. Widening the match would trade real evidence for compatibility with an encoder this repository does not use. **Re-verify if the encoder, its version pin, or the `-f gif` muxer changes** — the same re-verify discipline the floor carries (§12).

**Floor violation behavior**: `size <= floor_bytes` is a **hard failure — exit code 12, no publish, and no ladder descent**, regardless of the current rung. The ladder exists to make oversized output smaller; descending a rung on an undersized artifact makes it *smaller still*, which cannot repair it and merely burns encodes. A sub-floor artifact is evidence that the encode is broken (collapse, truncation, zero-length), not that it is mis-tuned. The run then takes the **pre-push failure** path of the write contract (§10): game state untouched, best-effort UNAVAILABLE swap, issues left open, next run retries.

**Structural failure behavior**: an artifact that fails to establish the step 1 property — empty, missing the `GIF89a` head, or missing the `0x3B` tail — is a **hard failure — exit code 13**, no publish, no ladder descent, `reason: "structure"`. It is deliberately *not* folded into the floor verdict, because **structural validity is orthogonal to size**. Folding would be correct only for the 0-byte case, where `0 <= floor_bytes` holds by coincidence; a *large* malformed artifact — a truncated GIF, or the wrong file entirely (a PNG, an HTML error page) — clears both floor and ceiling and would **publish**. That is the precise hole this section exists to close, and until the trailer check was added it was only half closed: the wrong-file half was caught, the truncation half published. It would also mislabel a 1.5 MB truncated file as a floor violation.

A **nonexistent `--file` path remains a usage error (exit 2)**: that is a malformed invocation, not a malformed artifact.

Operator meaning, and the reason these are separate integers: **13 = the encoder emitted garbage or the wrong file** (pipeline or toolchain fault); **12 = the encoder emitted a well-formed but degenerate clip** (palette or `pix_fmt` fault). Different first debugging step.

Emitted JSON on a hard failure carries `"hard_fail": true`, `"next": null`, and a `"reason"` of `"structure"`, `"floor"`, or `"ceiling"` so the workflow can branch and the operator can diagnose without reading logs. The floor is reported alongside the ceiling in the gate's output.

**Choosing 16,000 bytes.** Measured reference points: a legitimate single-frame still ≈ **46 KB**; a legitimate 18-frame clip ≈ **276 KB**; the recorded palette-collapse signature ≈ **a few KB** (GIF inter-frame differencing keeps a collapsed clip tiny no matter how many frames it holds, which is exactly why length is not a usable discriminator). 16,000 bytes sits near the geometric centre of that band — roughly 2x above the collapse signature and ~2.9x below the smallest legitimate artifact. Both error directions are loud rather than silent, but they are not symmetric: a false positive refuses one publish, turns the block UNAVAILABLE, alerts via the sweep, and self-heals on the next move; a false negative ships a blank frame to a visitor with everything upstream reporting success. The floor is therefore biased toward catching collapses. Re-verify if the ladder rungs or `pix_fmt` change.

- Ladder constants adjusted in E2 (2026-07-30) per the RFC's plan-time re-verify (Sho S2): worst-case
  active-play encode rate measured at ~248–267 KB/s with the pinned static ffmpeg (n8.1.2) — not the
  provisional ~150 KB/s — so a 20 s L0 tail measured **5.33 MB > 4.0 MB ceiling** and would never publish.
  Measured sizes at the adjusted rungs on the same worst-case fixture content: L0 = 3.71 MB, L1 = 2.64 MB,
  L2 = 1.37 MB. The 15 s L0 stays within the RFC's resolved 15–20 s tail range; ceiling and ladder shape
  unchanged (normative). Exact encode recipe and full measurement table: `game/toolchain.json`.

---

Mapping version: **1**. Any change to section 1, 2, or 5 values bumps `mapping_version`, records it in new section headers, and — like an engine bump — forces `new game` (RFC Normative contracts 3).
