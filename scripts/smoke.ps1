# Windows PowerShell: .\scripts\smoke.ps1 -Clip .\sample-recordings\rec_01_vendor_call.wav
param([Parameter(Mandatory=$true)][string]$Clip, [string]$Server = "http://localhost:8000")
$ts = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss") + "+05:30"
foreach ($n in 1..2) {
  curl.exe -s -w " HTTP %{http_code}`n" -F "audio=@$Clip" -F "device_id=rec-smoke" -F "recorded_at=$ts" -F "duration_ms=" -F "battery_pct=" "$Server/upload"
}
$id = "rec-smoke_" + $ts.Replace(":", "-")
$enc = [uri]::EscapeDataString($id)
$start = Get-Date
do {
  Start-Sleep -Seconds 2
  $status = (Invoke-RestMethod "$Server/recordings/$enc").status
  Write-Host ("  {0:N0}s  {1}" -f ((Get-Date) - $start).TotalSeconds, $status)
} until ($status -in @("done", "failed") -or ((Get-Date) - $start).TotalSeconds -gt 120)
