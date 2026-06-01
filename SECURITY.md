# Security Policy

Arandu is a privacy-first application that runs entirely on the user's
machine. We take security and privacy seriously and appreciate responsible
disclosure of vulnerabilities.

## Supported Versions

This project is in active beta. Security fixes are applied to the latest
release on the `main` branch. Older pre-release builds are not maintained.

| Version       | Supported |
|---------------|-----------|
| 0.5.x (beta)  | Yes       |
| < 0.5         | No        |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub
issues.**

Instead, use one of the following private channels:

1. **GitHub Security Advisories** (preferred) — open a private report from
   the repository's **Security → Report a vulnerability** tab.
2. **Email** — vinipd@gmail.com

Please include:

- A description of the issue and its potential impact.
- Steps to reproduce, or a proof of concept.
- Affected version(s) and platform.

**Do not include personal data or prompt content in your report — use hashes
or synthetic examples instead.**

## What to Expect

- We aim to acknowledge your report within **5 business days**.
- We will keep you informed as we investigate and work on a fix.
- Once a fix ships, we are happy to credit you in the release notes (unless
  you prefer to remain anonymous).

## Scope

Because all inference and data storage happen locally, the most relevant
classes of issue are:

- Sandbox escapes in the agent runtime.
- Bypasses of the egress or prompt-injection firewalls.
- Audit-chain tampering.
- Improper handling of data classified under the sensitivity-tier system.

See [docs/PRIVACY.md](docs/PRIVACY.md) for the privacy threat model.
