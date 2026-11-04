# Security rollout — 2026-11-04

## Phase 1: backend authentication

- Remembered login now uses a server-private signing key, never a password hash.
- Version-1 remembered-login cookies are rejected. Users must sign in again.
- Credential changes invalidate remembered-login signatures.
- Optional `AUTH_COOKIE_SECRET` must contain at least 32 bytes and remain server-only. Without it, a private random key is generated for the running process; server restarts intentionally invalidate remembered login.
- Both additional account creation/save paths now hash passwords before persistence.
- Database client prefers server-only `SUPABASE_SECRET_KEY`, then `SUPABASE_SERVICE_ROLE_KEY`, retaining existing key fallback only during the coordinated rollout.
- Tests use synthetic credentials only and do not write business data.

## Still open — not a complete security remediation

The existing database has anonymous access grants and permissive policies. All applications sharing it must first be migrated to server-authorized access. Configuring a server key does not itself secure the database or implement per-user authorization.

Before removing grants: validate old backend login, administrator-only account/import operations, both new frontend deployments, data-scope authorization, automatic import consumers, views and RPC dependencies. Then apply reviewed grants/RLS changes and verify anonymous reads/writes are denied without destructive test writes.

Do not print keys, copy secrets into source, revoke all old keys blindly, or claim Phase 1 eliminates the public-table exposure.
