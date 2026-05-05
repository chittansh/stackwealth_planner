---
name: code-review
description: Review pending changes (staged + unstaged + the last N commits if asked) for issues that bite THIS codebase — agent-tool wiring, source-priority breaks, validator regressions, real-time event gaps, dropdown/UI consistency, security. Returns a punch list.
---

# Code review — Stackwealth Planner

Run this on `git diff` (default: staged + unstaged) or on a specific PR / commit range if the user provides one. Output a **punch list grouped by severity** (🔴 must-fix, 🟡 should-fix, 🟢 nit).

## How to invoke

Read the diff yourself first:

```bash
git diff --cached    # staged
git diff             # unstaged
git diff main...HEAD # branch vs main
```

Then walk the diff against the categories below. **Don't just list generic web-app issues** — flag the ones that specifically break this codebase.

---

## Categories — what to look for

### 🔴 Critical (must fix before merge)

1. **Agent tool wiring drift**
   - New tool added in `backend/src/agent/planner.ts` but no entry in the system prompt's "Tools you must use" section → agent won't call it.
   - Tool name uses `dot.case` → Anthropic rejects (`^[a-zA-Z0-9_-]{1,128}$`). Use `snake_case`.
   - Tool execute returns `{ ok, ...}` but the system prompt example expects a different shape → agent narrates wrong.
   - Frontend `humanizeTool` (in `frontend/src/components/chat/ToolCallCard.tsx` `FRIENDLY` map) missing the new tool → row shows raw `tool_name`.

2. **Source-priority bypass**
   - Direct call to `getPlan(...).then(p => { p.x = y; savePlan(p) })` anywhere — bypasses `enforceSourcePriority`. Must go through `applySet` / `applyAdd` / `applyAssumption` in `skills/scenario/index.ts`.
   - Mutation that doesn't trigger `recompute()` → `computed.*` goes stale, headline + chart get wrong.

3. **Validator regression**
   - Numeric output from a tool result that ISN'T captured into `seenNumbers` (chat.ts collects from `args` and `result`) → users see `«unverified:N»`.
   - Adding a new permissible-without-tool number range without adding a test in `backend/tests/validator.test.ts`.

4. **Anthropic message-shape break**
   - Anything that constructs `CoreMessage[]` and trims it → must use `safeTrim` (or guarantee no orphaned `tool_result` blocks at the head). Direct `slice(-N)` is a known foot-gun and will return `messages.0.content.0: unexpected tool_use_id` errors.

5. **Sensitive data in code/commit**
   - API keys (Anthropic, OpenAI), DB URLs, Fly tokens hard-coded or in tracked files. Especially watch `.env*` in git status.
   - The repo has a known pattern of `DEPLOY_NOW.md` containing real keys — flag if committed.

6. **Frontend: BACKEND_URL hard-coded**
   - Anything using `'http://localhost:4000'` directly outside `lib/api.ts`. The base URL must come from `process.env.NEXT_PUBLIC_BACKEND_URL` (baked at build).
   - Same for any new env that should be `NEXT_PUBLIC_*` — if it's needed in the browser, it must have that prefix AND be passed as a Docker `--build-arg`.

### 🟡 Should fix

1. **Real-time event gaps**
   - New backend mutation route (or new client-side mutation) that doesn't fire `firePlanChanged()` → canvas doesn't refresh until the next 2s poll.
   - New cross-component coordination using prop drilling instead of the existing `sw:chat-prompt` / `sw:plan-changed` / `sw:toast` event bus.

2. **Polling cadence**
   - Adding a new `setInterval(fetchX, < 1000ms)` — there are already two pollers; piling on more will hammer the API.

3. **Multi-model extraction not honored**
   - New parser/path that calls Claude directly via `@anthropic-ai/sdk` instead of going through `multimodalExtract` → loses the OpenAI fallback.
   - Hard-coded mime check that excludes a format the multimodal models support natively.

4. **Dedup guard skipped**
   - Adding new list paths to `applyAdd` callers without considering whether `findDuplicate` should know about them (e.g., a new "credit_cards[]" list that the user could double-add).

5. **Empty-state regression**
   - New canvas component that renders ugly when `plan` is `null` or all sections are empty — every existing component handles this. Match the pattern (a `min-h` placeholder with a clickable `firePrompt` link).

6. **Unsupported image mime path**
   - Adding image handling that bypasses `normaliseForVision` in `parseImage.ts` → HEIC will silently fail.

7. **Status pill / loader misuse**
   - New "in-flight + done" status pair stacked instead of using `replaceTaggedStatus`. Tag the pill and replace, don't append.
   - Spinner shown for terminal events (use `done` / `error` props on `StatusPill`).

8. **Auto-grow / scroll regressions**
   - New scrollable container without `scrollbar-hidden` class or matching styles in `globals.css` `* { scrollbar-width: none; }`.

### 🟢 Nits

1. **Color drift**
   - Any `text-emerald-* / amber-* / rose-* / sky-* / blue-* / lavender-*` Tailwind class. The design is monochromatic with matcha as the only accent. Use `var(--color-accent)` or zinc shades.
2. **Bare `<select>`**
   - Use `components/ui/Dropdown.tsx`. Native `<select>` clashes with the chevron-suppressed design language.
3. **Comments that restate the code**
   - Per repo convention, comments only for non-obvious WHY. Drop inline narration like `// loop over items`.
4. **Markdown in agent replies**
   - System prompt bans horizontal rules (`---`), emojis, and sub-headings. If you're shaping prompts, keep that contract.
5. **Long inline `<code>` paths**
   - Anything rendering canonical paths like `liquid_capital.savings_account_balance` in chat must `break-all` (already true for `AssistantMessage` — don't undo it).

---

## Output format

Return a structured punch list:

```
## Code review — <subject>

### 🔴 Must fix
1. <file:line> — <one-sentence issue> → <one-sentence fix>
2. ...

### 🟡 Should fix
1. ...

### 🟢 Nits (optional)
1. ...

### Looked fine
- <brief list of categories you checked that came back clean>
```

Keep each item to **one line + one-line fix**. If something needs a longer explanation, link to the relevant `repo-practices` section instead of inlining a treatise.

If the diff is empty (`git diff` returns nothing), say so and exit. Don't fabricate findings.
