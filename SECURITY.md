# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately through GitHub instead: open the repository's
**Security** tab and choose **Report a vulnerability**. Include the affected
endpoint or file, the steps to reproduce, and what an attacker gains.

You can expect an acknowledgement within a week. Once a fix is released, the
advisory is published with credit to you, unless you would rather stay
anonymous.

## Supported versions

Only the latest commit on `main` receives security fixes.

## What is in scope

ragleitus stores other people's LLM provider keys and documents, so these are
the reports that matter most:

- **Provider keys:** reading another user's key, or reading a key in
  plaintext. Keys are encrypted at rest with Fernet (`PROVIDER_KEY_SECRET`) and
  must only ever leave the API masked.
- **Tenant isolation:** reading, searching, chatting over or deleting another
  user's documents, conversations, evaluations or telemetry.
- **Authentication:** forging or replaying access tokens (HS256 JWTs signed
  with `JWT_SECRET`), bypassing password checks, or getting past the per-account
  login limit.
- **Server-side request forgery:** making the server call a private or
  loopback address through a custom provider URL while
  `ALLOW_PRIVATE_PROVIDER_URLS` is `false`.
- **Rate limiting:** evading the limits with spoofed `X-Forwarded-For` when
  the request does not come from a host in `TRUSTED_PROXIES`.
- **Uploads:** a crafted PDF, Markdown or text file that runs code, reads
  files on the server, or exhausts memory despite `MAX_UPLOAD_MB`.

## What is not in scope

- Deployments that set `ALLOW_PRIVATE_PROVIDER_URLS=true`, which deliberately
  lets users point the server at internal addresses.
- Weak values chosen for `JWT_SECRET`, `PROVIDER_KEY_SECRET` or
  `POSTGRES_PASSWORD`.
- Vulnerabilities in a dependency with no demonstrated impact on ragleitus.
  Report those to the dependency.
- What an LLM provider does with the prompts it is sent, including prompt
  injection through an uploaded document, unless it leads to one of the
  in-scope problems above.
