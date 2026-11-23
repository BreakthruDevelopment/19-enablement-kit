"""The exploration: breadth first from the build files and descriptors, over the sandbox only.

The scout's tools are the three a developer has -- a directory listing, a file read and grep -- and
every one of them goes through the `Sandbox`. This module opens nothing itself: a read is
`Sandbox.read_text`, a listing is `Sandbox.list_dir` / `Sandbox.walk`, and **grep never touches
the filesystem at all**: it searches what the sandbox has already served in this run. That makes
grep free (no byte is charged twice) and it means a quote can only ever be found in bytes the
sandbox handed over, which is exactly what `kit.scout.verify` later checks a finding against.

**The order.** The queue is first-in-first-out, so it is a breadth-first walk of a graph whose edges
are references:

1. the build files (`build.xml`, `build.properties`, ...) and the descriptors `ejb-jar.xml` and
   `weblogic-ejb-jar.xml` are the seeds, build files first;
2. a file is searched for what it names -- a path or directory (a build file), a fully qualified
   class (a descriptor), an import (a class) -- and each thing it names that the sandbox listed is
   queued behind everything already waiting.

A directory a build file names is read as that directory's own files, not recursively. Nothing
reads a file the sandbox's own listing did not offer, so a build file that names `.env` or
`/etc/passwd` makes no read at all.

**A cap stops the run.** `sandbox.run_byte_cap` and `sandbox.file_count_cap` end the exploration:
the budget is the run's, not the file's, so there is no reading "around" it. The brief then says
how far the scout got. A file that is merely too large for the *per-file* cap, or is not text, is
skipped and the walk goes on.

**What is recorded.** Every step records what was done, why that file was chosen (the file that
named it), what happened, and the rolling summary after it. The summary is rebuilt from a small
state at every step, so it stays the same size however far the exploration goes; that is what
keeps a long exploration inside a context budget (statement 5.4). A step names its target only when
the target is a path the sandbox listed. Anything else -- a refused or unlisted path, a file
withheld for looking like a credential -- is recorded as a fixed placeholder, so a step record can
never carry a path the sandbox denied.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from kit.core.errors import ErrorCode, KitError
from kit.core.sandbox import Sandbox
from kit.scout.secrets import looks_secret

__all__ = [
    "BUILD_NAMES",
    "SEED_DESCRIPTORS",
    "SIGNALS",
    "Explorer",
    "Hit",
    "ReadOutcome",
    "Signal",
    "Step",
    "kind_of",
    "references",
]

BUILD_NAMES: Final = ("build.xml", "build.properties", "pom.xml", "build.gradle")
SEED_DESCRIPTORS: Final = ("ejb-jar.xml", "weblogic-ejb-jar.xml")

# What a placeholder in a step's `target` looks like. Fixed strings, never a path.
UNLISTED: Final = "[unlisted]"
WITHHELD: Final = "[withheld]"

# A line longer than this is not searched: the patterns are bounded, but a hostile one-line file is
# a cost the scout has no reason to pay.
MAX_SEARCHED_LINE: Final = 2_000
MAX_HIT_TEXT: Final = 200
MAX_REFERENCES_PER_FILE: Final = 200
ROLLING_SUMMARY_CHARS: Final = 3_000

# These two refusals end the run; every other refusal on a read skips that file.
_STOP_CODES: Final = frozenset({ErrorCode.RUN_BYTE_CAP, ErrorCode.FILE_COUNT_CAP})

Kind = Literal["java", "xml", "jsp", "sql", "properties", "other"]
_KINDS: Final[Mapping[str, Kind]] = {
    ".java": "java",
    ".xml": "xml",
    ".jsp": "jsp",
    ".sql": "sql",
    ".properties": "properties",
}


def kind_of(path: str) -> Kind:
    """A fixed-vocabulary kind for a path, so a report can count files without naming them."""
    suffix = path[path.rfind(".") :].lower() if "." in path.rsplit("/", 1)[-1] else ""
    return _KINDS.get(suffix, "other")


@dataclass(frozen=True, slots=True)
class Signal:
    """A pattern worth a closer look. Every pattern must match somewhere in a file for the file to
    count; the hits are the lines the **first** pattern matches."""

    label: str
    patterns: tuple[re.Pattern[str], ...]
    before: int = 0
    after: int = 0
    per_file: int = 3


# Searched over served text only. The labels are the scout's vocabulary for what to look at, not
# findings: a model decides what they mean, and `verify` decides whether it may say so.
SIGNALS: Final[tuple[Signal, ...]] = (
    Signal("jndi-lookup", (re.compile(r"\.lookup\(\s*\""),)),
    Signal(
        "declared-container-transaction",
        (re.compile(r"<transaction-type>\s*Container\s*</transaction-type>"),),
        before=5,
        per_file=12,
    ),
    Signal("bean-managed-transaction", (re.compile(r"\bUserTransaction\b|getUserTransaction"),)),
    Signal(
        "string-built-sql",
        # A string literal that ends where a value is about to be pasted in: `= '" + id`,
        # `LIKE '%" + name`. Text that merely contains a SQL word does not match.
        (re.compile(r"(?i)(?:=|\blike)\s*'?%?\"\s*\+\s*[A-Za-z_]"),),
        before=2,
        after=2,
    ),
    Signal(
        "http-and-ejb",
        (
            re.compile(r"\bextends\s+(?:\w+\.)*HttpServlet\b"),
            re.compile(r"\bimplements\b[^{]*\bSessionBean\b"),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Hit:
    """One line a grep matched, with the lines around it. `path` is a path the sandbox served."""

    path: str
    line: int
    text: str
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    """What a read did. A refusal is a value here, not an exception: the scout carries on."""

    served: bool
    code: ErrorCode | None = None
    category: str | None = None
    withheld: bool = False
    text: str | None = None

    @property
    def stops_run(self) -> bool:
        return self.code in _STOP_CODES


@dataclass(frozen=True, slots=True)
class Step:
    """One thing the scout did, and why. First-class output, not logging."""

    number: int
    action: Literal["list", "walk", "read"]
    target: str
    why: str
    outcome: str
    bytes: int
    summary: str
    next: str

    def as_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "action": self.action,
            "target": self.target,
            "why": self.why,
            "outcome": self.outcome,
            "bytes": self.bytes,
            "summary": self.summary,
            "next": self.next,
        }


def _clip(line: str) -> str:
    return line if len(line) <= MAX_HIT_TEXT else line[:MAX_HIT_TEXT] + "..."


def _matching_lines(pattern: re.Pattern[str], lines: Sequence[str]) -> list[int]:
    """0-based indexes of the lines `pattern` matches, skipping lines too long to search."""
    return [
        i for i, line in enumerate(lines) if len(line) <= MAX_SEARCHED_LINE and pattern.search(line)
    ]


def signal_lines(signal: Signal, lines: Sequence[str]) -> list[int]:
    """The 0-based lines of a file that raise `signal`; empty unless every pattern matches."""
    first: list[int] | None = None
    for position, pattern in enumerate(signal.patterns):
        found = _matching_lines(pattern, lines)
        if not found:
            return []
        if position == 0:
            first = found
    return first or []


_PATH_TOKEN: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*")
# Bounded on every side, and only ever run over one short line: this reads untrusted files, and an
# unbounded `(?:\.[a-z]+)+` is quadratic on a long run of `a.a.a.a.`.
_CLASS_TOKEN: Final = re.compile(
    r"\b[a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40}){1,12}\.[A-Z][A-Za-z0-9_]{0,80}\b"
)
_IMPORT: Final = re.compile(r"[ \t]*import[ \t]+(?:static[ \t]+)?([A-Za-z0-9_.]{1,200})[ \t]*;")


def _pieces(line: str) -> Iterator[tuple[int, str]]:
    """A line as pieces of at most `MAX_SEARCHED_LINE`, overlapping so a name on a seam is whole.

    An ordinary line is one piece. The overlap is far longer than any name worth following, and a
    name seen twice is queued once.
    """
    step = MAX_SEARCHED_LINE - 200
    for offset in range(0, max(len(line), 1), step):
        yield offset, line[offset : offset + MAX_SEARCHED_LINE]


def references(path: str, text: str, files: Sequence[str]) -> list[str]:
    """What `text` (the content of `path`) names, as paths from `files`, in order of appearance.

    `files` is the sandbox's own listing, so this returns only paths the sandbox offered: a name in
    the text that is not in the listing -- `/etc/passwd`, `.env`, `../x` -- matches nothing, and the
    string is dropped here without being kept anywhere. Pure: it opens nothing.
    """
    kind = kind_of(path)
    wanted: list[str] = []
    seen: set[str] = set()

    def add(candidates: Iterable[str]) -> None:
        for candidate in candidates:
            if candidate not in seen and candidate != path:
                seen.add(candidate)
                wanted.append(candidate)

    known = set(files)
    children: dict[str, list[str]] = {}
    for name in files:
        children.setdefault(name.rpartition("/")[0], []).append(name)

    def by_class(dotted: str) -> list[str]:
        tail = dotted.replace(".", "/") + ".java"
        return [name for name in files if name == tail or name.endswith("/" + tail)]

    # Line by line, and a long line in pieces, so no pattern ever sees an attacker-sized string and
    # a minified descriptor on one line is still followed. Order is (line, column): what a file
    # names first is read first.
    found: list[tuple[int, int, list[str]]] = []
    for number, line in enumerate(text.split("\n")):
        for offset, piece in _pieces(line):
            if kind == "java":
                match = _IMPORT.match(piece)
                if match:
                    found.append((number, offset, by_class(match.group(1))))
            elif kind in ("xml", "properties"):
                for token in _PATH_TOKEN.finditer(piece):
                    name = token.group(0).rstrip(".-")
                    if name in known:
                        found.append((number, offset + token.start(), [name]))
                    elif name in children:
                        found.append((number, offset + token.start(), sorted(children[name])))
                for token in _CLASS_TOKEN.finditer(piece):
                    found.append((number, offset + token.start(), by_class(token.group(0))))
    for _, _, names in sorted(found, key=lambda item: item[:2]):
        add(names)
    return wanted[:MAX_REFERENCES_PER_FILE]


class Explorer:
    """The scout's tools and its record of using them. One per run, over one root."""

    def __init__(self, sandbox: Sandbox) -> None:
        roots = sandbox.roots
        if len(roots) != 1:
            raise ValueError("a scout explores exactly one root")
        self._sandbox = sandbox
        self._root = roots[0]
        self._index: tuple[str, ...] = ()
        self._listed: frozenset[str] = frozenset()
        self._top: tuple[str, ...] = ()
        self._served: dict[str, str] = {}
        self._steps: list[Step] = []
        self._queue: deque[tuple[str, str]] = deque()
        self._queued: set[str] = set()
        self._failed: set[str] = set()
        self._withheld = 0
        self._bytes = 0
        self._stopped_by: ErrorCode | None = None
        self._modules: Counter[str] = Counter()
        self._signal_files: dict[str, set[str]] = {s.label: set() for s in SIGNALS}

    # -- read-only view of the run ----------------------------------------------------------

    @property
    def steps(self) -> tuple[Step, ...]:
        return tuple(self._steps)

    @property
    def files(self) -> tuple[str, ...]:
        """Every path the sandbox listed under the root: `coverage.files_total` counts these."""
        return self._index

    @property
    def served(self) -> Mapping[str, str]:
        """The text the sandbox served, by path. The only thing a quote may be checked against."""
        return dict(self._served)

    @property
    def withheld(self) -> int:
        return self._withheld

    @property
    def stopped_by(self) -> ErrorCode | None:
        return self._stopped_by

    @property
    def queued(self) -> frozenset[str]:
        return frozenset(self._queued)

    @property
    def failed(self) -> frozenset[str]:
        return frozenset(self._failed)

    def sandbox_refusals(self) -> tuple[tuple[ErrorCode, str], ...]:
        """Every distinct refusal the sandbox recorded, as (code, category), in code order. Carries
        no path and no pattern: the sandbox's `Refusal.detail` is deliberately not read."""
        distinct = {(r.code, r.category.value) for r in self._sandbox.refusals}
        return tuple(sorted(distinct, key=lambda pair: pair[0].value))

    # -- the three tools --------------------------------------------------------------------

    def list_root(self) -> tuple[str, ...]:
        """A directory listing of the root. Denied and escaping entries are dropped by the sandbox
        and are on its refusal record, which is where the brief reports them."""
        children = self._sandbox.list_dir(self._root)
        # A directory is a name that has listed files beneath it: no second look at the disk.
        parents = {name.partition("/")[0] for name in self._index if "/" in name}
        self._top = tuple(
            sorted(
                name + ("/" if name in parents else "")
                for name in (self._relative(child) for child in children)
            )
        )
        self._record("list", ".", "see the top level of the tree", "listed", 0)
        return self._top

    def list_files(self) -> tuple[str, ...]:
        """Every readable file under the root. Opens nothing and charges no cap."""
        found = self._sandbox.walk(self._root)
        self._index = tuple(sorted(self._relative(path) for path in found))
        self._listed = frozenset(self._index)
        self._record("walk", ".", "count every file the sandbox will serve", "listed", 0)
        return self._index

    def read(self, relative: str, *, why: str = "requested") -> ReadOutcome:
        """Read one file through the sandbox. A refusal is returned, never raised."""
        try:
            text = self._sandbox.read_text(self._root / relative)
        except KitError as err:
            outcome = ReadOutcome(False, err.code, err.category.value)
            self._failed.add(relative)
            if outcome.stops_run:
                self._stopped_by = err.code
            self._record("read", self._target(relative), why, err.code.value, 0)
            return outcome
        size = len(text.encode("utf-8"))
        self._bytes += size
        if looks_secret(text):
            # Served by the sandbox, and not by us: not kept, not searched, not shown to a model.
            self._withheld += 1
            self._failed.add(relative)
            self._record("read", WITHHELD, why, "withheld", size)
            return ReadOutcome(False, withheld=True)
        self._served[relative] = text
        self._modules[relative.rpartition("/")[0] or "."] += 1
        lines = text.split("\n")
        for signal in SIGNALS:
            if signal_lines(signal, lines):
                self._signal_files[signal.label].add(relative)
        self._record("read", self._target(relative), why, "served", size)
        return ReadOutcome(True, text=text)

    def grep(
        self,
        pattern: re.Pattern[str],
        *,
        paths: Iterable[str] | None = None,
        before: int = 0,
        after: int = 0,
        limit: int = 200,
    ) -> tuple[Hit, ...]:
        """Lines matching `pattern` in files the sandbox has served. Opens nothing."""
        hits: list[Hit] = []
        for path in sorted(self._served if paths is None else set(paths) & self._served.keys()):
            lines = self._served[path].split("\n")
            for i in _matching_lines(pattern, lines):
                hits.append(_hit(path, lines, i, before, after))
                if len(hits) >= limit:
                    return tuple(hits)
        return tuple(hits)

    def signal_hits(self, signal: Signal) -> tuple[Hit, ...]:
        """Where `signal` fires, in served files only, a few lines per file."""
        hits: list[Hit] = []
        for path in sorted(self._signal_files[signal.label]):
            lines = self._served[path].split("\n")
            for i in signal_lines(signal, lines)[: signal.per_file]:
                hits.append(_hit(path, lines, i, signal.before, signal.after))
        return tuple(hits)

    def signal_counts(self) -> Mapping[str, int]:
        return {label: len(files) for label, files in self._signal_files.items()}

    # -- the strategy -----------------------------------------------------------------------

    def explore(self) -> None:
        """List, seed, then read breadth first until the queue is empty or a cap ends the run."""
        self.list_files()
        self.list_root()
        for path, why in self._seeds():
            self._enqueue(path, why)
        while self._queue and self._stopped_by is None:
            path, source = self._queue.popleft()
            outcome = self.read(path, why=source)
            # The decision for the next step is part of this step's record.
            self._annotate_next()
            if outcome.served and outcome.text is not None:
                for name in references(path, outcome.text, self._index):
                    self._enqueue(name, f"named by {path}")
        self._annotate_next()

    def unread(self) -> dict[str, dict[Kind, int]]:
        """Files not served, grouped by why, then counted by kind. No names: fixed words only."""
        groups: dict[str, Counter[Kind]] = {
            "not_referenced": Counter(),
            "not_reached": Counter(),
            "not_readable": Counter(),
        }
        for path in self._index:
            if path in self._served:
                continue
            if path in self._failed:
                groups["not_readable"][kind_of(path)] += 1
            elif path in self._queued:
                groups["not_reached"][kind_of(path)] += 1
            else:
                groups["not_referenced"][kind_of(path)] += 1
        return {reason: dict(counts) for reason, counts in groups.items() if counts}

    # -- the rolling summary ----------------------------------------------------------------

    def summary(self) -> str:
        """Where the exploration stands, rebuilt from state so its size does not grow with the run.

        Directories and signal counts, never file bodies: this is what the next decision and the
        model's prompt carry in place of the transcript.
        """
        read = len(self._served)
        lines = [f"Read {read} of {len(self._index)} files ({self._bytes} bytes served)."]
        if self._top:
            lines.append("Top level: " + ", ".join(self._top[:20]) + ".")
        if self._modules:
            ranked = sorted(self._modules.items())
            shown = [f"{name} ({count})" for name, count in ranked[:25]]
            more = f" and {len(ranked) - 25} more" if len(ranked) > 25 else ""
            lines.append("Directories read: " + ", ".join(shown) + more + ".")
        found = [f"{label} in {n} files" for label, n in self.signal_counts().items() if n]
        if found:
            lines.append("Signals so far: " + ", ".join(found) + ".")
        lines.append(f"Waiting to be read: {len(self._queue)} files.")
        text = "\n".join(lines)
        return text if len(text) <= ROLLING_SUMMARY_CHARS else text[:ROLLING_SUMMARY_CHARS]

    # -- internals --------------------------------------------------------------------------

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _target(self, relative: str) -> str:
        return relative if relative in self._listed else UNLISTED

    def _enqueue(self, path: str, why: str) -> None:
        if path not in self._queued:
            self._queued.add(path)
            self._queue.append((path, why))

    def _seeds(self) -> list[tuple[str, str]]:
        def depth(name: str) -> tuple[int, str]:
            return (name.count("/"), name)

        # Shallowest first, then in the order `BUILD_NAMES` lists them: `build.xml` names things,
        # `build.properties` mostly configures them.
        def build_order(name: str) -> tuple[int, int, str]:
            return (name.count("/"), BUILD_NAMES.index(name.rpartition("/")[2]), name)

        builds = sorted(
            (n for n in self._index if n.rpartition("/")[2] in BUILD_NAMES), key=build_order
        )
        wanted: list[tuple[str, str]] = [(name, "build file") for name in builds]
        for descriptor in SEED_DESCRIPTORS:
            for name in sorted(
                (n for n in self._index if n.rpartition("/")[2] == descriptor), key=depth
            ):
                wanted.append((name, "deployment descriptor"))
        return wanted

    def _record(
        self,
        action: Literal["list", "walk", "read"],
        target: str,
        why: str,
        outcome: str,
        size: int,
    ) -> None:
        self._steps.append(
            Step(len(self._steps) + 1, action, target, why, outcome, size, self.summary(), "")
        )

    def _annotate_next(self) -> None:
        """Say, on the last step, what will be read next and why. Only a listed path is named."""
        if not self._steps:
            return
        if self._stopped_by is not None:
            decision = "stop: the sandbox refused a read with " + self._stopped_by.value
        elif self._queue:
            path, why = self._queue[0]
            decision = f"read {path}: {why}"
        else:
            decision = "stop: nothing left that a build file, a descriptor or a class names"
        last = self._steps[-1]
        self._steps[-1] = Step(
            last.number,
            last.action,
            last.target,
            last.why,
            last.outcome,
            last.bytes,
            last.summary,
            decision,
        )


def _hit(path: str, lines: Sequence[str], index: int, before: int, after: int) -> Hit:
    return Hit(
        path,
        index + 1,
        _clip(lines[index]),
        tuple(_clip(line) for line in lines[max(0, index - before) : index]),
        tuple(_clip(line) for line in lines[index + 1 : index + 1 + after]),
    )
