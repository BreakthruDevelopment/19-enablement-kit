"""A content-level check for secret-shaped strings.

The sandbox's deny list refuses `.env*`, `*.pem`, `id_*` and `secrets` by *name*, on the resolved
path. That is the control, and it is enough for every path the rules can see. It cannot see a
hard link: `notes.txt` hard-linked to `<root>/.env` has no second path to match, and the sandbox
says so in its own docstring and leaves the content-level check to this slice. So a file whose
**content** looks like a credential is treated as one: it is withheld from the model and from the
brief, and the brief says that something was withheld. The same patterns run over the finished
brief as the last gate, so a model that invents or echoes a credential cannot emit one either.

Every repetition is bounded, because the text scanned is an untrusted file: an unbounded `[a-z]*`
in front of a keyword is quadratic on a long line with no match, and a hung scout is a denial of
service from one planted file.

The patterns are deliberately narrow: well-known token shapes and quoted or upper-case-assignment
credentials. A source file with `password` in a variable name is not a credential, and a scout that
withheld every such file would be a scout that could not read a login class.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["SECRET_PATTERNS", "looks_secret"]

SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # `.env` style: an upper-case name that says what it is, `=`, then a value.
    re.compile(
        r"(?m)^[ \t]*(?:export[ \t]+)?[A-Z0-9_]{0,60}"
        r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY)"
        r"[A-Z0-9_]{0,60}[ \t]*=[ \t]*[^\s#]{6,}"
    ),
    # A quoted literal assigned to a credential-named field, in any language.
    re.compile(
        r"(?i)(?:secret|password|passwd|api[_-]?key|access[_-]?key|token)"
        r"[a-z0-9_.-]{0,40}[\"']?[ \t]*[:=][ \t]*[\"'][^\"'\s]{8,}[\"']"
    ),
)


def looks_secret(text: str) -> bool:
    """Whether `text` holds anything that has the shape of a credential."""
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)
