---
name: poc-driven-spec-revision
description: Use when a PoC (in this repo's docs/poc/ or a sibling PoC repo like ConsoleMVC) revealed gaps or improvements to a design spec under docs/superpowers/specs/, and those findings need to be folded back into the spec.
---

# PoC-Driven Spec Revision

## Overview

Design specs in `docs/superpowers/specs/` are pseudocode-level and can miss edge cases
that only surface once someone implements a PoC against them. This skill defines how
to turn PoC findings into a spec revision without polluting the main repo with PoC
code or leaving the spec dependent on external documents.

**Core principle:** the target spec file must remain complete and self-contained.
PoC code and PoC-derived proposal docs are working material, not spec content — they
inform the edit, then stay out of the spec's cross-references.

## When to Use

- A PoC (own repo or `docs/poc/*.md` proposal) was built to validate a design spec.
- The PoC's tests or implementation exposed a gap, ambiguity, or missing edge case in
  a `docs/superpowers/specs/*.md` file.
- You're about to edit a spec based on a written PoC proposal.

Don't use this for spec changes that don't originate from a PoC (just edit normally).

## Workflow

1. **Verify claims against real PoC code before trusting a proposal doc.** A proposal
   citing `file.py:12-25` is a claim, not a fact — read the actual PoC file and confirm
   the cited behavior exists as described. Treat unverifiable citations (files that
   don't exist, wrong line ranges) as a blocking issue, not a nitpick.
2. **Judge each finding on its merits against the spec**, not just against the PoC:
   does it reveal a real design gap, or just one implementation's incidental choice?
   Reject/soften claims that overstate consistency with the existing spec (e.g. "this
   matches the existing pattern" when the spec never documented that pattern).
3. **Edit the spec file directly and inline.** Fold the accepted findings into the
   relevant sections (update pseudocode signatures, add a principle paragraph, update
   any call sites elsewhere in the same doc that the signature change affects).
   Do **not** add a "see PoC proposal" or "see docs/poc/..." reference — the spec must
   read as a complete design on its own.
4. **Leave the PoC artifacts alone.** Don't delete the PoC proposal doc or PoC repo
   unless the user explicitly asks — they're scratch/reference material, not spec
   content. Don't commit PoC source code into this repo.
5. **Commit the spec change with a `Reference:` trailer** pointing at the PoC's GitHub
   repo URL (get it from `git remote -v` in the PoC's working copy), so provenance is
   traceable without the spec itself linking out:

   ```
   docs: <what changed in the spec and why, one line>

   <why the PoC surfaced this — one or two sentences>

   Reference: https://github.com/<owner>/<poc-repo>
   ```

## Common Mistakes

- Citing PoC line numbers without reading the file — verify every citation before
  acting on it.
- Leaving a "see proposal doc" link in the spec — defeats the point; the spec must be
  self-contained.
- Deleting the PoC proposal doc or PoC repo without being asked.
- Committing PoC implementation files into the main project.
