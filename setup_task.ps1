# Register Task Scheduler entry so the bot starts automatically at logon
# NOTE: keep this file ASCII-only — PowerShell 5.1 misreads BOM-less UTF-8 as ANSI
$action = New-ScheduledTaskAction -Execute "$PSScriptRoot\run_bot.bat" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "USEarningsScreenerBot" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Task 'USEarningsScreenerBot' registered - the bot will start automatically at logon."
