@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_REQUIRE_VIRTUALENV=1"
set "VENV_PYTHON=.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating the OAS virtual environment...
    py -3.11-64 -m venv ".venv" || goto venv_error
)

"%VENV_PYTHON%" -c "import struct, sys; sys.exit(not (sys.prefix != sys.base_prefix and sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8))" || goto venv_error

echo Checking OAS dependencies in .venv...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --quiet -r "requirements.txt" || goto install_error

"%VENV_PYTHON%" -u "server.py" %*
set "OAS_EXIT=%ERRORLEVEL%"
popd
exit /b %OAS_EXIT%

:venv_error
echo Failed to use .venv. OAS requires 64-bit Python 3.11 and the Windows Python Launcher. 1>&2
popd
exit /b 1

:install_error
echo Failed to install OAS dependencies in .venv. See the pip error above. 1>&2
popd
exit /b 1
