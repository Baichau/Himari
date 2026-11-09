param(
    [switch]$SkipTests,
    [switch]$AllowMissingSpeechAssets,
    [switch]$RequireOllama
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

if ($env:OS -ne "Windows_NT") {
    throw "Himari's release must be built on Windows."
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $python = $pythonCommand.Source
}

$pythonInfo = & $python -c "import platform,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{platform.architecture()[0]}|{sys.platform}')"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the Python build environment."
}
$pythonParts = $pythonInfo -split "\|"
$versionParts = $pythonParts[0] -split "\."
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]
if ($major -ne 3 -or $minor -lt 10 -or $minor -gt 13 -or $pythonParts[1] -ne "64bit" -or $pythonParts[2] -ne "win32") {
    throw "Use 64-bit Windows Python 3.10 through 3.13; found $pythonInfo."
}

$pyinstallerVersion = (& $python -m PyInstaller --version).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is missing. Install project dependencies before building."
}
$buildRequirement = Get-Content -LiteralPath (Join-Path $root "requirements-build.txt") |
    Where-Object { $_ -match "^PyInstaller==" } |
    Select-Object -First 1
if (-not $buildRequirement) {
    throw "requirements-build.txt does not pin PyInstaller."
}
$requiredPyInstaller = $buildRequirement -replace "^PyInstaller==", ""
if ($pyinstallerVersion -ne $requiredPyInstaller) {
    throw "Build requires PyInstaller $requiredPyInstaller; found $pyinstallerVersion."
}

& $python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "The active Python environment has broken dependencies."
}

$smokeData = Join-Path $env:TEMP ("himari-build-tests-" + [guid]::NewGuid().ToString("N"))
$savedHome = $env:HIMARI_HOME
try {
    $env:HIMARI_HOME = $smokeData
    if (-not $SkipTests) {
        & $python -m compileall -q himari tests
        if ($LASTEXITCODE -ne 0) {
            throw "Python syntax checks failed."
        }
        & $python -m pytest -q tests
        if ($LASTEXITCODE -ne 0) {
            throw "The project test suite failed."
        }
    }
} finally {
    if ($null -eq $savedHome) {
        Remove-Item Env:\HIMARI_HOME -ErrorAction SilentlyContinue
    } else {
        $env:HIMARI_HOME = $savedHome
    }
    if (Test-Path -LiteralPath $smokeData) {
        Remove-Item -LiteralPath $smokeData -Recurse -Force
    }
}

& $python (Join-Path $root "prepare_release_assets.py")
if ($LASTEXITCODE -ne 0) {
    throw "Local speech asset staging failed."
}

$stagedModels = @(
    Get-ChildItem -LiteralPath (Join-Path $root "models") -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -ne "piper-voices" -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "config.json")) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "model.bin"))
        }
)
$stagedVoices = @(
    Get-ChildItem -LiteralPath (Join-Path $root "models\piper-voices") -Filter "*.onnx" -File -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath ($_.FullName + ".json") }
)
if ((-not $stagedModels.Count -or -not $stagedVoices.Count) -and -not $AllowMissingSpeechAssets) {
    throw "A local Faster-Whisper model and Piper voice are required. Prepare them locally or rerun with -AllowMissingSpeechAssets for a chat-only build."
}

# ONEFILE: the output is a single release\Himari.exe
$releaseRoot = Join-Path $root "release"
$exe = Join-Path $releaseRoot "Himari.exe"
if (Test-Path -LiteralPath $exe) {
    throw "Output already exists: $exe. Move or remove it before rebuilding."
}
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$workPath = Join-Path $root ".build\pyinstaller"
New-Item -ItemType Directory -Path $workPath -Force | Out-Null

& $python -m PyInstaller --clean --noconfirm `
    --distpath $releaseRoot `
    --workpath $workPath `
    (Join-Path $root "Himari.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed; inspect the build output above."
}

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "PyInstaller completed without the expected onefile executable: $exe"
}

$testHome = Join-Path $env:TEMP ("himari-packaged-smoke-" + [guid]::NewGuid().ToString("N"))
$savedHome = $env:HIMARI_HOME
$env:HIMARI_HOME = $testHome
try {
    $arguments = @("--self-test", "--gui")
    if ($RequireOllama) {
        $arguments += "--require-ollama"
    }
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -PassThru -Wait -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        $logPath = Join-Path $testHome "logs\himari.log"
        if (Test-Path -LiteralPath $logPath) {
            Get-Content -LiteralPath $logPath -Tail 80
        }
        throw "Packaged smoke test failed with exit code $($process.ExitCode)."
    }
    $logPath = Join-Path $testHome "logs\himari.log"
    if (-not (Test-Path -LiteralPath $logPath)) {
        throw "Packaged app did not create its user-data log file."
    }
    if (-not (Select-String -LiteralPath $logPath -Pattern "Packaged main-window smoke test completed" -Quiet)) {
        Get-Content -LiteralPath $logPath -Tail 80
        throw "Packaged app did not complete its main-window smoke test."
    }
    Write-Output "Packaged app smoke test passed."
} finally {
    if ($null -eq $savedHome) {
        Remove-Item Env:\HIMARI_HOME -ErrorAction SilentlyContinue
    } else {
        $env:HIMARI_HOME = $savedHome
    }
    if (Test-Path -LiteralPath $testHome) {
        Remove-Item -LiteralPath $testHome -Recurse -Force
    }
}

Write-Output "Single-file executable: $exe"
Write-Output "Bundled Faster-Whisper models: $($stagedModels.Name -join ', ')"
Write-Output "Bundled Piper voices: $($stagedVoices.BaseName -join ', ')"
Write-Output "External runtime dependency: Ollama (install separately; prepare the selected model manually)."