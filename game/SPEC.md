# Game spec — normative value tables (v1)

Plan-time spec artifact designated by RFC 001 (`.yui-soul/rfcs/approved/001-playable-doom-readme/`, "Normative contracts"). The RFC defines the **shapes** (anchored `\A...\z` full match, ASCII-only, closed enum, bounded count, enumerated reject classes); this file fills the **values**. Consumed verbatim by the parser, expander, rewriter, budget check, drain, workflow gate, control-table renderer, and the E3 test suite. Machine-readable mirror: `game/mapping/v1.json` (`mapping_version: 1`) — on any discrepancy between the two files, treat it as a build error and fix the discrepancy; neither silently wins.

Engine timing basis: DOOM runs at **35 tics/sec**; one doomreplay input frame = one tic. Approximate durations below use 35 fps.

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

- `game/state/log.txt` — **the authoritative game state** (RFC D13): a sequence of sections; each section = one header line followed by zero or more ledger lines. Append-only; sections are never truncated or rewritten. A section with zero ledger lines is valid (fresh game).
- `game/state/stream.txt` — **derived artifact**: the doomreplay input stream for the **current section only**, regenerated from the ledger on every run (`stream == expand(ledger, mapping_version)` is a CI invariant; on mismatch the stream is regenerated — the ledger wins). Empty section ⇒ empty stream file (zero frames, no commas, single LF).

### 5.2 Section header grammar

One line, space-delimited, exactly 6 fields:

```
#section <n> engine=<40-hex> build=<64-hex> wad=<64-hex> mapping=<int>
```

- `<n>`: section number, decimal, starts at 1, strictly increasing by 1.
- `engine=`: immutable engine commit SHA (40 lowercase hex). `build=`: engine build-artifact SHA-256. `wad=`: `freedoom1.wad` SHA-256 (both 64 lowercase hex). `mapping=`: mapping version (this spec: `1`).
- Any mismatch between the current section's header pins and the running toolchain ⇒ **refuse to run** (RFC determinism guarantees).

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

## 6. Knob values (RFC OQ5 — resolved here, not post-launch)

| Knob | Value | Notes |
|---|---|---|
| `new game` cooldown (RFC D16) | **30 minutes** | Resets within 30 min of the last applied reset are rejected with the fixed message |
| Per-user move cooldown | **0 (disabled in v1)** | Valid-move floods are "someone playing"; drain amortizes. Knob exists in config, default off |
| Per-run drain cap | **20 issues** | ≈ 60 receipt writes worst case — under the 80/min secondary content-write limit |
| Log-section cap | **120,000 expanded frames** (unit: engine frames ≈ 57 min gameplay) | At cap, only `doom: new game` is accepted; others get the fixed guidance comment ("log full — start a new game") |
| Push retry attempts | **3** (fetch → reset → regenerate → commit → push) | Then fail per the write contract |
| Sweep cron | **`17 */6 * * *`** (every 6 h at :17) | Off-peak minute to dodge busy-window delivery lag; no-ops cheaply when idle |
| Sweep owner-alert threshold | **2 consecutive failed heavy runs** | Opens/updates the maintenance issue assigned to Nik |
| Trailing-24h abuse run-count threshold | **200 workflow runs / 24 h** | Sweep flips README to PAUSED and alerts (RFC must_have 7 defense) |
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

## 11. State screens (v1)

- **LIVE** — the game GIF (normal state after a move).
- **PAUSED** — default "press play" idle state (swapped by the sweep after inactivity, well before the 60-day scheduled-workflow auto-disable).
- **UNAVAILABLE** — failure/limit guard. Semantics: **"moves are not being processed right now"** — not "the frame is wrong"; an untouched prior frame is still accurate history.
- **LOG-FULL guidance** — shown at the section cap: only `doom: new game` accepted.
- **LOADING** — defined but **off by default in v1** (costs an extra push per move).

## 12. GIF budget constants (RFC D7)

- **Hard byte ceiling: 4.0 MB = 4,000,000 bytes** (single exact constant; under the 5 MB Camo reference cap with headroom).
- Re-encode ladder (checked-in budget script; hard-fail, no publish, if L2 still exceeds the ceiling):
  - **L0**: 15 s tail @ 320 px wide / 12 fps / 128 colors (bayer dithered)
  - **L1**: 12 s tail @ 320 px / 12 fps / 128 colors
  - **L2**: 12 s tail @ 256 px / 10 fps / 64 colors
- Ladder constants adjusted in E2 (2026-07-30) per the RFC's plan-time re-verify (Sho S2): worst-case
  active-play encode rate measured at ~248–267 KB/s with the pinned static ffmpeg (n8.1.2) — not the
  provisional ~150 KB/s — so a 20 s L0 tail measured **5.33 MB > 4.0 MB ceiling** and would never publish.
  Measured sizes at the adjusted rungs on the same worst-case fixture content: L0 = 3.71 MB, L1 = 2.64 MB,
  L2 = 1.37 MB. The 15 s L0 stays within the RFC's resolved 15–20 s tail range; ceiling and ladder shape
  unchanged (normative). Exact encode recipe and full measurement table: `game/toolchain.json`.

---

Mapping version: **1**. Any change to section 1, 2, or 5 values bumps `mapping_version`, records it in new section headers, and — like an engine bump — forces `new game` (RFC Normative contracts 3).
