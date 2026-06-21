$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$WebDir = Join-Path $Root "v2-web"

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
  $Node = $nodeCmd.Source
} else {
  $BundledNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
  if (-not (Test-Path $BundledNode)) {
    throw "Node.js was not found in PATH and bundled Codex Node.js was not found."
  }
  $Node = $BundledNode
  $env:PATH = "$(Split-Path -Parent $Node);$env:PATH"
}

$pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
if ($pnpmCmd) {
  $PnpmArgs = @($pnpmCmd.Source)
  $PnpmRunner = $Node
} else {
  $BundledPnpm = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\pnpm\bin\pnpm.cjs"
  if (-not (Test-Path $BundledPnpm)) {
    throw "pnpm was not found in PATH and bundled Codex pnpm was not found."
  }
  $PnpmRunner = $Node
  $PnpmArgs = @($BundledPnpm)
}

Push-Location $WebDir
try {
  & $PnpmRunner @PnpmArgs install
  if ($LASTEXITCODE -ne 0) { throw "pnpm install failed with exit code $LASTEXITCODE" }

  & ".\node_modules\.bin\vue-tsc.cmd" --noEmit
  if ($LASTEXITCODE -ne 0) { throw "vue-tsc failed with exit code $LASTEXITCODE" }

  & ".\node_modules\.bin\vite.cmd" build
  if ($LASTEXITCODE -ne 0) { throw "vite build failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}
