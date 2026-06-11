param(
    [string]$Distro = "Ubuntu-24.04"
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    $scriptPath = $PSCommandPath
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$scriptPath`"",
        "-Distro", "`"$Distro`""
    )

    Start-Process powershell -Verb RunAs -ArgumentList $arguments
    Write-Host "Requested administrator privileges. Accept the UAC prompt to continue WSL setup."
    exit 0
}

Write-Host "Enabling Windows optional features required by WSL2..."
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

Write-Host "Setting WSL default version to 2..."
wsl --set-default-version 2

Write-Host "Installing $Distro..."
if ($Distro -eq "Ubuntu-24.04") {
    wsl --install -d Ubuntu-24.04
} else {
    wsl --install -d $Distro
}

Write-Host ""
Write-Host "If Windows asks for a restart, reboot before running Ubuntu initialization."
Write-Host "After Ubuntu opens, create the Linux user when prompted, then run:"
Write-Host "  cd /mnt/d/Projects/LakeShore336"
Write-Host "  bash scripts/setup_epics_wsl.sh"
