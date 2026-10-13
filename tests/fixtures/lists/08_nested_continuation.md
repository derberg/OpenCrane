## Retries

- Option A: retry policy
  applies to idempotent calls only
  - Only applies when server returns 5xx
    and the request carries a retry header
  - Ignored for 4xx

  Option A also logs every retry.
- Option B: timeout policy
