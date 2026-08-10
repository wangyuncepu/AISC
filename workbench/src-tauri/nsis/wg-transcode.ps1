# AISC installer helper: run winget and transcode its UTF-8 stdout to the
# system ANSI codepage, so the NSIS install log (which nsExec decodes as ANSI)
# shows readable progress instead of mojibake. Streams chunk-by-chunk so
# progress is live. Exits with winget's exit code.
#
# Invoked by installer.nsi Section Docker:
#   powershell -NoProfile -ExecutionPolicy Bypass -File "<path>" <winget args...>
param()
$ansi = [System.Text.Encoding]::GetEncoding([System.Globalization.CultureInfo]::CurrentCulture.TextInfo.ANSICodePage)
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'winget'
$psi.Arguments = [string]::Join(' ', $args)
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.CreateNoWindow = $true
$p = [System.Diagnostics.Process]::Start($psi)
$out = [Console]::OpenStandardOutput()
$buf = New-Object byte[] 8192
while (($n = $p.StandardOutput.BaseStream.Read($buf, 0, $buf.Length)) -gt 0) {
  $txt = [System.Text.Encoding]::UTF8.GetString($buf, 0, $n)
  $ab = $ansi.GetBytes($txt)
  $out.Write($ab, 0, $ab.Length)
  $out.Flush()
}
$p.WaitForExit()
$out.Close()
exit $p.ExitCode
