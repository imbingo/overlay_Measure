param(
    [string]$Python = "python",
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$InstallerDir = Join-Path $Root "installer"
$DistDir = Join-Path $Root "dist"
$BuildDir = Join-Path $Root "build"
$ReleaseDir = Join-Path $Root "release"

Push-Location $Root
try {
    $RuntimeCheck = (& $Python -c "import struct, sys; bitness = struct.calcsize('P') * 8; supported = (3, 10) <= sys.version_info[:2] < (3, 14) and bitness == 64; print('supported' if supported else f'unsupported:{sys.version.split()[0]}:{bitness}-bit')").Trim()
    if ($LASTEXITCODE -ne 0 -or $RuntimeCheck -ne "supported") {
        throw "Release builds require 64-bit Python 3.10-3.13. Detected: $RuntimeCheck"
    }

    $Version = (& $Python -c "from overlay_measure import __version__; print(__version__)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Version) {
        throw "Unable to read the application version."
    }
    Write-Host "Building SOMA Vision Metrology V$Version" -ForegroundColor Cyan

    if (-not $SkipTests) {
        & $Python -m pytest -q
        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed. Release build stopped."
        }
    }

    New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
    & $Python ".\scripts\generate_release_metadata.py" `
        --version $Version `
        --version-file ".\installer\generated_version_info.txt"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to generate Windows version metadata."
    }

    Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $DistDir `
        --workpath $BuildDir `
        ".\installer\overlay_measure.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    $PackagedExe = Join-Path $DistDir "OverlayMeasure\OverlayMeasure.exe"
    if (-not (Test-Path $PackagedExe)) {
        throw "Packaged executable was not found: $PackagedExe"
    }
    $Smoke = Start-Process -FilePath $PackagedExe -ArgumentList "--smoke-test" -WindowStyle Hidden -Wait -PassThru
    if ($Smoke.ExitCode -ne 0) {
        throw "Packaged smoke test failed with exit code $($Smoke.ExitCode)."
    }

    if ($SkipInstaller) {
        Write-Host "One-folder application created: $DistDir\OverlayMeasure" -ForegroundColor Green
        return
    }

    $IsccCandidates = @(
        (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    $Iscc = $IsccCandidates | Select-Object -First 1
    if (-not $Iscc) {
        throw "Inno Setup 6 is not installed. Install it or use -SkipInstaller."
    }

    & $Iscc "/DAppVersion=$Version" ".\installer\OverlayMeasure.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }

    $Setup = Join-Path $ReleaseDir "SOMA_Vision_Metrology_V${Version}_Setup.exe"
    if (-not (Test-Path $Setup)) {
        throw "Installer was not found: $Setup"
    }
    & $Python ".\scripts\generate_release_metadata.py" `
        --version $Version `
        --artifact $Setup `
        --manifest (Join-Path $ReleaseDir "update_manifest.json")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to generate the update manifest."
    }
    Write-Host "Release build completed: $Setup" -ForegroundColor Green
}
finally {
    Pop-Location
}
