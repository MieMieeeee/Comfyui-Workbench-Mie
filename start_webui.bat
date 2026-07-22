@echo off
setlocal enableextensions enabledelayedexpansion

REM ============================================================
REM  ComfyUI Web Workflow 启动脚本（与 ComfyUI 解耦）
REM  - 先清理占用 8199 端口的旧进程
REM  - 首次运行自动 pip install -r requirements.txt
REM  - 启动 Flask WebUI (8199) 并打开浏览器
REM  - ComfyUI 地址在 WebUI 的"设置" tab 里配置（默认 127.0.0.1:8188）
REM  - 完全本地自包含：浏览器用 127.0.0.1 访问（不用 localhost，
REM    避免 Windows IPv6 优先解析 ::1 但服务只监听 IPv4 导致回退超时）
REM ============================================================

cd /d "%~dp0"

set "WEBUI_PORT=8199"
REM 用 127.0.0.1 打开浏览器。localhost 会先解析到 IPv6 ::1，但 Flask 只监听
REM IPv4 (0.0.0.0)，浏览器要等 ~2 秒超时再回退 127.0.0.1。
set "DISPLAY_HOST=127.0.0.1"

REM 离线自包含：切断 huggingface_hub 的外网探测（版本检查）。
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"

echo ============================================================
echo   ComfyUI Web Workflow 启动器
echo ============================================================
echo.

REM --- 0. 清理占用 WEBUI_PORT 的旧进程（避免端口冲突）---
echo [清理] 检查端口 %WEBUI_PORT% 是否被占用...
set "KILLED=0"
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr ":%WEBUI_PORT% " ^| findstr "LISTENING"') do (
    echo       发现占用进程 PID=%%P，正在结束...
    taskkill /F /PID %%P >nul 2>&1
    set "KILLED=1"
)
if "!KILLED!"=="0" (
    echo       端口 %WEBUI_PORT% 空闲。
) else (
    echo       已清理旧进程，等待 1 秒释放端口...
    ping -n 2 127.0.0.1 >nul
)
echo.

REM --- 1. 找 python ---
where py >nul 2>&1 && set "PYCMD=py" || set "PYCMD=python"
%PYCMD% --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 找不到 Python。请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
)

REM --- 2. 检查依赖（首次自动装）---
echo [1/3] 检查依赖...
%PYCMD% -c "import flask, requests" >nul 2>&1
if errorlevel 1 (
    echo       缺少依赖，正在安装 requirements.txt ...
    %PYCMD% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败。请手动运行: %PYCMD% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo       依赖安装完成。
) else (
    echo       依赖已就绪。
)

REM --- 3. 预检工作流模板 ---
echo.
echo [2/3] 预检工作流模板...
%PYCMD% -c "import sys; sys.path.insert(0,'.'); from app import config; [print('  ', w['name'], 'OK' if config.workflow_path(w['name']).exists() else 'MISSING') for w in config.list_workflows()]" 2>nul

REM --- 4. 启动 Flask WebUI ---
echo.
echo [3/3] 启动 Flask WebUI...
echo       地址: http://%DISPLAY_HOST%:%WEBUI_PORT%
echo       ComfyUI 地址在 WebUI 的"设置" tab 配置（默认 127.0.0.1:8188）
echo       按 Ctrl+C 停止。
echo ============================================================
echo.

REM 启动后延迟打开浏览器
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://%DISPLAY_HOST%:%WEBUI_PORT%"

REM [migrate-to-flask 2026-07-21] Flask 是唯一前端 (Gradio 已下线).
set "FLASK_PORT=%WEBUI_PORT%"
set "FLASK_HOST=0.0.0.0"
%PYCMD% -m app.flask_app
if errorlevel 1 (
    echo.
    echo [错误] Flask 启动失败。查看上方 preflight 输出或 app\data\gradio_run.log。
    pause
)

endlocal
