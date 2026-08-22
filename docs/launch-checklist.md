# Production launch decision checklist

Use this checklist to select HealthScope's production platform and record the
evidence required for a go/no-go launch decision. It complements the
[deployment runbook](deployment.md): this document decides whether a platform
can satisfy the contract, while the runbook contains the deployment commands.

Do not place passwords, tokens, database URLs, or other secret values in this
file. Record the secret-manager entry name or other non-secret evidence instead.

## Decision record

Complete these fields in a private launch ticket or an approved copy of this
template before provisioning begins.

| Decision | Recorded value |
| --- | --- |
| Decision owner | Pending |
| Application host and plan | Pending |
| Managed PostgreSQL provider and plan | Pending |
| Primary region | Pending |
| Public hostname and DNS owner | Pending |
| Scheduler mechanism and daily UTC time | Pending |
| Uptime and ingestion monitor owner | Pending |
| Backup retention and point-in-time recovery window | Pending |
| Monthly budget ceiling and alert threshold | Pending |
| Target release full commit SHA | Pending |
| Planned launch window and rollback owner | Pending |

The application and database should use the same region unless the decision
record explicitly accepts the latency, availability, and data-egress impact.

## Provider hard gates

A candidate passes only when every row has concrete evidence. A feature name on
a pricing page is not sufficient when the capability depends on a higher plan
or an account-specific quota.

| Gate | Acceptance evidence |
| --- | --- |
| Container release | Runs the repository preflight, then pulls both private or public GHCR images by its attestation-verified immutable digests without rebuilding them. |
| Process model | Runs the long-lived frontend and API plus one-shot migration and ingestion commands from the reviewed images. |
| Private networking | Exposes only the Nginx frontend publicly; the API is reachable by the frontend but not directly from the internet. |
| TLS and routing | Terminates HTTPS for the chosen hostname and preserves the application's security, cache, and request-ID headers. |
| Secret handling | Injects the database URL and optional FDA key without committing them or placing them in image layers, scheduler definitions, or ordinary logs. |
| Managed PostgreSQL | Supplies a PostgreSQL connection with required TLS, automated backups, point-in-time recovery, documented connection limits, and a supported restore workflow. |
| Migration ordering | Can require the one-shot Alembic migration to succeed before the new API receives traffic. |
| Daily scheduling | Runs the ingestion image every day, prevents overlapping executions, preserves output, and alerts on a nonzero exit. |
| Health monitoring | Polls public liveness, readiness, and ingestion-health endpoints and alerts the named owner on failures. |
| Operational logs | Retains frontend, API, migration, and ingestion logs long enough to diagnose a failed daily run using `X-Request-ID`. |
| Rollback | Redeploys the previous matching API/frontend image pair without automatically downgrading the database. |
| Capacity and cost | Documents memory, CPU, database storage/connections, outbound traffic, scheduler limits, sleep behavior, and budget alerts for the selected plans. |

Reject platforms that cannot meet a hard gate. Record optional conveniences
such as managed custom domains or integrated monitoring separately; they must
not compensate for a missing safety requirement.

## Minimum provisioning input

The person authorizing deployment must provide or approve all of the following:

- the selected host, managed PostgreSQL service, plans, and common region;
- the public hostname plus authority to update its DNS records;
- access scoped to create the application services, scheduled job, monitors,
  secrets, and database, without sharing credentials in the repository;
- a production database role and database with a TLS-required SQLAlchemy URL,
  delivered through the platform secret manager;
- the GHCR package visibility decision or a read-only package credential stored
  as a host registry credential, not an application secret;
- the daily UTC ingestion time, alert destination/owner, log retention, backup
  retention, point-in-time recovery window, and monthly budget ceiling; and
- the approved full commit SHA for both production images, the two preflight-
  verified registry digests, and the launch window.

Until this input exists, production provisioning, data ingestion, monitoring,
and restore validation remain blocked. Repository work may improve the reviewed
release contract, but it cannot substitute for these operational decisions.

## Launch acceptance sequence

Execute these gates in order and attach non-secret evidence to the launch
ticket. Stop at the first failure and follow the runbook's rollback guidance.

- [ ] Provider decision: every hard gate has evidence and named ownership.
- [ ] Database: managed PostgreSQL is in the selected region, TLS is required,
  automated backups and point-in-time recovery are enabled, and connection
  limits are recorded.
- [ ] Release: matching API and frontend images use the same reviewed full SHA;
  their registry digests and GitHub provenance/SBOM attestations are recorded.
- [ ] Configuration: production secrets are stored outside Git, Compose
  configuration succeeds with the production env file, and no placeholder or
  default credential remains.
- [ ] Migration and deploy: Alembic reaches the current head before the API is
  routed, only the frontend is public, and HTTPS is valid for the public host.
- [ ] Runtime contract: `/api/v1/health`, `/api/v1/ready`, and `/overview`
  succeed through the public URL; liveness reports the approved full release
  SHA, and security/cache headers plus `X-Request-ID` propagation match the
  runbook.
- [ ] Initial live ingestion: the one-shot CMS job reports equal expected,
  fetched, and upserted counts with a succeeded run ID; no fabricated or bundled
  healthcare records are loaded.
- [ ] Monitoring: liveness, readiness, and ingestion-health monitors are active;
  a controlled failure reaches the named alert owner and can be correlated to
  logs without query strings or response bodies.
- [ ] Scheduling: the daily CMS ingestion runs at the approved UTC time,
  the database-backed overlap rejection is exercised, and a forced nonzero exit
  triggers an alert.
- [ ] Backup restore: a production backup is restored into an isolated database,
  `healthscope-verify-restore` confirms the backed-up migration revision plus
  row/completion/run integrity before any migration or ingestion is run there,
  and aggregate evidence is retained without exposing records or credentials.
- [ ] Recovery: the previous matching image pair is redeployed in a controlled
  exercise without an automatic Alembic downgrade, then the approved release is
  restored.
- [ ] Sign-off: the decision owner, monitor owner, database owner, and rollback
  owner approve launch and record any accepted residual risk.

## Launch evidence to retain

Keep the following outside the repository when it includes account details:

- the provider decision record and plan/quota evidence;
- target SHA, image digests, and successful attestation verification output;
- migration revision, deployment time, runtime release SHA, and public endpoint
  check results;
- initial ingestion run ID and counts;
- monitor and scheduler test events with owner acknowledgement;
- backup identifier, isolated restore time, integrity results, and cleanup
  confirmation; and
- the last known-good image pair and rollback exercise result.

Launch is complete only when every acceptance item is checked. A green CI build
proves the provider-neutral release contract; it does not prove that a selected
production account, database, scheduler, monitor, or backup has been configured.
