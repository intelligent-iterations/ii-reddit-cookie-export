# Security policy

## Supported versions

Security fixes are applied to the latest published release.

## Reporting a vulnerability

Report suspected vulnerabilities privately to
security@intelligentiterations.com. Do not open a public issue for an
unpatched vulnerability.

Include the affected version, a minimal reproduction that does not contain
real cookies, the expected impact, and any suggested mitigation.

## Security boundary

This tool reads Chrome's local cookie database and asks macOS Keychain for the
key needed to decrypt it. It filters the result to Reddit domains and writes
the export locally. It does not authenticate the consuming application,
upload files, or manage the exported credential after it is written.
