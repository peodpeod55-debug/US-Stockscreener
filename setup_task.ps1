# ลงทะเบียน Task Scheduler ให้ bot รันอัตโนมัติตอน logon
$action = New-ScheduledTaskAction -Execute "$PSScriptRoot\run_bot.bat" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "USEarningsScreenerBot" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "ลงทะเบียน Task 'USEarningsScreenerBot' แล้ว — จะรันอัตโนมัติตอน logon"
