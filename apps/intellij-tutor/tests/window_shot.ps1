# Capture one process's largest visible window by its own content (PrintWindow), never the rest of the screen.
#   powershell -ExecutionPolicy Bypass -File apps/intellij-tutor/tests/window_shot.ps1 -ProcessId <pid> -Out shot.png
param([int]$ProcessId, [string]$Out, [switch]$Restore, [int]$Width = 1280, [int]$Height = 800)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class WyspWin {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr p);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  public static IntPtr Largest(uint target) {
    IntPtr best = IntPtr.Zero; long area = 0;
    EnumWindows((h, p) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == target && IsWindowVisible(h)) {
        RECT r; GetWindowRect(h, out r);
        long a = (long)(r.Right - r.Left) * (r.Bottom - r.Top);
        if (a > area) { area = a; best = h; }
      }
      return true;
    }, IntPtr.Zero);
    return best;
  }
}
"@
$h = [WyspWin]::Largest([uint32]$ProcessId)
if ($h -eq [IntPtr]::Zero) { Write-Error "process $ProcessId has no visible window"; exit 1 }
# -Restore: un-minimise without activating and keep it behind other windows (PrintWindow still sees it).
if ($Restore) {
  [void][WyspWin]::ShowWindow($h, 4)  # SW_SHOWNOACTIVATE
  [void][WyspWin]::SetWindowPos($h, [IntPtr]1, 0, 0, $Width, $Height, 0x0010)  # HWND_BOTTOM, SWP_NOACTIVATE
  Start-Sleep -Milliseconds 1500
}
$r = New-Object WyspWin+RECT
[void][WyspWin]::GetWindowRect($h, [ref]$r)
$w = $r.Right - $r.Left; $hgt = $r.Bottom - $r.Top
$bmp = New-Object Drawing.Bitmap $w, $hgt
$g = [Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
[void][WyspWin]::PrintWindow($h, $dc, 2)  # PW_RENDERFULLCONTENT
$g.ReleaseHdc($dc)
$bmp.Save($Out)
"$w x $hgt -> $Out"
