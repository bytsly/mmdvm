# -*- coding: utf-8 -*-
"""
MMDVM 更新程序 —— GitHub Release 发布后验证脚本

用法:
    python verify_release.py            # 验证最新 Release
    python verify_release.py v2.1       # 验证指定 tag

检查项（与 mmdvm_updater.py 内自动更新逻辑完全一致）:
    1. 仓库公开可访问
    2. releases/latest 可取到，tag 合法且 >= 本地 VERSION
    3. 资产中存在 mmdvm_updater.exe
    4. GitHub 直链 + 两个 ghproxy 镜像均可连通
    5. 远端 exe 大小与本地 output/mmdvm_updater.exe 一致（可选）

全部通过退出码为 0，任一失败为 1。
"""
import os
import re
import sys

import requests

# ---- 与主程序保持一致的配置 ----
OWNER = "bytsly"
REPO = "mmdvm"
ASSET_NAME = "mmdvm_updater.exe"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
MIRROR_PREFIXES = ["", "https://ghproxy.net/", "https://mirror.ghproxy.com/"]
HEADERS = {"User-Agent": "MMDVMUpdater/2.0", "Accept": "application/vnd.github+json"}
# 如遇未认证 API 限流(60次/小时)，可设置环境变量 GITHUB_TOKEN 提升到 5000 次/小时:
#   PowerShell: $env:GITHUB_TOKEN="ghp_xxx"; python verify_release.py
_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
if _token:
    HEADERS["Authorization"] = f"Bearer {_token}"
TIMEOUT = 20

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_EXE = os.path.join(HERE, "output", "mmdvm_updater.exe")

passed, failed, skipped = [], [], []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))


def skip(name, detail=""):
    skipped.append(name)
    print(f"[SKIP] {name}" + (f"  -- {detail}" if detail else ""))


def version_tuple(v):
    parts = [int(p) for p in re.findall(r"\d+", str(v))[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def read_local_version():
    """从 mmdvm_updater.py 读取 VERSION 常量"""
    src = os.path.join(HERE, "mmdvm_updater.py")
    try:
        with open(src, "r", encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
            return m.group(1) if m else "2.0"
    except OSError:
        return "2.0"


def probe_download(url):
    """只取前 64KB 验证可连通性，避免下载整个 100MB 文件；返回(ok, 状态码, 文件总大小)"""
    try:
        r = requests.get(url, headers={"Range": "bytes=0-65535"},
                         stream=True, timeout=TIMEOUT)
        if r.status_code not in (200, 206):
            return False, r.status_code, 0
        total = 0
        cr = r.headers.get("content-range")  # 206: bytes 0-65535/100241912
        if cr and "/" in cr:
            total = int(cr.rsplit("/", 1)[1])
        if not total and r.status_code == 200:
            total = int(r.headers.get("content-length", 0))  # 200: 整个文件长度
        r.close()
        return True, r.status_code, total
    except requests.exceptions.RequestException as e:
        return False, str(e).splitlines()[0][:80], 0


def is_rate_limited(resp):
    return (resp.status_code == 403
            and resp.headers.get("X-RateLimit-Remaining") == "0")


def probe_channels(dl_url, remote_size=0):
    """依次验证 GitHub 直链与镜像（顺序与主程序 UPDATE_MIRROR_PREFIXES 一致）"""
    for prefix in MIRROR_PREFIXES:
        url = prefix + dl_url if prefix else dl_url
        host = url.split("/")[2]
        ok, code, got = probe_download(url)
        detail = f"HTTP {code}"
        if ok and got:
            detail += f", 文件 {got/1048576:.1f} MB"
        check(f"下载通道 {host}", ok, detail)
        if ok and got and not remote_size:
            remote_size = got
    if remote_size and os.path.exists(LOCAL_EXE):
        check("远端 exe 与本地 output 产物大小一致",
              os.path.getsize(LOCAL_EXE) == remote_size,
              f"本地 {os.path.getsize(LOCAL_EXE)/1048576:.1f} MB / 远端 {remote_size/1048576:.1f} MB")


def main():
    expect_tag = sys.argv[1].lstrip("vV") if len(sys.argv) > 1 else None
    local_ver = read_local_version()

    print("=" * 64)
    print("MMDVM GitHub Release 发布验证")
    print("=" * 64)

    # 1. 仓库公开性
    try:
        repo = requests.get(f"https://api.github.com/repos/{OWNER}/{REPO}",
                            headers=HEADERS, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        check("仓库可访问且为公开", False, str(e)[:80])
        return finish()

    if is_rate_limited(repo):
        return rate_limited_fallback(expect_tag or local_ver)
    if repo.status_code != 200:
        check("仓库可访问且为公开", False, f"HTTP {repo.status_code}")
        return finish()
    check("仓库可访问且为公开", not repo.json().get("private", True))

    # 2. 最新 Release
    try:
        r = requests.get(API_URL, headers=HEADERS, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        check("获取最新 Release", False, str(e)[:80])
        return finish()

    if is_rate_limited(r):
        return rate_limited_fallback(expect_tag or local_ver)
    if r.status_code != 200:
        check("获取最新 Release", False, f"HTTP {r.status_code}（可能尚未发布 Release）")
        return finish()

    release = r.json()
    tag = str(release.get("tag_name", "")).lstrip("vV")
    check("获取最新 Release", bool(tag), f"tag=v{tag}")
    if expect_tag:
        check(f"tag 为 v{expect_tag}", version_tuple(tag) == version_tuple(expect_tag),
              f"实际 v{tag}")
    check("Release 版本不低于本地 VERSION",
          version_tuple(tag) >= version_tuple(local_ver),
          f"Release v{tag} / 本地 v{local_ver}")
    check("Release 已正式发布（非草稿/预发布）",
          not release.get("draft", True) and not release.get("prerelease", False),
          "draft=%s prerelease=%s" % (release.get("draft"), release.get("prerelease")))

    # 3. 资产
    asset = next((a for a in release.get("assets", [])
                  if a.get("name") == ASSET_NAME), None)
    if not asset:
        check(f"资产 {ASSET_NAME} 存在", False,
              "实际资产: " + ", ".join(a.get("name", "?") for a in release.get("assets", [])))
        return finish()
    check(f"资产 {ASSET_NAME} 存在", True,
          f"{asset['size']/1048576:.1f} MB, 下载次数={asset.get('download_count', 0)}")

    # 4-5. 本地大小比对 + 直链/镜像连通性
    probe_channels(asset["browser_download_url"], asset["size"])
    return finish()


def rate_limited_fallback(tag):
    """API 限流时：跳过 API 检查，用可预测的下载直链继续验证下载通道"""
    print("[WARN] GitHub API 未认证请求已限流(60次/小时)，跳过 API 元数据检查。")
    print("       如需完整检查: $env:GITHUB_TOKEN='你的token'; python verify_release.py")
    for name in ("仓库可访问且为公开", "获取最新 Release", "Release 版本检查",
                 "Release 发布状态", f"资产 {ASSET_NAME} 元数据"):
        skip(name, "API 限流")
    dl_url = (f"https://github.com/{OWNER}/{REPO}/releases/download/"
              f"v{tag}/{ASSET_NAME}")
    print(f"       改用直链验证下载通道: .../download/v{tag}/{ASSET_NAME}")
    probe_channels(dl_url)
    return finish()


def finish():
    print("=" * 64)
    print(f"结果: {len(passed)} 通过, {len(failed)} 失败, {len(skipped)} 跳过")
    if failed:
        print("失败项: " + "; ".join(failed))
        return 1
    if skipped:
        print("下载链路正常；API 元数据项因限流跳过，设 GITHUB_TOKEN 后可完整复查。")
        return 0
    print("全部通过，自动更新链路正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
