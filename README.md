# 19 — Enablement kit

> A client with a Java EE and WebLogic estate wants its engineers to use an AI coding assistant safely on a codebase nobody fully remembers. This kit is what they keep after the engagement: a generated team configuration, a pull-request reviewer that runs against written criteria, and a scout that explores the legacy code read-only and writes a migration brief.

<!-- DRAFT: the remaining placeholders are TODO(deploy) (30-apps-infra#98, 19.12) and TODO(19.11) (HTTP surface, not built yet). Fill them in as each lands. -->

**Live:** TODO(deploy): `https://app19.breakthruventures.ai/healthz` once 30-apps-infra#98 is applied and the live smoke passes. · **Runs on:** AWS · **Imports:** [app 17](https://github.com/BreakthruDevelopment/17-agent-container), pinned by tag in [`pyproject.toml`](pyproject.toml). App 18 is **not** imported: its gateway contract is frozen in [`contracts/p2p-erp.json`](contracts/p2p-erp.json). · Part of [30 apps in 30 days](https://github.com/BreakthruDevelopment/ai-dev-os): the **enable** stage of the AWS demo track (apps 17 to 20).

There is no web UI. The kit is the `kit` command line plus the `Kit review` workflow it runs in CI.

## What it does

- **Lead:** runs `kit new <target> --scaffold <kind>` to write a `CLAUDE.md` hierarchy, path-scoped rules, slash commands and skills into a target repo. It is the only command that writes into a target repository. Three kinds ship: `java-legacy-companion`, `python-service` and `docs-only`.
- **Engineer:** runs `kit scout <root>` to explore a codebase through the read-only sandbox and get a migration brief. Every finding cites files and a verbatim quote, and the brief states what was not read and why.
- **Engineer:** runs `kit review <diff>` to run four finding passes and a consolidation pass against the written [`criteria/`](criteria/). The report can block. **It cannot approve.**
- **Engineer:** runs `kit erp <tool>` to make one read call to app 18's ERP gateway over MCP. It replays by default, and write tools are refused.
- **Engineer:** runs `kit session list | resume | fork` on their own sessions. Resuming replays the recorded turns with no model call.
- **Engineer:** `kit plan <task>` runs one task planned-first and executed-directly from one forked prefix and prints a comparison of turns, tool calls and budget. `--refine` reviews the direct attempt, runs the findings into a second attempt and shows what changed.
- **CI:** `kit review-ci` runs the reviewer headless on a pull request and posts at most one report, marked with the kit's own `Kit-Review:` line. It never changes a label, never merges, and never posts the factory's reviewer marker: the merge gate's sign-off stays with a person.

The committed sample [`sample/legacy-oms/`](sample/legacy-oms/) is a synthetic Java EE order-management app (51 files) with four planted problems for the scout to find. It is written for this repo, with no third-party code.

## The AI feature

Every model call goes through app 17's `ModelProvider`. CI and the default demo replay recorded replies and make no model call. The CI workflow has an opt-in live path, which runs only when a repository secret and a pull-request label are both present.

- **`pr-review`** ([`run_review`](kit/review/pipeline.py#L198)): four finding passes (correctness, security, project-rules, tests-coverage), each with its own written criteria file, then a consolidation pass. The diff goes in [fenced with a per-run nonce](kit/review/passes.py#L192) and is treated as data. In the demo, a comment in the diff asks reviewers not to report the injection. That comment is itself reported as SEC-7, and the injection is still reported. The [verdict](kit/review/pipeline.py#L107) is `blocking` or nothing: there is no approve value.
- **`scout-brief`** ([`run_scout`](kit/scout/pipeline.py#L149)): exploration is done in code by the [`Explorer`](kit/scout/explore.py#L293), which lists, reads and greps through the sandbox and keeps a rolling summary. The model writes the brief from what was served. [`assert_brief_clean`](kit/scout/pipeline.py#L143) runs before it is printed.
- **The sandbox Proxy** ([`Sandbox`](kit/core/sandbox.py#L125)) is the only module that opens a file for the scout or the reviewer. It applies a root allowlist and a deny list (`.git`, `.env*`, `*.pem`, `id_*`, `secrets`, `.claude`) per path segment of the resolved real path, plus byte and file-count caps. Every refusal is reported, never silently skipped.

## Exam coverage

App 19 owns 11 statements, including all of Domain 3. Statement 2.4 is **exercised** here and owned by app 18: see [`kit/erp/client.py`](kit/erp/client.py#L36) and the live contract check ([`contract_check.py`](kit/erp/contract_check.py#L28)).

| Statement | Subject | Where |
| --- | --- | --- |
| 1.7 | Session state, resumption, forking | [`SessionStore.fork`](kit/session/store.py#L97) copies turns up to a named turn and sets `parent_id`. [`resume`](kit/session/resume.py#L173) replays recorded turns through app 17's loop with no model call. |
| 2.5 | Built-in tools | The scout's [`list_root`](kit/scout/explore.py#L357), [`read`](kit/scout/explore.py#L380) and [`grep`](kit/scout/explore.py#L408), all through the sandbox |
| 3.1 | CLAUDE.md hierarchy | The root [`CLAUDE.md`](kit/scaffold/templates/java-legacy-companion/CLAUDE.md#L1) and closer layers such as [`sql/CLAUDE.md`](kit/scaffold/templates/java-legacy-companion/sql/CLAUDE.md#L1), written by [`write_scaffold`](kit/scaffold/factory.py#L65) |
| 3.2 | Custom commands and skills | [`commands/review.md`](kit/scaffold/templates/java-legacy-companion/commands/review.md#L1) and [`skills/review-dao/SKILL.md`](kit/scaffold/templates/java-legacy-companion/skills/review-dao/SKILL.md#L1), placed under `.claude/` by [`_REMAP`](kit/scaffold/templates.py#L40) |
| 3.3 | Path-specific rules | The `paths:` front matter in [`rules/sql.md`](kit/scaffold/templates/java-legacy-companion/rules/sql.md#L2) and its siblings |
| 3.4 | Plan mode versus direct execution | [`run_plan`](kit/plan/run.py#L196) stores the prefix and both arms as sessions and replays each. [`check_plan_rules`](kit/plan/recording.py#L195) refuses a recording that is not the comparison it claims to be: the prefix must use read tools only, and the planned arm must stay read-only until one approved plan. |
| 3.5 | Iterative refinement | [`run_refine`](kit/plan/run.py#L369) reviews the direct arm, runs the findings into a second attempt, reviews that and compares. [`build_refine_opening`](kit/plan/run.py#L256) builds round 2's opening deterministically from the **recorded** finding set, so the second attempt cannot be given a trimmed one. |
| 3.6 | CI/CD integration | [`kit-review.yml`](.github/workflows/kit-review.yml) runs [`run_ci_review`](kit/review/ci.py#L221) as `ci` on a pull request, posting at most one report |
| 4.1 | Explicit criteria for precision | Written criteria such as [`SEC-1`](criteria/security.md#L6), parsed by [`parse_criteria`](kit/review/criteria.py#L107). Findings are checked against them in [`grade`](kit/review/passes.py#L294). |
| 4.6 | Multi-instance and multi-pass review | [`PassName`](kit/review/passes_names.py#L11) (four finding passes plus consolidation), run by [`run_review`](kit/review/pipeline.py#L198) and merged by [`run_consolidation`](kit/review/passes.py#L362) |
| 5.4 | Context in large codebase exploration | The [rolling summary](kit/scout/explore.py#L489), capped at [`ROLLING_SUMMARY_CHARS`](kit/scout/explore.py#L80), and the stated [`unread_reason`](kit/scout/pipeline.py#L95) |

TODO(19.11): `GET /` will serve this map with file and line. That slice is not built yet.

### Exam scenarios 2, 4 and 5

The track assigns these three scenarios to app 19; their subjects are recorded in [`day-0-aws-demo-track.md`](https://github.com/BreakthruDevelopment/ai-dev-os/blob/main/specs/day-0-aws-demo-track.md). Each of the kit's three sub-systems answers one.

| Scenario | Subject | Answered by |
| --- | --- | --- |
| 2 | Code generation with Claude Code: slash commands, `.md` and configuration files, and deciding between plan mode and direct execution | `kit new`, which writes the hierarchy, rules, commands and skills (3.1, 3.2, 3.3). The plan-mode clause is `kit plan` (3.4, with 3.5 adjacent). |
| 4 | Developer productivity: navigating unfamiliar codebases with built-in tools such as grep and targeted file reads | `kit scout` over `sample/legacy-oms/` (2.5, 5.4) |
| 5 | CI/CD: running Claude Code in automated pipelines for code reviews, test generation, and pull-request feedback | `kit review` (4.1, 4.6), and the same reviewer headless in Actions as `kit review-ci` (3.6) |

**Scenario 5 is not fully covered.** Code review and pull-request feedback are covered in full. **Test generation is not.** The tests-coverage pass judges tests and writes none, and nothing else in the kit generates tests. A test-writing mode would be a new write path in a repo whose security story is that only `kit new` writes, and only under a target root. So it is out of scope, and this gap is named here rather than claimed.

## Architecture

```text
 kit new ──▶ scaffold Factory ──▶ target repo (lead only; the one write path)
 kit scout ─▶ Explorer ──▶ Sandbox Proxy ──▶ sample/ or a checkout (read-only)
               └─ rolling summary + served files ──▶ model (replay) ──▶ brief (verified, cleaned)
 kit review ▶ 4 finding passes (criteria/*.md) ──▶ consolidation ──▶ report: blocking | nothing
 kit erp ───▶ MCP client ──▶ recorded transcript   (--live: gateway.command, checked against contracts/p2p-erp.json)
 kit session ▶ sessions/<id>.json ──▶ resume = replay through AgentLoop, no model call
 kit plan ──▶ prefix forked into 2 arms ──▶ replay each ──▶ compare turns/tools/budget
               └─ --refine: review ──▶ round 2 from the recorded findings ──▶ what changed
 CI workflow ▶ kit review-ci as ci ──▶ at most one Kit-Review report (never a sign-off)
 GET /healthz, GET / ──▶ TODO(19.11)
```

## Security

| Principal | May |
| --- | --- |
| `engineer` | read through the sandbox, run the scout, the reviewer and `kit plan`, call gateway read tools, manage its own sessions |
| `ci` | read the checkout, run the reviewer, post at most one report. No scout, no sessions, no gateway, no writes. |
| `lead` | everything `engineer` may do, plus `kit new` |

Grants are an enumerated table in [`principals.py`](kit/core/principals.py#L92). Changing labels, merging and resolving threads are [capabilities that are never granted](kit/core/principals.py#L77) to anyone. Every command checks the principal before doing anything:

- `kit new` with the default principal prints `principal.forbidden: principal engineer may not write_target`.
- `kit erp post_invoice` prints `erp.write_refused`.
- `kit erp` as `ci` prints `principal.forbidden`.

The image has no credentials baked in ([`Dockerfile`](Dockerfile)).

## Deploy it yourself

TODO(deploy): fill this in from 30-apps-infra#98 (19.12) once it merges: the `apps.yaml` entry, the runtime and the IAM policy. The container image is built from the [`Dockerfile`](Dockerfile). The served endpoints come from 19.11 (TODO(19.11)).

## Develop

```bash
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict
uv run pytest
```

See [`AGENTS.md`](AGENTS.md) for the repo rules.

## 2-minute demo script

Every step replays recorded replies, with no network and no credentials.

1. Run `uv run kit new /tmp/demo --scaffold java-legacy-companion`. It is refused (`principal.forbidden ... write_target`). Add `--principal lead` and 14 files are listed: the root and four closer `CLAUDE.md` files, plus `.claude/rules`, `.claude/commands` and `.claude/skills`. Open `.claude/rules/sql.md` to show its `paths:` scope.
2. Run `uv run kit scout sample/legacy-oms`. The brief names the four planted problems from the code: the JNDI lookup repeated in nine classes, the self-managed transaction against the descriptor, the concatenated SQL in `OrderDao`, and the servlet-plus-EJB. Each has a verbatim quote. `coverage` says `Read 48 of 51 files` and why the other three were not read, and `steps` records each read with its reason.
3. Run `uv run kit review fixtures/pr-review/demo/change.diff`. It prints `Kit-Verdict: blocking`. The first finding is SEC-1 critical, the injection. SEC-7 shows the "note to reviewers" comment reported, not obeyed. The header states the report cannot approve.
4. Run `uv run kit erp get_invoice invoice_id=INV-1001` to get one replayed read. Then `uv run kit erp post_invoice invoice_id=INV-1001` prints `erp.write_refused`.
5. Run `uv run kit plan "<task>" --refine`. It shows the planned and direct arms forked from one prefix, the comparison of turns, tool calls and budget, then a second attempt built from round 1's findings and what changed between the rounds.
6. On any pull request in this repo, show the `Kit review` check and its single report: it carries `Kit-Review:`, says it cannot approve, and leaves `Reviewer sign-off` to a person.
7. TODO(deploy): open `https://app19.breakthruventures.ai/healthz`, then `/` for the coverage map (TODO(19.11)).
