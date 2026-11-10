@echo off
chcp 65001 >nul
title Update iPod (artist photos, database, art cache)

rem ============================================================
rem  Change these if your iPod uses a different drive or folder
set "IPOD=G:"
set "MUSIC=G:\Music"
rem ============================================================

rem Run from the folder this file is in, so it finds the .py files
cd /d "%~dp0"
set "TOOLS=%IPOD%\.rockbox\tools"
set "PYTHONIOENCODING=utf-8"

for %%F in (art_fetch.py artist_fallback.py) do (
    if not exist "%%F" (
        echo Can't find %%F.
        echo Put this file in the same folder as art_fetch.py and artist_fallback.py.
        echo.
        pause
        exit /b 1
    )
)

if not exist "%MUSIC%\" (
    echo Can't find %MUSIC%
    echo Is the iPod plugged in and showing in File Explorer?
    echo If it's on a different drive or folder, right-click this file,
    echo choose Edit, and change the IPOD and MUSIC lines near the top.
    echo.
    pause
    exit /b 1
)

rem Album covers standing in for artist photos are taken away first, so
rem those artists are searched for again every run. Any still not found
rem get their album cover back in step 2.
python artist_fallback.py "%MUSIC%" --remove
echo.

echo ============================================================
echo  Step 1 of 4: fetching artist photos online
echo ============================================================
echo Artists that already have a real photo are skipped.
echo Artists with no photo found are skipped automatically.
echo Press Ctrl+C at any time to stop.
echo.

python art_fetch.py artist "%MUSIC%" --retry-not-found

echo.
echo ============================================================
echo  Step 2 of 4: using an album cover where no photo was found
echo ============================================================
python artist_fallback.py "%MUSIC%"

echo.
echo ============================================================
echo  Step 3 of 4: updating the music database
echo ============================================================
"%TOOLS%\database_pb.exe" %IPOD%\
if errorlevel 1 (set "DBRESULT=FAILED - see messages above") else (set "DBRESULT=done")

echo.
echo ============================================================
echo  Step 4 of 4: updating the art cache
echo ============================================================
"%TOOLS%\artcache_pb.exe" %IPOD%\
if errorlevel 1 (set "ARTRESULT=FAILED - see messages above") else (set "ARTRESULT=done")

echo.
echo ------------------------------------------------------------
echo  Finished.
echo  Database update   : %DBRESULT%
echo  Art cache update  : %ARTRESULT%
echo.
echo  Lists saved next to this file:
echo    "Artists using album cover.txt"
echo    "Artists without photos.txt"
echo.
echo  Now eject the iPod. It restarts itself to load the changes.
echo  If a step failed or was skipped, run it on the iPod instead:
echo  Settings ^> General Settings ^> System ^> Library Maintenance
echo ------------------------------------------------------------
echo.
pause
