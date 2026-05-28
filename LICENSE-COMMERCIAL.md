# Commercial License — Myah

Myah is dual-licensed. The default license is AGPL-3.0-or-later (see
[LICENSE](./LICENSE)). For use cases that AGPL does not permit — closed-source
SaaS deployments that don't release modifications to network users, embedded
distribution in proprietary products, etc. — a commercial license is available.

## When you need a commercial license

You should consider a commercial license if any of these apply to your use:

- You're operating a multi-tenant SaaS product based on Myah and don't want
  to release your modifications to your users under AGPL Section 13.
- You're embedding Myah into a closed-source commercial product.
- Your organization's legal policy forbids AGPL-licensed code in commercial
  deliverables.

## Inquiries

For commercial licensing inquiries, contact: **hello@myah.dev**

Please include:
- Your company name and use case (1-2 sentences).
- Whether the deployment is single-tenant, multi-tenant, or embedded.
- Expected user count or deployment scale (rough is fine).

We'll reply with pricing and terms.

## Why AGPL + commercial dual-license?

Same playbook as MongoDB (SSPL → AGPL transition), Plausible, Sentry, Cal.com,
Posthog, and many other modern OSS-first companies.

- **AGPL** protects the project from a SaaS competitor forking it and offering
  it as a closed-source paid service without contributing back. The network-use
  clause (AGPL §13) requires anyone who runs a modified version on a server
  to make their modifications available to the users of that server.
- **Commercial license** is the proper path for companies whose business model
  is incompatible with AGPL §13. We'd rather have them as paying customers
  than not have them at all.

For 99% of OSS users — anyone running Myah for personal use, internal company
use, or a project that already releases its source — **AGPL is the right
license and no further action is needed**.
