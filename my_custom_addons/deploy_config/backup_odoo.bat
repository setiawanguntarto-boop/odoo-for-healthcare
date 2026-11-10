@echo off
REM ==============================================================================
REM KLINIK ADERA ERP - AUTOMATED DAILY BACKUP SCRIPT (WINDOWS BAT)
REM Performs PostgreSQL database dump, archives filestore, and rotates backups (30 days)
REM ==============================================================================

setlocal enabledelayedexpansion

set PG_BIN="C:\Program Files\PostgreSQL\16\bin"
set PG_HOST=localhost
set PG_PORT=5432
set PG_USER=odoo
set PGPASSWORD=12345
set DB_NAME=adera_prod

set BACKUP_DIR=C:\odoo\backups
set FILESTORE_DIR=C:\Users\ASUS\AppData\Local\Odoo\filestore\%DB_NAME%

for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set MYDATE=%%c-%%a-%%b)
for /f "tokens=1-2 delims=: " %%a in ('time /t') do (set MYTIME=%%a%%b)
set TIMESTAMP=%MYDATE%_%MYTIME%
set CURRENT_BACKUP=%BACKUP_DIR%\backup_%DB_NAME%_%TIMESTAMP%

if not exist %BACKUP_DIR% mkdir %BACKUP_DIR%
if not exist %CURRENT_BACKUP% mkdir %CURRENT_BACKUP%

echo [*] Starting PostgreSQL Backup for %DB_NAME% at %TIMESTAMP%...
%PG_BIN%\pg_dump.exe -h %PG_HOST% -p %PG_PORT% -U %PG_USER% -F c -b -v -f "%CURRENT_BACKUP%\%DB_NAME%.dump" %DB_NAME%

echo [*] Backing up Odoo Filestore...
if exist "%FILESTORE_DIR%" (
    tar -czf "%CURRENT_BACKUP%\filestore.tar.gz" -C "%FILESTORE_DIR%" .
)

echo [*] Compressing full backup bundle...
tar -czf "%BACKUP_DIR%\full_backup_%DB_NAME%_%TIMESTAMP%.tar.gz" -C "%CURRENT_BACKUP%" .
rmdir /s /q "%CURRENT_BACKUP%"

echo [*] Purging backups older than 30 days...
forfiles /p "%BACKUP_DIR%" /m *.tar.gz /d -30 /c "cmd /c del @path"

echo [SUCCESS] Backup completed: %BACKUP_DIR%\full_backup_%DB_NAME%_%TIMESTAMP%.tar.gz
endlocal

