# Local Langfuse

This development deployment downloads the unmodified official Compose file at
the commit and SHA-256 recorded in [upstream.json](upstream.json). The small
[overlay](compose.local.yml) pins Langfuse 4.50.0 and all service image digests, restricts published ports to
loopback, and adds log rotation. Upstream application code is not vendored.

Requires PowerShell 7, Docker Desktop with Linux containers, and Docker Compose
2.24.4 or newer. Start Docker Desktop before running:

```powershell
./scripts/start-langfuse.ps1
./scripts/start-langfuse.ps1 -Action Status
```

The UI is at `http://localhost:3100`. Use `/api/public/health` to check readiness;
container startup alone does not confirm that database migrations have finished.
`-Action Prepare` prepares and validates configuration without starting containers.
First-run `-WebPort` and `-MediaPort` options default to 3100 and 9190.

Secrets are generated once in ignored `.local/langfuse/.env`. The UI login uses
`LANGFUSE_INIT_USER_EMAIL` and `LANGFUSE_INIT_USER_PASSWORD` from that file.
SDK credentials are saved in `.local/langfuse/sdk.env`, and in `.env.local` only
when that file does not already exist. Load one of these files explicitly in the
calling application; the Langfuse SDK does not load it automatically.

The deployment uses the separate Docker Compose project `tracepilot-langfuse`
and named data volumes. Compose operations use parallelism 1 to reduce initial
image extraction pressure on local machines. Re-running preserves credentials
and data. To stop:

```powershell
./scripts/start-langfuse.ps1 -Action Stop
```

Do not delete the local credentials while retaining the data volumes: existing
database passwords, encryption keys, and headless initialization records will
not automatically change. This single-machine setup is for the integration pilot.

Sources: [official deployment guide](https://langfuse.com/self-hosting/deployment/docker-compose)
and [headless initialization](https://langfuse.com/self-hosting/administration/headless-initialization).
