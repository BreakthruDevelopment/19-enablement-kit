# Architecture decision records

This is the `docs/adr/` layer of the CLAUDE.md hierarchy. It applies when work is in
`docs/adr/` or below, on top of the closer `docs/` layer and the root `CLAUDE.md`.

- An ADR records a decision. It has a status, a context, the decision and the
  consequences.
- Do not change application code from this directory. Record the decision, and name
  the document that would have to change next.
- A superseded ADR stays in the tree. Point at the record that replaces it.
