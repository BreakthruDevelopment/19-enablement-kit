---
name: write-adr
description: Use when adding an architecture decision record under docs/adr. Requires a status, a context, a decision and consequences, each tied to a source.
---

# Write an ADR

1. Read `docs/adr/CLAUDE.md` and the path-scoped rule for `docs/adr/**/*.md`.
2. Find the next free number from the files already in `docs/adr/`. Do not renumber
   an existing record.
3. Write the status, the context, the decision and the consequences. Cite a document
   for any behaviour the context claims.
4. If an older record is replaced, set its status to superseded and point both ways.
