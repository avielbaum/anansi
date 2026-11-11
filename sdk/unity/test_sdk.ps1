# Compiles Anansi.cs with Windows PowerShell's built-in C# compiler and checks it against a live local gateway.
# Run (Windows PowerShell 5.1) from the repo root:  powershell -File sdk\unity\test_sdk.ps1
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root
# Delegates are compiled in C#: a PowerShell scriptblock cannot run on the SDK's background continuation thread.
$helpers = @'
namespace Anansi { public static class TestHooks {
  public static System.Func<string> Ticket = () => "dev:76561198000000001";
  public static System.Func<System.Collections.Generic.List<Message>, System.Threading.Tasks.Task<string>> Fallback =
    m => System.Threading.Tasks.Task.FromResult("(local line)");
  public static System.Collections.Generic.List<string> Got = new System.Collections.Generic.List<string>();
  public static System.Action<string> OnSentence = s => { lock (Got) Got.Add(s); };
} }
'@
Add-Type -TypeDefinition ((Get-Content "$PSScriptRoot\Anansi.cs" -Raw) + "`n" + $helpers) -ReferencedAssemblies System.Net.Http, System.Runtime.Serialization, System.Xml

$env:ANANSI_CONFIG = "config.example.json"
$py = (Get-Command python).Source
$procs = @(
  (Start-Process $py "tools\mock_node.py 9001 node-a" -PassThru -WindowStyle Hidden),
  (Start-Process $py "tools\mock_node.py 9002 node-b" -PassThru -WindowStyle Hidden),
  (Start-Process $py "-m uvicorn gateway.app:make_app --factory --port 8080 --log-level warning" -PassThru -WindowStyle Hidden)
)
function Check($ok, $msg) { if (-not $ok) { throw "FAIL: $msg" } else { "PASS $msg" } }
try {
  Start-Sleep 5
  $msgs = New-Object 'System.Collections.Generic.List[Anansi.Message]'
  $m = New-Object Anansi.Message; $m.role = "user"; $m.content = "hello"; $msgs.Add($m)
  $ticket = [Anansi.TestHooks]::Ticket
  $fb = [Anansi.TestHooks]::Fallback

  $c = New-Object Anansi.Client("http://127.0.0.1:8080", "demo", "change-me", $ticket, $fb, 3)
  $r = $c.ChatAsync($msgs, "smith", $false).GetAwaiter().GetResult()
  Check ($r.Source -eq "gateway" -and $r.Say -like "*hello") "gateway reply ($($r.Say))"

  $bad = New-Object Anansi.Client("http://127.0.0.1:8080", "demo", "WRONG", $ticket, $fb, 3)
  $r = $bad.ChatAsync($msgs, "smith", $false).GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback" -and $r.Say -eq "(local line)") "bad key falls back"

  $got = [Anansi.TestHooks]::Got; $on = [Anansi.TestHooks]::OnSentence
  $r = $c.StreamAsync($msgs, $on, "smith").GetAwaiter().GetResult()
  Check ($r.Source -eq "gateway" -and $got.Count -ge 1 -and ($got -join "") -like "*hello" -and $r.Say -eq ($got -join "")) "stream delivers sentences ($($got -join '|'))"
  $got.Clear()
  $r = $bad.StreamAsync($msgs, $on, "smith").GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback" -and $got.Count -eq 1 -and $got[0] -eq "(local line)") "stream falls back once on bad key"

  $procs[2] | Stop-Process -Force; Start-Sleep 1
  $r = $c.ChatAsync($msgs, "smith", $false).GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback") "gateway down falls back"

  $none = New-Object Anansi.Client("http://127.0.0.1:8080", "demo", "change-me", $ticket, $null, 1)
  $r = $none.ChatAsync($msgs, $null, $false).GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback" -and $r.Say -eq "...") "default fallback line"
  $got.Clear()
  $r = $c.StreamAsync($msgs, $on, "smith").GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback" -and $got.Count -eq 1 -and $got[0] -eq "(local line)") "stream with gateway down falls back"
} finally { $procs | ForEach-Object { if (-not $_.HasExited) { Stop-Process -Id $_.Id -Force } } }
