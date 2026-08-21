@echo off
REM ============================================================
REM  FilmCam - tools launcher / status board
REM  Project root: D:\Projects\filmcam
REM
REM  Double-click to run the .fcr reference tools without typing
REM  paths. (filmcam.bat opens the AI session; this is the tools
REM  menu.)
REM ============================================================

setlocal
set "ROOT=%~dp0"
set "FCRREF=%ROOT%tools\fcr-reference"

title FilmCam - tools launcher
cd /d "%ROOT%"

:menu
cls
echo ============================================================
echo   FilmCam  -  .fcr reference tools
echo   Root: %ROOT%
echo ============================================================
echo.
echo   Stage W (reference implementation): DONE
echo   Variable bit depth (10/12/14-bit):  DONE
echo   Embedded audio (container v2):      DONE
echo.
echo   Next gate: Stage M0 needs a Mac + iPhone 15.
echo ------------------------------------------------------------
echo   What do you want to do?
echo.
echo     [1] Show git status + recent commits
echo     [2] Run the test suite
echo     [3] Convert DNG sequence  -^>  .fcr
echo     [4] Inspect / verify an .fcr file
echo     [5] Extract one frame to raw16
echo     [6] Measure compression ratio on DNGs
echo     [7] Open the design spec
echo     [8] Open a shell in the project folder
echo     [0] Exit
echo.
set /p choice="  Choice: "

if "%choice%"=="1" goto gitstatus
if "%choice%"=="2" goto tests
if "%choice%"=="3" goto convert
if "%choice%"=="4" goto inspect
if "%choice%"=="5" goto extract
if "%choice%"=="6" goto analyze
if "%choice%"=="7" goto spec
if "%choice%"=="8" goto shell
if "%choice%"=="0" goto end
goto menu

:gitstatus
echo.
echo --- Branch + recent commits ---
git -C "%ROOT%" log --oneline -15
echo.
echo --- Working tree ---
git -C "%ROOT%" status --short
echo.
pause
goto menu

:tests
echo.
echo Running test suite in %FCRREF% ...
echo.
cd /d "%FCRREF%"
python -m pytest tests/ -q
cd /d "%ROOT%"
echo.
pause
goto menu

:convert
echo.
echo Convert a folder of DNGs into one .fcr clip (video only).
set /p dngfolder="  Full path to DNG folder: "
set /p outfcr="  Output .fcr path (e.g. D:\clip.fcr): "
set /p nframes="  Max frames (blank = all): "
cd /d "%FCRREF%"
if "%nframes%"=="" (
  python -m fcrref.convert --input "%dngfolder%\*.dng" --out "%outfcr%"
) else (
  python -m fcrref.convert --input "%dngfolder%\*.dng" --out "%outfcr%" --limit %nframes%
)
cd /d "%ROOT%"
echo.
pause
goto menu

:inspect
echo.
echo Inspect / verify an .fcr file (fast structural check, no full decode).
set /p fcrfile="  Full path to .fcr file: "
cd /d "%FCRREF%"
python -m fcrref.inspect "%fcrfile%" --check
cd /d "%ROOT%"
echo.
pause
goto menu

:extract
echo.
echo Decode one frame and write it out as raw16.
set /p fcrfile="  Full path to .fcr file: "
set /p frnum="  Frame index (0 = first): "
set /p outraw="  Output raw16 path (e.g. D:\frame0.raw16): "
cd /d "%FCRREF%"
python -m fcrref.inspect "%fcrfile%" --frame %frnum% --out "%outraw%"
cd /d "%ROOT%"
echo.
pause
goto menu

:analyze
echo.
echo Measure the lossless compression ratio on real Bayer DNGs.
set /p dngglob="  DNG folder path: "
cd /d "%FCRREF%"
python -m fcrref.analyze --input "%dngglob%\*.dng"
cd /d "%ROOT%"
echo.
pause
goto menu

:spec
start "" "%ROOT%docs\superpowers\specs\2026-08-19-filmcam-capture-design.md"
goto menu

:shell
echo.
echo Opening a shell in %ROOT% ...
echo (type 'exit' to return to the launcher)
echo.
cmd /k "cd /d %ROOT%"
goto menu

:end
endlocal
