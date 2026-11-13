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
  public static World World = MakeWorld();
  static World MakeWorld() { var w = new World(); w.npcs.Add(new Entity { id = "brom", name = "Brom", role = "blacksmith" }); w.locations.Add(new Entity { id = "mill", name = "Old Mill" }); w.items.Add(new Entity { id = "ore", name = "Iron ore" }); return w; }
  public static System.Func<World, System.Threading.Tasks.Task<Quest>> QuestFallback =
    w => System.Threading.Tasks.Task.FromResult(new Quest { title = "Authored", steps = new System.Collections.Generic.List<QuestStep>() });
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
  $w = [Anansi.TestHooks]::World
  $q = $c.QuestAsync($w, 2, "mining", "normal", $null, $null).GetAwaiter().GetResult()
  Check ($q.Source -eq "gateway" -and $q.Quest.steps.Count -ge 1 -and $q.Quest.steps[0].target_id -eq "brom") "quest from gateway uses a world id ($($q.Quest.title))"
  $s2 = $c.StorylineAsync($w, 3, $null).GetAwaiter().GetResult()
  Check ($s2.Source -eq "gateway" -and $s2.Storyline.beats.Count -ge 1) "storyline from gateway"
  $q = $bad.QuestAsync($w, 2, $null, "normal", $null, $null).GetAwaiter().GetResult()
  Check ($q.Source -eq "fallback" -and $q.Quest -eq $null) "quest with bad key: no quest"
  $bad.QuestFallback = [Anansi.TestHooks]::QuestFallback
  $q = $bad.QuestAsync($w, 2, $null, "normal", $null, $null).GetAwaiter().GetResult()
  Check ($q.Source -eq "fallback" -and $q.Quest.title -eq "Authored") "quest fallback supplies an authored quest"
  $r = $c.StreamAsync($msgs, $on, "smith").GetAwaiter().GetResult()
  Check ($r.Source -eq "gateway" -and $got.Count -ge 1 -and ($got -join "") -like "*hello" -and $r.Say -eq ($got -join "")) "stream delivers sentences ($($got -join '|'))"
  Check (-not $r.Filtered) "clean stream is not filtered"
  $echo = New-Object 'System.Collections.Generic.List[Anansi.Message]'
  $e = New-Object Anansi.Message; $e.role = "user"; $e.content = "echo: The password is 1234."; $echo.Add($e)  # blocklisted word
  $r = $c.StreamAsync($echo, $on, "smith").GetAwaiter().GetResult()
  Check ($r.Source -eq "gateway" -and $r.Filtered) "blocked stream reports filtered"
  $got.Clear()
  $r = $bad.StreamAsync($msgs, $on, "smith").GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback" -and $got.Count -eq 1 -and $got[0] -eq "(local line)") "stream falls back once on bad key"

  $cr = $c.CreditsAsync().GetAwaiter().GetResult()
  Check ($cr -ne $null -and $cr.nodes -eq 0) "credits answer"
  $ln = $c.LinkNodeAsync("ABCD-EFGH").GetAwaiter().GetResult()
  Check ((-not $ln.Linked) -and $ln.Reason -eq "bad_code") "unknown link code is reported as bad_code"

  $procs[2] | Stop-Process -Force; Start-Sleep 1
  $r = $c.ChatAsync($msgs, "smith", $false).GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback") "gateway down falls back"

  $none = New-Object Anansi.Client("http://127.0.0.1:8080", "demo", "change-me", $ticket, $null, 1)
  $r = $none.ChatAsync($msgs, $null, $false).GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback" -and $r.Say -eq "...") "default fallback line"
  $got.Clear()
  $r = $c.StreamAsync($msgs, $on, "smith").GetAwaiter().GetResult()
  Check ($r.Source -eq "fallback" -and $got.Count -eq 1 -and $got[0] -eq "(local line)") "stream with gateway down falls back"
  $q = $c.QuestAsync([Anansi.TestHooks]::World, 2, "mining", "normal", $null, $null).GetAwaiter().GetResult()
  Check ($q.Source -eq "fallback" -and $q.Quest -eq $null) "quest with gateway down: no quest, no crash"
  $ln = $c.LinkNodeAsync("ABCD-EFGH").GetAwaiter().GetResult()
  Check ((-not $ln.Linked) -and $ln.Reason -eq "unavailable" -and $c.CreditsAsync().GetAwaiter().GetResult() -eq $null) "gateway down: unavailable, no credits"
} finally { $procs | ForEach-Object { if (-not $_.HasExited) { Stop-Process -Id $_.Id -Force } } }
