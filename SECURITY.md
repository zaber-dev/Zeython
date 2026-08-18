# Security Policy

## Supported versions

Zeython is pre-1.0 (currently `2.0.0a1`) and moving fast — there's no
long-term-support branch yet. Only the latest published release on PyPI
gets security fixes; upgrading to it is the fix for anything reported
against an older one.

| Version        | Supported          |
| -------------- | ------------------ |
| Latest release | :white_check_mark: |
| Anything older | :x:                |

## Reporting a vulnerability

**Please don't open a public GitHub issue for a security vulnerability.**
A public issue gives anyone running Zeython advance notice of an
exploitable problem before a fix exists.

Instead, report it privately through either:

- **GitHub Security Advisories** (preferred): open the repository's
  [Security tab](https://github.com/zaber-dev/Zeython/security) and use
  "Report a vulnerability." This starts a private discussion visible only
  to you and the maintainer, and can turn directly into a coordinated
  advisory once a fix is ready.
- **Email**: zaber@zealtyro.com. Include a description of the issue, the
  affected version, and a minimal reproduction if you have one — the same
  detail a normal bug report needs (see `CONTRIBUTING.md`), plus why it's
  a security concern specifically.

### What to expect

- An acknowledgment within a few days of the report.
- An assessment of severity and, if confirmed, a fix developed privately
  against the report.
- Credit in the fix's release notes and commit message, unless you'd
  rather stay anonymous — say so in the report.
- A CVE/GitHub Security Advisory published once a fix is released, for
  anything that warrants one.

There's no bug bounty program — this is an open-source project without a
funded security budget. Responsible disclosure is still very much
appreciated.

## Scope

This policy covers the `zeython` package itself
(`src/zeython/`) and the code `zeython new` scaffolds into a generated
project. It does not cover:

- Vulnerabilities in a specific application built with Zeython (report
  those to that application's own maintainers).
- Vulnerabilities in Zeython's dependencies (Starlette, SQLAlchemy,
  uvicorn, etc.) — report those upstream; we'll pick up the fix on the
  next dependency bump, and you're welcome to open a normal issue here if
  Zeython needs to react to it (a version pin, a workaround) in the
  meantime.

## A note on defaults

A framework's defaults matter as much as its code. If you find a place
where Zeython's *default* behavior is insecure (a provider that should
default to a safer setting, a scaffold template that ships something
unsafe out of the box), that's in scope here too, even if it's not
exploitable through a single specific code path — see `docs/csrf.md`,
`docs/security-headers.md`, and `docs/authentication.md` for the security
posture the framework aims for by default today.
