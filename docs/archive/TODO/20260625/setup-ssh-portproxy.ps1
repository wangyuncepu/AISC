# Self-elevate to admin
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoExit","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`""
    exit
}

$listenAddr  = "10.147.20.73"
$listenPort  = 2222
$connectAddr = "172.21.90.157"
$connectPort = 22

Write-Host "=== removing old rule ==="
netsh interface portproxy delete v4tov4 listenaddress=$listenAddr listenport=$listenPort

Write-Host "`n=== adding new rule ==="
netsh interface portproxy add v4tov4 listenaddress=$listenAddr listenport=$listenPort connectaddress=$connectAddr connectport=$connectPort

Write-Host "`n=== current portproxy rules ==="
netsh interface portproxy show v4tov4

Read-Host "`nPress Enter to exit"
