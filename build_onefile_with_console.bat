@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ====================================================
echo MMDVM 更新程序 — 生成单文件 EXE（带终端）
echo ====================================================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python，请先安装 Python 3.7+
    pause
    exit /b 1
)

REM 安装 PyInstaller（如未安装）
npython -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo 错误: PyInstaller 安装失败
        pause
        exit /b 1
    )
)

REM 安装 requirements（如果存在）
if exist requirements.txt (
    echo 正在安装 requirements.txt 中的依赖...
    pip install -r requirements.txt
) else (
    echo 未找到 requirements.txt，跳过依赖安装（若缺少包请手动安装）
)

REM 准备 PyInstaller 参数
set "ICON_OPTION="
if exist icon.ico (
    set "ICON_OPTION=--icon=icon.ico"
) else (
    echo 警告: 未找到 icon.ico，生成的 exe 将不带自定义图标
)

REM 自动收集常见的辅助目录作为 --add-data 参数（格式: "src;dest"，Windows 使用分号）
set "ADD_DATA="
for %%d in (up CSV "数字联系人文件" plugins resources docs) do (
    if exist "%%~d" (
        if defined ADD_DATA (
            set "ADD_DATA=!ADD_DATA! --add-data "%%~d;%%~d""
        ) else (
            set "ADD_DATA=--add-data "%%~d;%%~d""
        )
    )
)

echo 检测到的附加数据: %ADD_DATA%

echo 开始使用 PyInstaller 生成单文件 exe（带终端），此过程可能需要几分钟...
python -m PyInstaller --noconfirm --clean --onefile %ICON_OPTION% %ADD_DATA% mmdvm_updater.py

if errorlevel 1 (
    echo.
    echo 错误: 打包失败
    pause
    exit /b 1
)

echo.
echo ====================================================
echo 打包完成（带终端）
echo 生成文件位于 dist\
echo ====================================================
pause
