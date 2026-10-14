"""
手动安装 pandas 的脚本
"""
import urllib.request
import zipfile
import os
import sys
import tempfile
import shutil

def download_and_install(package_name, target_dir):
    """下载并安装指定的包"""
    print(f"正在获取 {package_name} 的下载地址...")

    # 获取下载链接
    pkg_url = f"https://pypi.org/simple/{package_name}/"
    try:
        req = urllib.request.Request(pkg_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8')
    except Exception as e:
        print(f"获取 {package_name} 失败: {e}")
        return False

    # 找最新的 wheel 文件（对于 Windows CPython 3.13）
    import re
    python_tag = "cp313"
    platform_tag = "win_amd64"
    pattern = rf'href="([^"]*{package_name}[^"]*\.whl[^"]*)"'
    matches = re.findall(pattern, html)

    wheel_url = None
    for match in matches:
        if python_tag in match and platform_tag in match:
            wheel_url = match
            break

    if not wheel_url:
        # 尝试找纯 Python 包
        for match in matches:
            if python_tag in match and 'none-any' in match:
                wheel_url = match
                break

    if not wheel_url:
        print(f"未找到 {package_name} 的兼容 wheel 文件")
        return False

    print(f"正在下载 {wheel_url}...")

    # 下载文件
    temp_dir = tempfile.mkdtemp()
    wheel_file = os.path.join(temp_dir, f"{package_name}.whl")

    try:
        req = urllib.request.Request(wheel_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(wheel_file, 'wb') as f:
                shutil.copyfileobj(resp, f)

        print(f"正在解压 {wheel_file} 到 {target_dir}...")

        # 解压 wheel 文件（wheel 本质上是一个 zip 文件）
        with zipfile.ZipFile(wheel_file, 'r') as zip_ref:
            zip_ref.extractall(target_dir)

        print(f"{package_name} 安装成功！")
        return True

    except Exception as e:
        print(f"安装 {package_name} 失败: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    target_dir = r"f:\编程\源码包\更新软件\_lib"

    packages = ["numpy", "pandas", "python_dateutil", "tzdata", "six", "pytz", "openpyxl", "et_xmlfile"]

    for pkg in packages:
        download_and_install(pkg, target_dir)
