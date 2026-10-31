# Creates two mock meetings with Windows' built-in text-to-speech (16 kHz, 16-bit, mono WAV)
# plus manifest.json in sample-recordings/. Different voices stand in for different people.
$ErrorActionPreference = "Stop"
$dir = Resolve-Path (Join-Path $PSScriptRoot "..\sample-recordings")
Add-Type -AssemblyName System.Speech
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$probe = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = @($probe.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
$probe.Dispose()

function New-Meeting($file, $lines) {
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.SetOutputToWaveFile((Join-Path $dir $file), $fmt)
    $pb = New-Object System.Speech.Synthesis.PromptBuilder
    $i = 0
    foreach ($line in $lines) {
        if ($voices.Count -gt 0) { $pb.StartVoice($voices[$i % $voices.Count]) }
        $pb.AppendText($line)
        if ($voices.Count -gt 0) { $pb.EndVoice() }
        $pb.AppendBreak([TimeSpan]::FromMilliseconds(700))
        $i++
    }
    $s.Speak($pb)
    $s.Dispose()
    Write-Host "  created $file"
}

New-Meeting "rec_01_vendor_call.wav" @(
    "Good morning Ravi, thanks for joining. This is Priya from Northwind.",
    "Morning Priya. Let's confirm the order for two hundred sensor units.",
    "Yes. We will send the purchase order by Thursday.",
    "Great. Please also confirm the delivery address in Salt Lake, Kolkata, before Friday.",
    "Delivery takes ten working days after we receive the purchase order.",
    "Let's do a review call on the fifth of November at three p m."
)
New-Meeting "rec_02_team_standup.wav" @(
    "Okay team, quick stand up.",
    "Arjun here. I finished the login page. Today I will fix the upload bug.",
    "Meera here. I am blocked on the payment API keys. Priya, can you share them by tomorrow?",
    "Priya here. Yes, I will send the keys by tomorrow morning.",
    "Also, the client demo has moved to next Monday.",
    "Let's meet again at the same time tomorrow."
)

@'
[
  { "file": "rec_01_vendor_call.wav", "device_id": "rec-demo", "recorded_at": "2026-11-03T10:05:00+05:30" },
  { "file": "rec_02_team_standup.wav", "device_id": "rec-demo", "recorded_at": "2026-11-03T15:30:00+05:30" }
]
'@ | Set-Content -Encoding UTF8 (Join-Path $dir "manifest.json")
Write-Host "  created manifest.json"
