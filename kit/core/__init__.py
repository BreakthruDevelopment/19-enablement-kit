"""Foundation package: principals, the read-only sandbox and the frozen contract (slice 19.2).

Wave 1 owns this path. A later slice adds files here only if a security-sensitive
`claude` slice names it.

- `errors` -- structured refusals mapped onto app 17's `ErrorCategory` and `is_retryable`.
- `principals` -- the `engineer`, `ci` and `lead` principals, and `assert_can`.
- `sandbox` -- the read-only Proxy: the only module in the kit that opens a file.
- `config` -- the sandbox's caps and `gateway.command`, validated at the boundary.
- `contract` -- the schema and loader for app 18's frozen gateway contract.
"""
