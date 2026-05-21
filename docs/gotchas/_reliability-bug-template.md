# <Bug title>

**Status:** Investigating | Verified
**Reported:** YYYY-MM-DD
**Affects:** OSS | hosted | both
**Severity:** P0 | P1 | P2 | P3
**Reproduction confidence:** high | medium | low

## Symptom

What does the user see? Be specific — quote the exact error message,
DOM state, or behavior description.

## Reproduction

Step-by-step reproduction. Include version pins (plugin SHA, Hermes SHA,
platform commit) at the bottom of the section.

## Root cause

What's actually broken in the code. Reference specific files + lines.

## Evidence of fix

REQUIRED to flip Status to Verified. Include AT LEAST 2 of:
- Smoke-test green run URL (after the fix landed)
- Sentry event ID + resolved-state link
- Browser screenshot showing the working state
- Production verification command output
- Manual repro confirming the bug no longer reproduces

**Observability evidence rule (Task 5.4):** every reliability bug card
must surface concrete observability proof that the fix landed and the
bug is gone. "Verified by code review" is NOT sufficient. The bug must
either (a) emit a distinctive Sentry breadcrumb / log event that
disappears post-fix, OR (b) be covered by a smoke-test step that
asserts the working behavior.

## Workaround (if any)

For users still on a version without the fix.

## Tracking

- Linear / issue link
- PR(s) that fix it
- Plugin SHA that ships the fix (if applicable)
