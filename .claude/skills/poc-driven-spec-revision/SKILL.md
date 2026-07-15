---
name: poc-driven-spec-revision
description: Use when a docs/poc/*.md proposal document already exists and its findings need to be folded into a design spec under docs/superpowers/specs/.
---

# PoC-Driven Spec Revision

## Overview

The user builds and verifies PoCs themselves, in a separate PoC repo, and writes up
findings as a proposal doc under `docs/poc/*.md`. This skill starts from that already-
written proposal — it is **not** about implementing or verifying a PoC. Its job is to
turn an existing proposal into a spec revision, and to commit both correctly.

**Core principle:** the target spec file must remain complete and self-contained.
The `docs/poc/*.md` proposal is a record of *why* the change was made, not something
the spec ever points back to.

## When to Use

- A `docs/poc/*.md` proposal document already exists.
- Its suggested changes need to be folded into a `docs/superpowers/specs/*.md` file.

Don't use this to build, run, or verify a PoC yourself — that's out of scope; take the
proposal doc's findings as given.

## Workflow

1. **Read the proposal doc and the target spec.** Check each suggested change actually
   applies cleanly to the spec's current content (section numbers, function signatures,
   and call sites referenced in the proposal may have shifted since it was written).
2. **Verify each suggested change against the project's actual source of truth before
   accepting it.** A proposal written from the PoC's perspective can be correct about
   the PoC and still wrong, redundant, or actively harmful for the real project — read
   `PRD.md`/`DESIGN.md` (or whatever the project's own CLAUDE.md names as the source of
   truth) for anything the proposal touches, not just the target spec file. Concretely:
   - If the proposal wants to *add* content (a schema, a constant, a formula), check
     whether that content already exists canonically elsewhere in the project. If it
     does, reconcile/reference the existing definition instead of re-deriving a fresh
     one from scratch — a re-derived copy can silently drift (e.g. missing a `CHECK`
     or `UNIQUE` constraint the canonical version has) and now there are two sources of
     truth disagreeing with each other.
   - If the proposal's suggested fix conflicts with an explicit rule or invariant
     already stated in the project's source-of-truth docs, the project's doc wins —
     flag the conflict to the user rather than folding it in silently.
   - Judge each change on whether it is actually worth taking, not just whether it
     parses/compiles against the current spec text. A PoC-specific workaround, a
     stylistic preference from the PoC repo, or a "finding" that's just restating a
     language's default behavior (e.g. "bare `raise` preserves exception type") may not
     earn its place in the spec even though it's technically true.
   - If a change is rejected or modified from what the proposal literally says, say so
     to the user and explain why, rather than applying it as-is.
3. **Edit the spec file directly and inline.** Fold each accepted change into the
   relevant section — update pseudocode signatures, add principle paragraphs, and
   update any other call sites in the same doc that the change affects. Do **not**
   add a "see PoC proposal" or "see docs/poc/..." reference — the spec must read as a
   complete design on its own.
4. **Commit the spec change** with a `Reference:` trailer pointing at the PoC's GitHub
   repo URL (ask the user for it, or run `git remote -v` in the PoC's working copy if
   you have access to it):

   ```
   docs: <what changed in the spec and why, one line>

   <why the PoC surfaced this — one or two sentences>

   Reference: https://github.com/<owner>/<poc-repo>
   ```

5. **Commit the `docs/poc/*.md` proposal doc itself** as a separate commit (it's a
   record of the findings, kept even though the spec never links to it), using the
   same `Reference:` trailer. Never delete the proposal doc unless the user explicitly
   asks.

## Common Mistakes

- Trying to go build/inspect the PoC yourself — that's the user's job; work from the
  proposal doc as given.
- Leaving a "see proposal doc" link in the spec — defeats the point; the spec must be
  self-contained.
- Leaving the `docs/poc/*.md` proposal doc uncommitted — it should be committed (with
  the `Reference:` trailer) even though the spec itself never links to it.
- Deleting the proposal doc without being asked.
- Applying a proposed change without checking it against the project's actual
  source-of-truth docs — e.g. writing a "missing" schema/constant from scratch instead
  of checking `DESIGN.md`/`PRD.md` first, producing a duplicate that quietly disagrees
  with the canonical version.
- Treating "the proposal says so" as sufficient justification — some proposed findings
  are PoC-specific, restate language defaults, or are just not worth the spec's
  complexity budget; push back or skip rather than folding in everything verbatim.
