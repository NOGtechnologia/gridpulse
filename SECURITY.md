# Security Policy

## Supported versions

Security fixes are provided for the latest minor release. Container images are
rebuilt weekly (Dependabot) and scanned with Trivy on every change.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's **private vulnerability reporting** ("Security" tab → "Report a vulnerability")
of this repository. Please include:

- affected version / commit and component (api, worker, web, deployment),
- steps to reproduce or a proof of concept,
- impact assessment as far as known.

We acknowledge reports within **5 working days** and aim to provide a fix or
mitigation within **30 days** for high/critical issues. Reporters are credited in
the release notes unless they prefer otherwise.

## Scope notes

GridPulse is **read-only**: it has no write access to grid control systems and
must never be connected to SCADA networks. Relevant attack surfaces are the public
API (rate limiting, API keys stored as SHA-256 hashes), the admin-token-protected
alert test endpoint, the web frontend (CSP, security headers) and the container
images (non-root, read-only root filesystem, dropped capabilities).

## Supply chain

- GitHub Actions pinned to commit SHAs, `permissions: read-all` by default
- CodeQL, Ruff/Bandit rules, gitleaks, pip-audit, pnpm audit, Trivy, Hadolint
- Release images are multi-arch, signed with cosign (keyless) and ship a CycloneDX SBOM
