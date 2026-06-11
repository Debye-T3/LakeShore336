param(
    [string]$LogPath = "D:\Projects\LakeShore336\wsl-diagnostics.log"
)

$ErrorActionPreference = "Continue"

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
        "-LogPath", "`"$LogPath`""
    )

    Start-Process powershell -Verb RunAs -ArgumentList $arguments
    Write-Host "Requested administrator privileges. Accept the UAC prompt to write WSL diagnostics."
    exit 0
}

"=== WSL diagnostics $(Get-Date -Format o) ===" | Set-Content -Path $LogPath -Encoding UTF8

function Add-Section {
    param(
        [string]$Title,
        [scriptblock]$Command
    )

    Add-Content -Path $LogPath -Value ""
    Add-Content -Path $LogPath -Value "=== $Title ==="
    try {
        & $Command 2>&1 | Out-String | Add-Content -Path $LogPath
    } catch {
        "ERROR: $($_.Exception.Message)" | Add-Content -Path $LogPath
    }
}

Add-Section "wsl --status" { wsl --status }
Add-Section "wsl --version" { wsl --version }
Add-Section "wsl --list --verbose" { wsl --list --verbose }
Add-Section "WSL optional feature" {
    dism.exe /online /get-featureinfo /featurename:Microsoft-Windows-Subsystem-Linux
}
Add-Section "matching optional feature names" {
    dism.exe /online /get-features /format:table | Select-String -Pattern "Subsystem|Linux|Virtual|Hyper|Machine|WSL"
}
Add-Section "Virtual Machine Platform optional feature" {
    dism.exe /online /get-featureinfo /featurename:VirtualMachinePlatform
}
Add-Section "Hyper-V optional feature" {
    dism.exe /online /get-featureinfo /featurename:Microsoft-Hyper-V-All
}
Add-Section "bcdedit current" { bcdedit /enum "{current}" }
Add-Section "computer system virtualization" {
    Get-CimInstance Win32_ComputerSystem | Select-Object HypervisorPresent
}
Add-Section "processor virtualization flags" {
    Get-CimInstance Win32_Processor | Select-Object Name,VirtualizationFirmwareEnabled,SecondLevelAddressTranslationExtensions,VMMonitorModeExtensions
}

Write-Host "Wrote diagnostics to $LogPath"
