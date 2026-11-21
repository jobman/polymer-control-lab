@echo off
setlocal
chcp 65001 >nul
title Полимерная лаборатория
pushd "%~dp0"
if errorlevel 1 exit /b 1

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "EXIT_CODE=1"
if exist "%VENV_PYTHON%" goto check_environment

echo Создание виртуального окружения .venv...
python -c "import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] < (3, 14)))" >nul 2>&1
if errorlevel 1 goto use_launcher
python -m venv "%~dp0.venv"
if errorlevel 1 goto environment_error
goto check_environment

:use_launcher
for %%V in (3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] < (3, 14)))" >nul 2>&1
    if not errorlevel 1 (
        py -%%V -m venv "%~dp0.venv"
        if errorlevel 1 goto environment_error
        goto check_environment
    )
)
goto python_error

:check_environment
"%VENV_PYTHON%" -c "import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] < (3, 14)))" >nul 2>&1
if errorlevel 1 goto environment_error
echo Проверка и установка зависимостей...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto dependencies_error

echo Запуск симуляции...
"%VENV_PYTHON%" "%~dp0main.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto application_error
goto finish

:python_error
echo Не найден Python 3.10-3.13. Установите подходящую версию с python.org и повторите запуск.
goto failure

:environment_error
echo Не удалось создать или запустить .venv с Python 3.10-3.13.
echo Проверьте установку Python и права доступа. Если .venv создана другой версией Python,
echo переименуйте её папку и повторите запуск, чтобы создать новое окружение.
goto failure

:dependencies_error
echo Не удалось установить зависимости. Проверьте сообщение pip выше и подключение к интернету.
goto failure

:application_error
echo Программа завершилась с ошибкой %EXIT_CODE%. Подробности приведены выше.

:failure
echo.
pause

:finish
popd
exit /b %EXIT_CODE%
