"""The scaffold Factory: `kit new` (statements 3.1, 3.2 and 3.3).

`write_scaffold` copies a committed scaffold into a target directory. It does not author
rules, commands or skills at runtime.
"""

from kit.scaffold.factory import Manifest, write_scaffold
from kit.scaffold.templates import Kind

__all__ = ["Kind", "Manifest", "write_scaffold"]
