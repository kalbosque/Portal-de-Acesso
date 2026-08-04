Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win32API {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
}
"@ -ErrorAction SilentlyContinue

$hwnd = [Win32API]::GetForegroundWindow()
$sb = New-Object System.Text.StringBuilder 256
if ([Win32API]::GetWindowText($hwnd, $sb, 256) -gt 0) {
    Write-Host "Title: $($sb.ToString())"
} else {
    Write-Host "NO_TITLE"
}
