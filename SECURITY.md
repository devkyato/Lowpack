# Security policy

Version 0.1 is an alpha. Report suspected vulnerabilities privately through
GitHub's security-advisory feature. Do not include malicious archives in a
public issue.

LowPack never executes archive contents and does not restore symlinks. Treat
all archives as untrusted input: verify them fully, extract into a new
directory, retain safety limits, and inspect results before use. Security
support currently covers the newest released alpha only.
