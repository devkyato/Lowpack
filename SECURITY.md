# Security policy

I treat extraction bugs differently from ordinary defects because an archive
can cross a trust boundary. Version 0.1 is still an alpha; please report a
suspected vulnerability privately through GitHub's security-advisory feature
and do not attach a malicious archive to a public issue.

LowPack never executes archive contents and does not restore symlinks. Still,
treat an unfamiliar archive as untrusted: verify it fully, extract into a new
directory, keep the safety limits, and inspect the result. Security support
currently covers the newest released alpha.
