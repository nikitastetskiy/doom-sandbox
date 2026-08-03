# Game spec — normative value tables (v1)

Plan-time spec artifact designated by RFC 001 (`.yui-soul/rfcs/approved/001-playable-doom-readme/`, "Normative contracts"). The RFC defines the **shapes** (anchored `\A...\z` full match, ASCII-only, closed enum, bounded count, enumerated reject classes); this file fills the **values**. Consumed verbatim by the parser, expander, rewriter, budget check, drain, workflow gate, control-table renderer, and the E3 test suite. Machine-readable mirror: `game/mapping/v1.json` (`mapping_version: 1`) — on any discrepancy between the two files, treat it as a build error and fix the discrepancy; neither silently wins.

Engine timing basis: DOOM runs at **35 tics/sec**; one doomreplay input frame = one tic. Approximate durations below use 35 fps.

## 0. How this document specifies a gate (normative)

Several sections here define a **gate**: the parse rule (§4), the seal (§5.5), the section cap (§6), the publish gate (§12.1). Each exists because some artifact or input was wrong in a way nothing downstream noticed. Gates have a characteristic failure mode of their own, and this plan has now hit it twice: **a gate gets specified against the instance that prompted it rather than the class it must cover.** The drift is invisible, because the predicate passes its own motivating example and ships.

The second instance is this document's. §12.1 was written after "the gate that was meant to catch them" was logged as failure instance four; §12.1 then named *a truncated GIF* as a motivating case and specified a predicate structurally incapable of detecting one. Naming the right class in the prose did not produce a predicate that covers it, because the enumeration underneath was still a list of rejects.

Therefore a gate in this document carries five obligations. The first three are what the specification must **state**, in this order:

1. **The positive property it establishes** — stated as a property an accepted artifact *has*, never as a list of artifacts it turns away. "The file carries the header a GIF encoder writes first and the terminator it writes last" is a property; "the file is not empty and not a PNG" is a list.
2. **The evidence it reads** — the exact bytes, fields, or comparisons, and their cost.
3. **The residual it does not cover** — what can still be wrong in an artifact that passes, and why closing that remainder was judged disproportionate. **A gate with no stated residual is unfinished, not perfect.** A stated residual is also what lets two gates **compose**: §12.1's floor demonstrably narrows the structural gate's remainder, and that could only be written down because the remainder had been written down first.

The remaining two are things the specification must **be true of**. Both were violated in this plan before they were written here, and neither is visible in a predicate read on its own:

4. **The property must be observable, including on a run that does nothing.** Stating a property normatively is not implementing it. Some output the system actually produces must **witness** the property, and the witness must exist in **every** state where the property can hold — not only in the states that happen to generate other traffic. The characteristic trap is a witness that is a by-product of activity: it is present exactly while something is happening and absent exactly when the system is quiet, which is when a stuck state most needs to be visible and least likely to be noticed. **The test is one question: if this run drains nothing, applies nothing and produces nothing, can a consumer still tell whether the property holds?** If not, the property is stated but not implemented — and no test will catch it, because a test that exercises the property must first arrange for something to happen, which manufactures the very witness the quiet case lacks. So: name the output that carries the witness, and say whether it is emitted unconditionally.
5. **A gate has exactly one implementation site.** The predicate is implemented once, by the component that owns the property. Every other consumer reads that component's **verdict** and never recomputes its predicate. A second copy is not defense in depth: depth means an *independent* invariant, checked at a *different* layer, against *different* evidence (§5.5 rule 4 re-checks the ledger the drain already screened; §12.1 step 1 re-checks the artifact the workflow already saw). Retyping the same comparison in a second language is not that — it has no test of its own, it drifts on the first amendment, and it turns one bug into two: the fix lands on the owning implementation, the copy stays wrong, and the prose claims both are covered. Constants a predicate reads are mirrored in `game/mapping/v1.json` and read at runtime for the same reason — authored once, not repeated in the script, the workflow, and this file. **A consumer that needs to know whether a property holds asks for the verdict; it does not re-derive the comparison.** A second copy that reads a *different comparand* for the same pin is the worst form of it, and §5.9 records the instance: the two copies disagreed about what "the running build" meant, and the disagreement composed into a livelock neither copy could be read to predict.

**Corollary to obligation 4 — a witness must be readable by a consumer that was not watching.** Emitting a value is not the same as recording it. A witness that survives only in a rendering no machine can fetch afterwards is a witness to whoever happened to be looking, which is nobody by the time it matters. The instance: the golden-frame job exists to produce exactly one number — the canonical engine build hash — and wrote it **only** to `$GITHUB_STEP_SUMMARY`, which no REST endpoint returns (`check-runs/{id}.output.summary` is null for Actions jobs), so the single value the job exists to produce was retrievable by eye and by no other means. Therefore: the witness goes somewhere a consumer can fetch after the run ends — for a CI job, one greppable line in the run log — and it carries enough of its own provenance to be worth reading later (**what** was observed, **where** it came from, and **on what**: `origin=` distinguishes a compiled binary from a restored one, `runner-image=` names the image that produced it). Human-readable renderings are additional, never the record. This is obligation 4 applied to a job rather than to a run, and it generalizes: any value a gate is *for* must outlive the gate's own execution in machine-readable form.

Enumerations of known-bad artifacts are **illustrative only**. They motivate a predicate and they belong in tests; they are never the definition, and a predicate is never complete merely because it rejects every example printed beside it. The same applies to obligations 4 and 5: the instances that produced them — a sealed section that could not swap its own screen because the only witness was a rejection, and a truncation predicate that existed in both `budget.py` and a shell copy in the workflow so that closing the hole in one left it open in the other — motivate the rules and do not bound them.

**The review questions for any new or amended gate**, all three:

1. *Does the predicate establish the stated property, or does it only reject the examples named next to it?* If the second, the gate is not specified yet. Applied to §12.1's original step 1: the stated property was "well-formed GIF", the evidence was the leading magic, and the magic cannot speak to any byte after offset 5 — so the property was never established, and the residual (everything after the header) was never written down where a reader could see it.
2. *What output witnesses the property on a run where nothing happens?* Applied to §5.5 rule 7: the answer was "none", because the `sealed` reason code requires a move to reject — which is why §5.8 exists.
3. *How many places implement this predicate?* The only acceptable answer is one.

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
- `engine=`: immutable engine commit SHA (40 lowercase hex). `build=`: engine build-artifact SHA-256 — **provenance, never a comparand** (§5.9). `wad=`: `freedoom1.wad` SHA-256 (both 64 lowercase hex). `mapping=`: mapping version (this spec: `1`).
- The **sealing pins** are `engine`, `wad` and `mapping` (`game/mapping/v1.json` `sealing_pins`). A mismatch between any of them and the running toolchain ⇒ the section is **sealed**: refuse to advance it. `build` is deliberately *not* among them: it identifies the binary that produced this section's frames, and **§5.9** establishes that the replay, not the binary's bytes, is what determinism pins on. The one sanctioned in-band exception is the zero-frame rollover defined in **§5.5**, which is what keeps the RFC's "engine bump ⇒ forced `new game`" reachable without an operator.

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

A section is **sealed** when any of its header's **sealing pins** (`engine`, `wad`, `mapping` — §5.2, mirrored as `game/mapping/v1.json` `sealing_pins`) does not match the running toolchain. `build` is excluded by **§5.9** and is never a comparand anywhere. Sealing is computed at run time by comparing the current section's header against `game/toolchain.json`; it is never configured or stored.

**Why this rule exists.** §5.2 requires refusal on a pin mismatch; the RFC requires an engine (or mapping) bump to force a `new game`. Because §5.3 places the `new-game` directive as the **last line of the closing section**, a literal refusal would block the very recovery the RFC prescribes, leaving the game permanently unable to advance without a human hand-editing committed state. The rule below satisfies both.

**The rule.**

1. **Sealed sections never advance and are never re-simulated.** No line that contributes frames may be appended to a sealed section. Its `stream.txt` is not regenerated and the section is not replayed while sealed. Its committed pins are preserved verbatim — a sealed section always remains reproducible against the archived build that produced it.
2. **The sole admissible move is `doom: new game`.** It contributes **zero frames** (§1), so it provably cannot alter the sealed section's replay output and therefore cannot fork the timeline. It is appended as that section's final line, and the next section header is written with the **running** toolchain's pins — this is the only legitimate way a pin change enters the log.
3. **Everything else is rejected, not fatal.** In sealed mode the drain closes every other valid move with the fixed message **`the arcade is being upgraded — press New game to continue`** (verbatim, no interpolation) and the `sealed` reason code — the same mechanics already used at the section cap (§6, `log full`). Rejection, not run failure, is required: refusing the batch would livelock the loop, because the drain processes issues in ascending number order, so a lower-numbered frame-contributing issue would be re-drained and re-refused on every subsequent run, forever.
4. **Defense in depth.** `game/scripts/apply_moves.py` independently enforces invariant 1: if any frame-contributing line would land in a sealed section it **refuses with exit code 7** and leaves the ledger byte-unchanged, even though correct drain behavior means it should never see such a batch. A frame-contributing move ordered *ahead* of a reset in the same batch is refused by this path. What makes this depth rather than a second copy (§0.5) is the **evidence**, not the predicate: it re-reads the ledger file and the batch itself instead of trusting the drain's plan. It therefore calls the **same** sealing predicate implementation and **must not substitute a different comparand for any pin** — §5.9 records what happened when it did.
5. **Moves after the rollover apply normally.** Once the reset opens a fresh section, that section's pins match the running toolchain by construction, so later moves in the same batch land in it and are simulated normally.
6. **Recovery is always reachable**: the `new game` cooldown (§6) does **not** apply while the current section is sealed. A sealed game cannot advance, so the cooldown's purpose — preventing reset-griefing of a live game — is inapplicable, and a visitor cannot induce a mismatch (pins change only through a default-branch commit).
7. **Player-visible state.** While sealed, the README game block shows the **SEALED** guidance screen (§11). A run that **appends no ledger line to a sealed section** is a **successful run with zero ledger appends**: it performs a display-only swap to SEALED and commits no game state (§10). The governing property is "no frame-contributing line landed", not "a rejection was issued" — the sealed-reject batch of rule 3, a batch that is entirely duplicates (§5.3 idempotency key), and a batch with nothing admissible in it at all are the *same* case and take the *same* path. In particular rule 1's prohibition is **unconditional**: `stream.txt` is not regenerated in any of them. Regeneration is never contingent on whether the run had something to reject — a sealed section is never re-simulated, full stop.

   **The witness is §5.8's section state, not the reason codes.** Of the three cases this rule unifies, only the first emits a `sealed` code (§5.7) — a code exists only where an issue existed to close. So the reason codes witness the property exactly when a player is submitting moves, and are silent when nobody is: a section sealed by a default-branch commit, with an empty queue, would show the last live frame indefinitely and reject the next visitor's move with no warning that it was going to. That is precisely the silent trap the SEALED screen exists to prevent, and it is the observability defect §0.4 now names. Therefore the drain emits the section's state **unconditionally** (§5.8), and the display swap is selected from that state — never from the presence of a rejection. Sealing is a property of the section and of `game/toolchain.json`; it does not become true when someone submits a move, and it must not become visible only then.

**Rollover recovery render.** The fresh section is empty, so the recovery run replays zero frames and renders the game-start view — the same path already exercised by the initial committed state (§5.1).

**Alternative considered and rejected.** Moving the `new-game` directive to the *first* line of the opening section would dissolve the contradiction without an exception. Rejected: it rewrites the §5.3 serialization contract that committed tests and implementation already encode, it degrades the audit trail (the new section's first line would describe an event that preceded its existence), and it does not remove the need for degraded-mode handling of frame-contributing moves anyway.

### 5.6 Authoring exception: re-initializing an entry-less section (normative)

A section with **zero ledger lines** contains no player history: its replay output is empty under any pins, so rewriting its header rewrites nothing anyone played and cannot alter any rendered frame. For that section only, the header may be **re-initialized in place** — pin fields updated, section number preserved, no new section created.

Strictly bounded:

1. **Human-authored only — never a runtime behavior.** The workflow, drain, and `apply_moves.py` must never re-initialize a header. Their only recovery is the §5.5 rollover, so the automated path stays single-pathed and self-healing.
2. **Preconditions, all required**: the target section has zero ledger lines **and** is the last section in the file. Otherwise the §5.5 rollover applies.
3. **Authorized commit.** Re-initialization lands in an explicit, reviewed commit that also updates the toolchain pins it is aligning to — the header and `game/toolchain.json` move together, or the run that follows is sealed again for the same reason.
4. **The append-only guarantee is unweakened.** It exists to protect played history; an entry-less section has none. No section that ever held a ledger line may be rewritten, ever.

**First application (plan D9 / step E7), and what it looks like after §5.9.** The committed section 1 was entry-less and carried a provisional macOS `build=` hash; the canonical capture re-initialized that header in the same authorized commit that recorded the canonical build hash in `game/toolchain.json`. Preferred over burning a rollover: it keeps section numbering meaningful (a section 2 here would record "the toolchain changed before anyone played"), and it spares the profile's first-ever visitor a rejection message.

The **motivation** stated at the time — that the stale `build=` would seal section 1 before any move could apply — no longer holds: §5.9 removes `build` from the sealing pins, so a stale `build=` seals nothing. The action was still correct and is not being retro-justified: §5.6 exists to keep a header **honest**, and after §5.9 that is the whole of its purpose here. `build=` is now provenance, and a header claiming its frames came from a binary that never ran is a false record whether or not anything compares it. Re-initializing an entry-less header to the binary that will actually produce its frames is exactly the authoring case this section sanctions. Note the direction this closes: because a stale `build=` is no longer *load-bearing*, nothing forces it to be corrected — so correcting it is now a discipline rather than a consequence, and §5.9's unconditional provenance line is what makes a drifted one visible.

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
- **A section's state is not a reason code, and does not belong in this enum.** The six answer *why did this issue close this way* — one per drained issue, authored per item, meaningful only because an issue existed. Whether the current section is sealed or at its cap answers a different question with a different cardinality and a different lifetime: it is one fact per **run**, it is a property of the section and `game/toolchain.json`, and it holds just as firmly on a run that drained nothing at all. Folding it in here would mean inventing a phantom drained issue to carry it, which is exactly how the property became unobservable on a quiet run in the first place. It is emitted as a separate top-level field, specified in **§5.8**. The closed set of six is unchanged by it; a consumer that wants to know the section's state reads §5.8's field, never the presence or absence of a code (§0.5).

### 5.8 Section state: the unconditional display witness (normative)

**Why this exists.** §5.5 rule 7 and the §6 cap both govern on a property of the **current section** — sealed, at cap, or neither — and §11 shows a guidance screen for the first two. Until this section, the only evidence of that property was the `sealed` / `section-cap` reason codes, which exist only where there was a move to reject. That made the screen a function of *player traffic* rather than of *section state*, so the screen appeared only for a player who had already been told no, and never for the visitor arriving at a quiet, blocked game. Restated as §0.4: the property was specified but not witnessed in the quiet case.

**The positive property established.** After any successful drain, a consumer can read the state of the section the next move will land in — whether or not this run drained, applied, or rejected anything.

**The evidence read.** Nothing new. The drain already computes both halves in order to decide admission: the sealing predicate compares the current header's **sealing pins** against `game/toolchain.json` (§5.5, §5.9), and the section's expanded frame total is compared against the §6 log-section cap. The field **reports the conclusion those comparisons already reached**. No consumer recomputes either one (§0.5) — in particular the pin comparison is never re-derived in the workflow, which is what made the missing field the correct fix rather than a YAML-side workaround.

**The contract.** `game/scripts/drain.py` emits one additional top-level member in its actions JSON, a sibling of `mapping_version`, `moves` and `post_push`:

```
"section": { "state": "sealed" | "capped" | "open" }
```

1. **Unconditional.** The member is present on **every** exit-0 drain — including a run with an empty issue list, a run that is entirely duplicates, and a run in which nothing was admissible. That is the entire point of the field: it is the one signal that does not require a player to have done something. On a non-zero exit the drain reached no conclusion and there is no contract; the run takes a failure path of §10 and writes no guidance screen.
2. **Closed set of three, in precedence order**: `sealed` (any header pin mismatches the running toolchain, §5.5) beats `capped` (the section is at or above the §6 log-section cap) beats `open` (neither). A section can satisfy both of the first two, and `sealed` wins — the same order the drain already applies when admitting moves, so the reported state and the admission decision cannot disagree. The three values are mirrored in `game/mapping/v1.json` `section_states` and guarded against this list by the drift guard, exactly as the reason codes are.
3. **Reported as of the end of the batch.** It describes the section the *next* move will land in, not the one this run started with. A sanctioned rollover (§5.5 rule 2) inside the batch opens a section carrying the running pins, so a run that applies a reset reports `open`. This is the direction that cannot lie: the screen a run pushes describes the game as it stands when that run ends, and a run that just healed a sealed game must not leave SEALED on the profile.

   **This state and a successful publish can coexist, and the state does not win.** End-of-batch reporting means a batch whose *applied* moves carry the section over the §6 cap ends `capped` **and** publishes a frame — the two are not alternatives, and a consumer that reads the field as a decision would swap LOG_FULL over a frame this run just produced. §11 resolves it and this clause states it so it is not inferred: **a run that publishes a frame shows LIVE** (§11 rule 2, which strictly precedes the guidance rule), the `capped` state surfaces on the next run, and that is also the next moment a player can act on it. The field is an **input to** screen selection, never the selection. The mirror case cannot arise: a run cannot end `sealed` and publish, because while sealed the sole admissible move is the zero-frame rollover (§5.5 rule 2) and applying it un-seals — so suppressing guidance behind a publish can never suppress SEALED.
4. **Run-local, never serialized.** Like the reason codes, it is a diagnostic carried in the drain's output only. It is never written into `game/state/log.txt` or `game/state/stream.txt` (a ledger line is exactly the 5 fields of §5.3; a header exactly the 6 of §5.2), it is **not** a section 1/2/5 value, and adding it does **not** bump `mapping_version` and does **not** force a `new game`. Changing one of the three *strings* does change a runtime contract and requires the same coordinated commit as any other mirrored constant.

**Screen selection.** `sealed` → SEALED, `capped` → LOG_FULL, `open` → no guidance screen (§11, which governs precedence against LIVE and PAUSED). This is a **lookup, not a predicate**: the consumer maps a value it was handed and hard-fails on an unmapped one, rather than deciding for itself what "sealed" means.

**A missing member is a hard failure, not `open`.** Clause 1 makes the member unconditional on every exit-0 drain, so its absence is a **contract violation** and the consumer must fail loudly — it must never be read as "nothing to report". `open` is the value that says nothing to report; absence says *the drain never told me*, and those are different facts about different things. Defaulting absence to "no screen" would convert a broken producer into a silent one in exactly the case §5.8 exists to close: a sealed game keeps showing a stale live frame, and the missing field is indistinguishable from a healthy quiet run. This is obligation 4 in miniature — **the absence of a witness must be distinguishable from the witness saying nothing is wrong** — and it is the same shape as the near-miss where a missing key rendered as empty and passed a check by looking like a legitimate empty value. Applies to the member being absent, present-but-not-an-object, and present with no `state` key; all three are the same fault and take the same path. This does not weaken §5.8's exit-0 precondition: on a **non-zero** drain exit there is no contract to violate, the run takes a failure path of §10, and no consumer reads the field at all.

**Residual (§0.3).** The field reports what the drain concluded from the ledger and `game/toolchain.json` as that run read them, so it says nothing about a run that never reached the drain: if the sweep halts on the abuse threshold (§6) or the job dies earlier, no state is emitted and the display keeps whatever it last showed. The remainder is bounded by construction rather than by argument — the state is a pure function of two committed files, so it cannot go stale or accumulate error, and the next completed run re-reads both and re-emits. Closing it would mean computing section state somewhere other than the drain, which is the duplication §0.5 forbids and a worse trade than a delayed swap. The field also does not make sealing *visible sooner than a run*: a section sealed between runs is announced by the next drain, at worst one sweep interval (§6) later.

### 5.9 Engine identity: the replay is the pin, the binary is provenance (normative)

**Why this exists.** Until this section `build=` — the SHA-256 of the compiled engine binary — was treated as a determinism pin: a mismatch sealed the section, and the toolchain action failed the job closed on a rebuild that did not reproduce it. Real CI showed the proxy is wrong. On 2026-08-03 the canonical `ubuntu-24.04` build (`af458ac9…`) did **not** reproduce the reference build made from the same pinned commit with a clang publishing the same `18.1.3` version string; the binary's bytes are a property of the **runner image version**, which GitHub rotates on a schedule nobody in this repository controls. In the same runs the golden fixture's 700-frame framebuffer digest (`7cc38611…`, 716,800,000 bytes) reproduced **byte-exact** across macOS-arm64/Apple clang and hosted Linux-amd64/Ubuntu clang. Two different binaries, one identical replay.

That is the whole finding: **the binary's bytes and the replay are different properties, and the pin was placed on the one that moves.**

**The positive property established.** The engine this run is about to execute replays a fixed committed input to the same frames as the engine that produced the committed history. That — not byte identity — is what "same game" means (must_have 2) and what an append-only ledger needs in order to stay one timeline.

**The evidence read.** The committed golden fixture (`game/tests/fixtures/golden.stream`) is replayed with the binary this job will use and the resulting recorded framebuffer stream is SHA-256'd against the digest committed in `game/tests/fixtures/golden.expected.json` — the single authoring site for that constant, which is therefore **not** mirrored into `game/mapping/v1.json` (mirroring it would create the second site §0.5 forbids). *Cost*: one fixture replay, paid **only on the from-source build path**. A binary restored from cache has been proven byte-identical to a binary that already passed this gate, and byte identity implies behavioural identity, so the warm path is unchanged and the gate is paid only by runs that were already paying for a compile.

**The sealing predicate contains exactly the replay's inputs.** `engine`, `wad` and `mapping` are inputs: change one and the frames change. `build` is an *artifact of compiling* one of them, and the fixture demonstrates that two artifacts of the same input replay identically — so sealing on it seals on a property the replay does not have. The cost of getting this wrong is not abstract: an image rotation is an infrastructure event with no game meaning, and sealing would answer it by demanding a `new game` — discarding a live session's history, on GitHub's release cadence, to repair nothing. **Sealing is for events that change the game. An image rotation is not one.**

**`build=` stays in the header, as provenance.** §5.2's six fields are unchanged, §5.3's five are unchanged, and every committed log keeps its exact meaning. The field records *which binary produced this section's frames*: it is written at section open from the hash of the binary the run actually executed, and it is **never a comparand**. `apply_moves.py --engine-build-sha256` supplies that value and nothing else. §5.5 rule 1's guarantee is unweakened in the sense that matters — a sealed section remains reproducible, because reproducibility of this artifact means *same input, same frames*, which is the property this section gates directly rather than by proxy.

**One implementation site (§0.5), and the livelock that proves why.** The sealing predicate is implemented once and both `drain.py` and `apply_moves.py` call it. Before this section there were two copies reading **different comparands**: `drain.py` compared the header against `game/toolchain.json`, `apply_moves.py` compared it against the binary observed at run time. With a rotated image and a not-yet-updated pin those two disagree, and the disagreement composes into a state machine neither copy can be read to predict — the drain sees no mismatch and admits a reset; `apply_moves.py` opens the next section carrying the **observed** hash; the following drain compares that fresh header against the **committed** hash and seals it on arrival; the only admissible move is another reset, which opens another section that is sealed on arrival. One section per reset, forever, in committed state. Removing `build` from the predicate leaves both sides reading only committed values, so they cannot disagree by construction. **This is the load-bearing reason the ruling is a package**: relaxing the toolchain action's hard failure *without* unifying the comparand does not soften the failure, it converts a loud one into that livelock.

**Failure classes, stated as classes rather than as the instance that prompted them.**

| Observation | Class | Behaviour |
|---|---|---|
| A **restored** binary's SHA-256 ≠ the recorded pin | untrusted artifact | Discard, rebuild from the pinned commit. Never execute it, never gate on it, never replay-test it — executing it is the risk. RFC "Executable integrity" / D12, **unchanged and not weakened by anything here**. |
| A **from-source** build's SHA-256 ≠ the recorded pin, replay digest **matches** | provenance divergence — **not a fault** | Proceed. Emit the observed hash, origin and runner image (§0 corollary). Do **not** write the pin back — a runtime that re-pins itself certifies nothing, and §5.6 rule 1 already forbids runtime rewriting of committed pins. Do **not** save a cache entry under a key naming a hash it does not carry. Cost is a rebuild per run until an operator re-pins, at leisure. |
| A **from-source** build's replay digest ≠ the committed digest | toolchain fault | **Hard failure**, job stops. §10 pre-push row: game state untouched, best-effort UNAVAILABLE, issues stay open, and the sweep's consecutive-failure alert reaches the operator. |
| `engine`, `wad` or `mapping` moved in a default-branch commit | game event | **Sealed** (§5.5). Healed in band by `new game`, no operator. |

The hard failure is retained **deliberately**, and the correction is to its *trigger*, not its class. A same-commit replay divergence is a defect in the build environment whose repair is an operator re-pinning a toolchain — not a player pressing a button. Sealing it would ask a visitor to discard their session in order to work around a broken runner, and would file a real fault behind a screen that says the arcade is being upgraded. Hard-down is the honest report of a broken toolchain; what was wrong was firing it at binaries that replay correctly.

**The engine cache key must not carry the mutable image version.** It carries the image **label** (`ubuntu-24.04`), the engine commit and the recorded build hash. A surviving entry is how the pinned binary outlives a rotation: it restores, verifies byte-exact against the committed pin, and the game never notices. Keying on the rotating version would evict that entry precisely when it is most useful.

**Observability (§0.4), and the distinction it needs.** §5.5's property is a property of **committed state**: it is true or false whether or not anything runs, so it demands a witness on a run that does nothing — which is why §5.8 exists. This section's property is a property of **an execution**: absent a running engine it has no truth value at all, so its witness is per-execution, and its obligation is to be unconditional *within every execution that acquires an engine*. The toolchain restore therefore emits one greppable line, unconditionally, on every invocation, carrying the observed build hash, the binary's origin, the runner image and the replay verdict. **No game state can be committed without that acquisition**, so no un-gated binary can ever produce a published frame — the residual is a detection delay, never an unguarded run. A gate whose property is about an action is witnessed per action; a gate whose property is about state is witnessed per run. Confusing the two is how §5.5 lost its witness, and answering §0.4 with "per-execution" is only legitimate when the property genuinely has no truth value between executions.

**Residual (§0.3).** The fixture exercises one input stream through one level path (966 tics, 700 recorded frames of continuous run/turn/strafe/fire). A binary that diverges only on code the fixture never reaches — a weapon it does not fire, a monster it does not meet, a map it does not enter — passes this gate and could still fork a live timeline. The remainder is narrowed, not closed, by DOOM's replay path being fixed-point integer arithmetic with no wall-clock or floating-point dependence, which is why the cross-architecture agreement above is as strong as it is: it is evidence about the *class* of divergence, not just about this fixture. Closing it would mean checksumming each section's own replay and storing the result per section — which makes every committed line carry a value derived from a binary, invalidates history rather than sealing forward on any change, and cannot be re-verified later without the retired binaries. Rejected as a worse trade. **Re-verify the fixture's coverage whenever the engine commit changes**, the same re-verify discipline §12 and §12.1 carry.

**Not a `mapping_version` bump.** Like the reason codes (§5.7) and the section state (§5.8), this changes a runtime contract and no serialization value: §5.2's six fields, §5.3's five, and every committed byte keep their exact meaning, and every existing log parses identically. A bump would also be self-defeating — it seals the current section and forces the very `new game` this section exists to stop an image rotation from demanding.

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

- Rendered **only** by `game/scripts/rewrite_readme.py`, from `game/mapping/v1.json` plus the control-link target supplied at render time (§9.1) — self-consistent by construction, and the self-consistency test parses every rendered title.
- Layout: **3 columns**, 4 rows (mobile-safe per RFC profile-page constraints). Cell URL: `https://github.com/<repo>/issues/new?title=<url-encoded canonical literal>&body=Just%20press%20Submit%20%E2%80%94%20your%20move%20runs%20automatically.` — `<repo>` per **§9.1**; this document names no repository.
- Rendered links (12, in this order): `forward`, `forward x5`, `run-forward x5`, `back`, `turn-left`, `turn-right`, `turn-left x3`, `turn-right x3`, `fire`, `fire x3`, `use`, `new game`. Labels/emoji per section 1 (repeat links append ` x<n>` to the label).
- `--controls-enabled` flag (cutover stage 1): when disabled, the rewriter renders this exact placeholder line instead of the table: `🕹️ Controls are being wired up — the arcade opens soon.`

### 9.1 Control-link target: the repository that will drain the move (normative)

**The positive property established.** Every rendered control link opens an issue on the repository whose **own workflow will process it**. Not "on the profile" — that is one deployment's answer to the question, and hard-coding an answer is how this was wrong.

**The evidence.** The target is supplied to the renderer at render time as an `<owner>/<name>` argument, and the workflow supplies `GITHUB_REPOSITORY` — the repository the run is executing in, which is *by definition* the repository whose `doom.yml` drains the issue the link creates. No authored value has that property. The motivating instance: the renderer carried the profile repository as a module constant, so when the rehearsal sandbox rendered the block, **12 of 12 links pointed at the profile** — a click would have filed a stranger's move on Nik's profile repository, where the sandbox's own workflow would never see it. A boundary violation and a dead control, from one correct-looking literal.

**No default, no fallback, no baked-in repository.** Rendering the control table without a supplied target is a **usage error (exit 2)**, README byte-untouched — never a render with a guess. A default is indistinguishable from a hardcode at the exact moment it matters: the first deployment that is not the one the default names. The target is required **if and only if** the control table is rendered; with `--controls-enabled` absent the placeholder line is rendered, there is no link, and there is nothing to target.

**The grammar is the sanitizer.** The value is validated as an anchored, ASCII-only full match against `\A[A-Za-z0-9][A-Za-z0-9._-]{0,38}/[A-Za-z0-9._-]{1,100}\z` and is then interpolated into the URL path **unescaped**, because the `/` between owner and name is structural. That is sound **only** because the grammar admits no character that is special in a URL (`? # & % : @` and space) or in a Markdown link target (`( ) < > " \` and space) — so the validation is not a courtesy check, it is the entire escaping strategy and may not be relaxed without replacing it. A reject is exit 2 with the README untouched.

  *Residual (§0.3).* The grammar cannot tell a valid-but-wrong repository from the right one: a typo naming a real repository renders links that resolve, look correct, and are never drained. That remainder is closed by the **source**, not by the predicate — the value must be taken from the execution environment (`GITHUB_REPOSITORY`) and **never authored as a literal in the workflow**, because only the environment's value is the running repository by definition. An authored literal passes this grammar exactly as readily as the correct one, which is why "where the value comes from" is normative here and not an implementation note.

**Not a mapping field, and not a post-render substitution.**
- **Mapping.** `game/mapping/v1.json` is the normative value table for the *game*; the repository a deployment runs in is not a game value. A mapping field would also force the rehearsal to carry a **modified** `game/mapping/v1.json` — the very file the rehearsal exists to exercise unmodified — and would place a deployment fact inside the artifact whose changes are the trigger for a `mapping_version` bump and a forced `new game`. Deployment configuration must never be able to imply a game reset.
- **Post-render substitution.** Rewriting the repository into the block after the renderer produced it creates a second site that authors the block's bytes (§0.5) and breaks the renderer's purity property: the block is a pure function of (mapping, state, image URL, control-link target, flags), applying it twice is byte-identical, and prior content is never consulted. Byte-level substitution over a tenant-shared README is also precisely the class of operation the marker-block contract exists to prevent.

**The rehearsal environment is not a SPEC concept.** This document names no repository, and there is no rehearsal mode, flag, environment or branch anywhere in the normative text or in the renderer. The sandbox is an **ordinary deployment** that supplies its own value through the same argument the profile supplies its own through. That is the only arrangement under which the rehearsal proves anything: a parameter the sandbox exercises and the profile does not is, by construction, a divergence between what was rehearsed and what ships. The arrangement also aligns the two deployment-dependent URLs in the rendered block, since the frame's `raw.githubusercontent.com` source is already derived from `GITHUB_REPOSITORY` at render time — the issue URL was the odd one out, not the new case.

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

Degraded-mode note (§5.5 rule 7, §6 cap): **a run whose drain succeeded and produced no ledger line to append is a `success` outcome** with zero ledger appends and no GIF publish. It is not a failure row above — nothing failed, and no game state was ever eligible to change. (This is disjoint from the pre-push failure row by construction: with no line to append there is nothing to apply, simulate, encode or budget, so no pre-push step runs to fail.)

The governing property is the **absence of an append**, not the presence of a rejection — a batch rejected in band (§5.5 rule 3, §6 cap), a batch that is entirely duplicates (§5.3), a batch rejected only on grammar or cooldown, and a run with nothing pending at all are the same outcome and take the same path. Any rejected issues are closed with their fixed guidance message; on the quiet run there are none to close, and that changes nothing else about the row. The display swap is selected from the **section state** (§5.8) — `sealed` → SEALED, `capped` → LOG_FULL, `open` → no swap, the prior frame stays and remains accurate history — so it fires on the quiet run too and never depends on a player having supplied something to reject.

## 11. State screens (v1)

- **LIVE** — the game GIF (normal state after a move).
- **PAUSED** — default "press play" idle state (swapped by the sweep after inactivity, well before the 60-day scheduled-workflow auto-disable).
- **UNAVAILABLE** — failure/limit guard. Semantics: **"moves are not being processed right now"** — not "the frame is wrong"; an untouched prior frame is still accurate history.
- **LOG-FULL guidance** (`LOG_FULL`) — shown at the section cap: only `doom: new game` accepted.
- **SEALED guidance** (`SEALED`) — shown while the current section is sealed by a pin mismatch (§5.5): only `doom: new game` accepted, and it is exempt from the cooldown. Distinct from UNAVAILABLE (moves *are* being processed) and from LOG_FULL (the section is not full — its toolchain moved). Adds one rewriter state value, one screen asset, and one drain reason code, parallel to LOG_FULL in every respect.
- **LOADING** — defined but **off by default in v1** (costs an extra push per move).

**Precedence (normative).** At most one screen is written per run, chosen by the first rule that applies:

1. **The abuse halt writes PAUSED and stops** (§6): move processing is halted for that sweep, so no later rule can run.
2. **A run that publishes a frame shows LIVE** (§10 success row). A fresh frame is truer than guidance, and the section's condition surfaces on the next run — which is also the next moment a player can act on it. This is the only case in which a run ends `capped` and does not show LOG_FULL. It never suppresses SEALED: a run that appends a frame-contributing line cannot end sealed, because while sealed the sole admissible move is the rollover (§5.5 rule 2) and applying it un-seals.

   **This rule is reached by the common case, not an exotic one, and it strictly precedes rule 3.** §5.8 reports the section state as of the *end* of the batch, so a batch whose applied moves carry the section over the cap reports `capped` **and** publishes — the two coexist on the same run and neither is a failure. Precedence resolves it without a tie-break: rule 2 applies first, so the run shows LIVE. A consumer must therefore not gate the guidance swap on "the batch was entirely rejected" **nor** treat a non-`open` state as decisive; the correct condition is *state selects the screen, and a publish suppresses it*. Gating on all-rejected is the defect §5.8 was written to remove — a sealed section with an empty queue rejects nothing, so an all-rejected gate leaves exactly the visitor §5.8 exists for staring at a stale frame.
3. **Otherwise a guidance screen selected by the section state (§5.8) outranks PAUSED.** A sealed or capped section that keeps drawing moves is not idle — it is being played and answered — and PAUSED would misreport *why* the frame is not moving. It also matters that idleness is measured from the last game-state commit (§6), which a blocked section never produces, so the idle threshold is reachable while the game is demonstrably in use.
4. **UNAVAILABLE** is written only on the failure rows of §10, and never over a guidance screen the same run already pushed.

A screen is never selected by string-matching player-visible prose or by re-deriving a normative predicate; the only inputs are the section state (§5.8) and the reason codes (§5.7).

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

- **(a) Truncation at an offset whose byte happens to be `0x3B`.** Measured at ~0.3 % of offsets in a reference L0 artifact (2,064 occurrences in 705,961 bytes, one of which is the genuine trailer), so step 1 alone narrows the truncation hole by roughly two orders of magnitude rather than closing it. A partially written encode essentially never stops there, but it can.

  **That ~0.3 % is step 1's residual, and it is an upper bound on the publish gate's.** A truncated artifact is a *prefix* of the intended output, and step 2 refuses every prefix of 16,000 bytes or fewer outright — so the offsets that actually survive to publication are only the `0x3B` offsets **above the floor**, and the floor removes the whole early region (header, logical screen descriptor, global colour table, and the opening of the first frame) in which a killed or out-of-space encoder leaves the shortest prefixes. The surviving count was not measured; treat the figure as **≤ 0.3 %** and re-measure alongside the ladder rungs if it ever becomes load-bearing. No uniformity is assumed — the excluded prefix has its own byte statistics, so the reduction is not the 2.3 % of the file that 16,000/705,961 would suggest.

  One honest consequence of the composition: a **sub-floor** truncation ending on `0x3B` is refused as `12`, not `13`, because on the evidence step 1 reads it genuinely is a complete GIF. Publication is correctly refused either way, but the operator is pointed at the palette/`pix_fmt` path for what was a truncation. Accepted: the safety verdict is right, only the first debugging step is misaddressed, and narrowing it further would need the block-chain walk rejected below. This is what §0.3 is for — the floor could only be shown to narrow the structural gate's remainder because that remainder had been written down first, and a gate with no stated residual cannot be composed with anything.
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
