Set WshShell = CreateObject("WScript.Shell")

' Stop all AniStory AI processes (ports 8088-8097 listeners, uvicorn reloader parents, and multiprocessing child workers)
' Walks both UP (to kill uvicorn reloader parents first so they cannot respawn workers) and DOWN (to kill child workers).
stopCmd = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command """ & _
    "for ($round = 0; $round -lt 3; $round++) { " & _
    "  $pids = New-Object System.Collections.Generic.HashSet[int]; " & _
    "  $allProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue); " & _
    "  $procById = @{}; foreach ($p in $allProcs) { $procById[[int]$p.ProcessId] = $p }; " & _
    "  Get-NetTCPConnection -LocalPort (8088..8097) -State Listen -ErrorAction SilentlyContinue | ForEach-Object { " & _
    "    $own = [int]$_.OwningProcess; " & _
    "    if ($own -gt 4) { [void]$pids.Add($own) } " & _
    "  }; " & _
    "  foreach ($p in $allProcs) { " & _
    "    if ($p.Name -like 'python*' -and $p.CommandLine -match '(?<![a-zA-Z0-9_])run\.py\b|backend\.app:app' -and $p.CommandLine -notmatch 'flowkit[\\/]run_background\.py') { " & _
    "      [void]$pids.Add([int]$p.ProcessId) " & _
    "    } " & _
    "  }; " & _
    "  if ($pids.Count -eq 0) { break }; " & _
    "  do { " & _
    "    $added = $false; " & _
    "    foreach ($id in @($pids)) { " & _
    "      $cur = $procById[$id]; " & _
    "      if ($cur) { " & _
    "        $ppid = [int]$cur.ParentProcessId; " & _
    "        if ($ppid -gt 4 -and -not $pids.Contains($ppid) -and $procById.ContainsKey($ppid)) { " & _
    "          $parent = $procById[$ppid]; " & _
    "          if ($parent.Name -like 'python*' -or ($parent.Name -eq 'cmd.exe' -and $parent.CommandLine -match 'run\.py')) { " & _
    "            [void]$pids.Add($ppid); $added = $true " & _
    "          } " & _
    "        }; " & _
    "        if ($cur.CommandLine -match 'parent_pid=(\d+)') { " & _
    "          $mpid = [int]$Matches[1]; " & _
    "          if ($mpid -gt 4 -and -not $pids.Contains($mpid) -and $procById.ContainsKey($mpid)) { " & _
    "            [void]$pids.Add($mpid); $added = $true " & _
    "          } " & _
    "        } " & _
    "      } " & _
    "    }; " & _
    "    foreach ($p in $allProcs) { " & _
    "      $pidInt = [int]$p.ProcessId; " & _
    "      if (-not $pids.Contains($pidInt) -and $p.Name -like 'python*' -and $p.CommandLine -notmatch 'flowkit[\\/]run_background\.py') { " & _
    "        $isChild = $pids.Contains([int]$p.ParentProcessId); " & _
    "        if (-not $isChild -and $p.CommandLine -match 'parent_pid=(\d+)') { $isChild = $pids.Contains([int]$Matches[1]) }; " & _
    "        if ($isChild) { [void]$pids.Add($pidInt); $added = $true } " & _
    "      } " & _
    "    } " & _
    "  } while ($added); " & _
    "  foreach ($targetPid in @($pids)) { " & _
    "    & taskkill /F /T /PID $targetPid 2>$null | Out-Null; " & _
    "    Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue " & _
    "  }; " & _
    "  Start-Sleep -Milliseconds 350 " & _
    "}" & _
    """"

WshShell.Run stopCmd, 0, True

' Verify ports 8088-8097 are closed
verifyCmd = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command """ & _
    "if (Get-NetTCPConnection -LocalPort (8088..8097) -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 4 }) { exit 1 } else { exit 0 }" & _
    """"
rc = WshShell.Run(verifyCmd, 0, True)
If rc = 0 Then
    WshShell.Popup "AniStory AI server has been stopped.", 2, "AniStory AI - Stopped", 64
Else
    WshShell.Popup "Warning: A process is still listening on ports 8088-8097." & vbCrLf & _
        "Try running stop_app.vbs as Administrator.", 10, "AniStory AI - Stop Warning", 48
End If
