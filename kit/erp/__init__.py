"""The MCP client against app 18's frozen gateway contract.

Statement 2.4 is exercised here: `kit erp` turns one invocation into a gateway call and
renders the structured result or error. The default is the recorded transcript in this
package. `--live` speaks stdio to the process named in `gateway.command`. App 18 is not
imported, and this package adds nothing under `contracts/`.
"""

from kit.erp.client import call_read, check_live_contract
from kit.erp.errors import ErpCode, ErpError

__all__ = ["ErpCode", "ErpError", "call_read", "check_live_contract"]
