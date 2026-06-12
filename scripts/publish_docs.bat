@echo off
REM Pubblica la documentazione mkdocs su cryptoquantix.github.io/docs
REM Prerequisito: clone di cryptoquantix.github.io accanto a questo repo.
REM Uso: scripts\publish_docs.bat   (poi git push nel repo Pages)
setlocal
cd /d "%~dp0\.."

set PAGES_REPO=..\cryptoquantix.github.io
if not exist "%PAGES_REPO%\.git" (
    echo [FAIL] repo Pages non trovato in %PAGES_REPO%
    exit /b 1
)

echo [1/3] Build mkdocs...
python -m mkdocs build -d "%TEMP%\cqx_docs_build" || exit /b 1

echo [2/3] Copia in %PAGES_REPO%\docs ...
if exist "%PAGES_REPO%\docs" rmdir /s /q "%PAGES_REPO%\docs"
xcopy /e /i /q "%TEMP%\cqx_docs_build" "%PAGES_REPO%\docs\" >nul || exit /b 1
rmdir /s /q "%TEMP%\cqx_docs_build"

echo [3/3] Commit nel repo Pages...
cd /d "%PAGES_REPO%"
git add docs
git diff --cached --quiet && echo [OK] nessuna modifica ai docs && exit /b 0
git commit -m "docs: aggiornamento documentazione CryptoQuantix"
echo [OK] Commit creato. Per pubblicare: cd %PAGES_REPO% ^&^& git push
endlocal
