param(
    [string]$DailyTime = "06:15",
    [string]$OosTime = "12:15",
    [string]$WeeklyTime = "07:30",
    [switch]$SkipWeeklyAlerts
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$scheduledDir = (Resolve-Path (Join-Path $PSScriptRoot "scheduled")).Path
$dailyCmd = (Resolve-Path (Join-Path $scheduledDir "daily-job.cmd")).Path
$oosCmd = (Resolve-Path (Join-Path $scheduledDir "oos-job.cmd")).Path
$weeklyCmd = if ($SkipWeeklyAlerts) {
    (Resolve-Path (Join-Path $scheduledDir "weekly-job-noalerts.cmd")).Path
} else {
    (Resolve-Path (Join-Path $scheduledDir "weekly-job.cmd")).Path
}

function Invoke-Schtasks {
    param(
        [Parameter(Mandatory = $true)][string[]]$Args
    )
    & schtasks @Args | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks failed: schtasks $($Args -join ' ')"
    }
}

function Register-OrReplaceTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$Schedule,
        [Parameter(Mandatory = $true)][string]$StartTime,
        [Parameter(Mandatory = $true)][string]$TaskRun,
        [int]$Modifier = 1
    )

    & schtasks /Query /TN $TaskName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Invoke-Schtasks -Args @("/Delete", "/TN", $TaskName, "/F")
    }

    $createArgs = @(
        "/Create",
        "/TN", $TaskName,
        "/TR", $TaskRun,
        "/SC", $Schedule,
        "/ST", $StartTime,
        "/MO", "$Modifier",
        "/RL", "LIMITED",
        "/F"
    )

    Invoke-Schtasks -Args $createArgs
    $everyText = if ($Modifier -gt 1) { " every $Modifier intervals" } else { "" }
    Write-Host "Registered task: $TaskName ($Schedule$everyText @ $StartTime)"
}

Register-OrReplaceTask -TaskName "SupplierDashboard-Daily" -Schedule "DAILY" -StartTime $DailyTime -TaskRun $dailyCmd
Register-OrReplaceTask -TaskName "SupplierDashboard-OOS-Every2Days" -Schedule "DAILY" -StartTime $OosTime -TaskRun $oosCmd -Modifier 2
Register-OrReplaceTask -TaskName "SupplierDashboard-Weekly" -Schedule "WEEKLY" -StartTime $WeeklyTime -TaskRun $weeklyCmd

Write-Host ""
Write-Host "Task registration complete."
Write-Host "Project root: $projectRoot"
Write-Host "Scheduled dir: $scheduledDir"
