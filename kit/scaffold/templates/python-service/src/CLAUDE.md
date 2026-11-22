# Source

This is the `src/` layer of the CLAUDE.md hierarchy. It applies when work is in `src/`
or below, on top of the root `CLAUDE.md`.

- Keep each module about one thing. Match the names and the error style already here.
- A function that can fail raises a typed error. Do not return a status string.
- Do not log a request body, a prompt or a credential.
- Do not read or write a path the task did not name.
