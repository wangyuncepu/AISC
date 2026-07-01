@echo off
title SSH Server Setup Script

:: Check admin privilege
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please right-click and run as Administrator
    pause
    exit /b 1
)

echo ======================================
echo       SSH Server Setup Script
echo ======================================
echo.

:: Step 1: Install OpenSSH Server
echo [1/5] Installing OpenSSH Server...
powershell -Command "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0"
if %errorlevel% neq 0 (
    echo [FAILED] OpenSSH Server installation failed
    pause
    exit /b 1
)
echo [OK] OpenSSH Server installed
echo.

:: Step 2: Start service and set auto start
echo [2/5] Configuring SSH service...
sc config sshd start= auto >nul
net start sshd >nul 2>&1
sc query sshd | find "RUNNING" >nul
if %errorlevel% equ 0 (
    echo [OK] SSH service is running, auto-start enabled
) else (
    echo [FAILED] SSH service failed to start
    pause
    exit /b 1
)
echo.

:: Step 3: Add firewall rule
echo [3/5] Configuring firewall rule...
netsh advfirewall firewall show rule name="OpenSSH SSH Server" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Firewall rule already exists
) else (
    netsh advfirewall firewall add rule name="OpenSSH SSH Server" dir=in action=allow protocol=TCP localport=22 >nul
    echo [OK] Port 22 allowed in firewall
)
echo.

:: Step 4: Setup admin authorized_keys with correct permissions
echo [4/5] Configuring admin authorized keys file...
set "ADMIN_KEY=C:\ProgramData\ssh\administrators_authorized_keys"
if not exist "C:\ProgramData\ssh" mkdir "C:\ProgramData\ssh"
if not exist "%ADMIN_KEY%" type nul > "%ADMIN_KEY%"

:: Fix permissions required by OpenSSH
icacls "%ADMIN_KEY%" /inheritance:r >nul
icacls "%ADMIN_KEY%" /grant:r "SYSTEM:(F)" "Administrators:(F)" >nul
echo [OK] Admin key file permissions set correctly
echo.

:: Step 5: Show local IP address
echo [5/5] Local LAN IPv4 addresses:
ipconfig | findstr /i "IPv4"
echo.
echo ======================================
echo Setup Complete!
echo Paste your client public key into: %ADMIN_KEY%
echo Connect command: ssh username@your_ip
echo ======================================
echo.
pause