#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Start', 'Status', 'Stop')]
    [string]$Action = 'Start',
    [ValidateRange(1024, 65535)]
    [int]$WebPort = 3100,
    [ValidateRange(1024, 65535)]
    [int]$MediaPort = 9190
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$localRoot = Join-Path $repoRoot '.local/langfuse'
$settingsPath = Join-Path $localRoot '.env'
$upstreamPath = Join-Path $localRoot 'docker-compose.upstream.yml'
$overlayPath = Join-Path $repoRoot 'infra/langfuse/compose.local.yml'
$source = Get-Content -Raw (Join-Path $repoRoot 'infra/langfuse/upstream.json') | ConvertFrom-Json

function New-Secret {
    return [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
}

function Write-NewPrivateFile([string]$Path, [string]$Text) {
    # Never replace existing credentials. The outer lock serializes this script.
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
}

function Read-Settings([string]$Path) {
    $values = [ordered]@{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

if ($WebPort -eq $MediaPort) { throw 'WebPort and MediaPort must be different.' }
New-Item -ItemType Directory -Path $localRoot -Force | Out-Null
# Prevent concurrent first-run setup from generating mismatched keys.
try { $setupLock = [IO.File]::Open((Join-Path $localRoot 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
catch { throw 'Another Langfuse setup command is running. Retry after it finishes.' }
$previousEnvironment = @{}
try {
    if (!(Test-Path -LiteralPath $settingsPath)) {
        if ($Action -in @('Status', 'Stop')) { throw 'No local deployment settings exist. Run -Action Prepare first.' }
        $postgresSecret = New-Secret
        $minioSecret = New-Secret
        $values = [ordered]@{
            TRACEPILOT_LANGFUSE_WEB_PORT = "$WebPort"
            TRACEPILOT_LANGFUSE_MEDIA_PORT = "$MediaPort"
            NEXTAUTH_URL = "http://localhost:$WebPort"
            NEXTAUTH_SECRET = (New-Secret)
            SALT = (New-Secret)
            ENCRYPTION_KEY = (New-Secret)
            POSTGRES_PASSWORD = $postgresSecret
            DATABASE_URL = "postgresql://postgres:$postgresSecret@postgres:5432/postgres"
            CLICKHOUSE_PASSWORD = (New-Secret)
            REDIS_AUTH = (New-Secret)
            MINIO_ROOT_USER = 'tracepilot'
            MINIO_ROOT_PASSWORD = $minioSecret
            LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID = 'tracepilot'
            LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY = $minioSecret
            LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID = 'tracepilot'
            LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY = $minioSecret
            LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT = "http://localhost:$MediaPort"
            LANGFUSE_S3_BATCH_EXPORT_ACCESS_KEY_ID = 'tracepilot'
            LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY = $minioSecret
            LANGFUSE_S3_BATCH_EXPORT_EXTERNAL_ENDPOINT = "http://localhost:$MediaPort"
            LANGFUSE_INIT_ORG_ID = 'tracepilot-local'
            LANGFUSE_INIT_ORG_NAME = 'TracePilot'
            LANGFUSE_INIT_PROJECT_ID = 'tracepilot-pilot'
            LANGFUSE_INIT_PROJECT_NAME = 'TracePilot-Pilot'
            LANGFUSE_INIT_PROJECT_PUBLIC_KEY = ('pk-lf-' + [Guid]::NewGuid().ToString())
            LANGFUSE_INIT_PROJECT_SECRET_KEY = ('sk-lf-' + (New-Secret))
            LANGFUSE_INIT_USER_EMAIL = 'tracepilot@localhost.test'
            LANGFUSE_INIT_USER_NAME = 'TracePilot-Local'
            LANGFUSE_INIT_USER_PASSWORD = (New-Secret)
            TELEMETRY_ENABLED = 'false'
        }
        Write-NewPrivateFile $settingsPath (($values.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n")
    }
    $settings = Read-Settings $settingsPath
    foreach ($key in @('TRACEPILOT_LANGFUSE_WEB_PORT', 'TRACEPILOT_LANGFUSE_MEDIA_PORT', 'NEXTAUTH_URL', 'LANGFUSE_INIT_PROJECT_PUBLIC_KEY', 'LANGFUSE_INIT_PROJECT_SECRET_KEY')) {
        if (!$settings[$key]) { throw "Missing $key in local deployment settings; restore the existing configuration." }
    }
    if (($PSBoundParameters.ContainsKey('WebPort') -and "$WebPort" -ne $settings.TRACEPILOT_LANGFUSE_WEB_PORT) -or
        ($PSBoundParameters.ContainsKey('MediaPort') -and "$MediaPort" -ne $settings.TRACEPILOT_LANGFUSE_MEDIA_PORT)) {
        throw 'Existing ports are preserved. Update the local settings and matching URLs deliberately before changing ports.'
    }

    if (!(Test-Path -LiteralPath $upstreamPath)) {
        $downloadPath = Join-Path $localRoot 'docker-compose.download.yml'
        Invoke-WebRequest -Uri $source.compose_url -OutFile $downloadPath -TimeoutSec 60
        if ((Get-FileHash -Algorithm SHA256 $downloadPath).Hash.ToLowerInvariant() -ne $source.compose_sha256) {
            throw 'Upstream Compose checksum mismatch; deployment was not started.'
        }
        Move-Item -LiteralPath $downloadPath -Destination $upstreamPath
    }
    if ((Get-FileHash -Algorithm SHA256 $upstreamPath).Hash.ToLowerInvariant() -ne $source.compose_sha256) {
        throw 'Cached upstream Compose differs from the pinned source; deployment was not started.'
    }

    $sdkPath = Join-Path $localRoot 'sdk.env'
    $sdkText = @(
        "LANGFUSE_BASE_URL=$($settings.NEXTAUTH_URL)"
        "LANGFUSE_PUBLIC_KEY=$($settings.LANGFUSE_INIT_PROJECT_PUBLIC_KEY)"
        "LANGFUSE_SECRET_KEY=$($settings.LANGFUSE_INIT_PROJECT_SECRET_KEY)"
    ) -join "`n"
    if (!(Test-Path -LiteralPath $sdkPath)) { Write-NewPrivateFile $sdkPath $sdkText }
    $repoEnvPath = Join-Path $repoRoot '.env.local'
    if (!(Test-Path -LiteralPath $repoEnvPath)) { Write-NewPrivateFile $repoEnvPath $sdkText }

    # Override inherited shell values only inside this process, then restore them.
    # This keeps service credentials consistent with the generated settings file.
    foreach ($entry in $settings.GetEnumerator()) {
        $previousEnvironment[$entry.Key] = @{
            Exists = Test-Path -LiteralPath "Env:$($entry.Key)"
            Value = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
        }
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
    $composeArgs = @('compose', '--parallel', '1', '--project-name', 'tracepilot-langfuse', '--project-directory', $localRoot,
        '--env-file', $settingsPath, '-f', $upstreamPath, '-f', $overlayPath)
    & docker @composeArgs config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration validation failed.' }
    switch ($Action) {
        'Prepare' { Write-Host 'Local settings and pinned Compose files are ready; no containers were started.' }
        'Start' {
            & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Docker is not ready. Start Docker Desktop and rerun this script.' }
            & docker @composeArgs up -d
            if ($LASTEXITCODE -ne 0) { throw 'Langfuse startup failed; existing data volumes were preserved.' }
            Write-Host 'Containers started. Check /api/public/health before using the SDK.'
        }
        'Status' { & docker @composeArgs ps }
        'Stop' { & docker @composeArgs stop }
    }
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed: $Action" }
    Write-Host "Langfuse URL: $($settings.NEXTAUTH_URL)"
    Write-Host "SDK environment: $sdkPath (existing .env.local is never overwritten)"
    Write-Host "Local UI login: LANGFUSE_INIT_USER_EMAIL / LANGFUSE_INIT_USER_PASSWORD in $settingsPath"
}
finally {
    foreach ($entry in $previousEnvironment.GetEnumerator()) {
        if ($entry.Value.Exists) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value.Value, 'Process')
        }
        else { Remove-Item -LiteralPath "Env:$($entry.Key)" -ErrorAction SilentlyContinue }
    }
    $setupLock.Dispose()
}
