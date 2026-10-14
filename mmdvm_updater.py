import sys
import os
import tkinter as tk
from tkinter import messagebox

# 添加本地库路径
_script_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
_lib_dir = os.path.join(_script_dir, '_lib')
if os.path.isdir(_lib_dir) and _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

# 验证 paramiko 是否可用
try:
    import paramiko
except ImportError as e:
    messagebox.showerror("错误", f"无法导入 paramiko: {e}\n\n_lib_dir = {_lib_dir}\n\n请确保 _lib 目录存在且包含 paramiko 模块。")
    sys.exit(1)

from tkinter import ttk
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import re
import webbrowser
from brand_database import BrandDatabase

# pandas、requests、json、shutil、tempfile、subprocess 将在使用时局部导入
# （从 _lib 加载，避免启动时全部加载）

class MMDVMUpdater:
    VERSION = "2.0"

    # GitHub Releases 自动更新配置
    GITHUB_OWNER = "bytsly"
    GITHUB_REPO = "mmdvm"
    GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    # Release 资产中要下载的主程序文件名（每次发版必须用这个文件名）
    UPDATE_ASSET_NAME = "mmdvm_updater.exe"
    # 下载地址前缀，按顺序尝试：原始 GitHub 直链 + 国内加速镜像
    UPDATE_MIRROR_PREFIXES = [
        "",
        "https://ghproxy.net/",
        "https://mirror.ghproxy.com/",
    ]
    
    def __init__(self, root):
        self.root = root
        # 在窗口标题中显示版本号
        self.root.title(f"MMDVM数据更新程序 v{self.VERSION}")
        self.root.geometry("815x500")

        # 启动时检查程序更新
        threading.Thread(target=self.check_for_updates, daemon=True).start()

        # 添加断点续传标志
        self.is_resuming = False
        self.resume_file = ""
        # 添加当前文件标志
        self.current_file = ""

        # 联系人转换相关变量
        self.brand_db = None
        self.contact_conversion_enabled = False
        
        # 设置中文字体支持
        self.style = ttk.Style()
        self.style.configure("TLabel", font=("SimHei", 10))
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabelframe.Label", font=("SimHei", 10, "bold"))
        
        # 存储找到的设备
        self.devices = []
        self.scan_running = False  # 扫描状态标志
        
        # 创建界面组件
        self.create_widgets()
        
        # SSH客户端
        self.ssh = None
        self.connected_ip = None

        # 盒子服务器类型（登录后检测："国服" / "BM"）
        self.server_type = None
        
        # 要更新的文件列表 - 8601国服地址
        self.files_to_update = [
            {
                "name": "DMRIds.dat",
                "url": "http://bh5hwp.zj130.com/8601/8601idxiazai/DMRIds.dat",
                "target": "/usr/local/etc/DMRIds.dat"
            },
            {
                "name": "user.csv",
                "url": "http://bh5hwp.zj130.com/8601/8601idxiazai/user.csv",
                "target": "/usr/local/etc/user.csv"
            },
            {
                "name": "NXDN.csv",
                "url": "http://bh5hwp.zj130.com/8601/8601idxiazai/NXDN.csv",
                "target": "/usr/local/etc/NXDN.csv"
            }
        ]
        
        # 需要恢复可修改属性的文件列表
        self.files_to_unlock = [
            "/usr/local/etc/DMRIds.dat",
            "/usr/local/etc/user.csv",
            "/usr/local/etc/NXDN.csv"
        ]

    def center_window(self, window):
        """将窗口固定在程序窗口中心"""
        # 更新窗口以确保获取正确的尺寸
        window.update_idletasks()
        
        # 获取主窗口位置和尺寸
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()
        
        # 获取对话框尺寸
        dialog_width = window.winfo_width()
        dialog_height = window.winfo_height()
        
        # 计算居中位置
        x = root_x + (root_width - dialog_width) // 2
        y = root_y + (root_height - dialog_height) // 2
        
        # 设置窗口位置
        window.geometry(f"+{x}+{y}")

    def create_widgets(self):
        # 顶部主框架 - 包含设备管理和登录信息
        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill="x", padx=10, pady=5)
        top_frame.grid_columnconfigure(0, weight=0)  # 左列固定宽度
        top_frame.grid_columnconfigure(1, weight=1)  # 右列自适应，占满剩余宽度

        # 左侧：设备管理区域（包含发现的设备）- 固定宽300 高200
        device_management_frame = ttk.LabelFrame(top_frame, text="设备管理", width=300, height=200)
        device_management_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 5),
            pady=5
        )
        device_management_frame.grid_propagate(False)  # 禁止内容撑开，强制固定尺寸
        
        # 扫描控制内容
        self.scan_button = ttk.Button(device_management_frame, text="开始扫描", command=self.start_scan)
        self.scan_button.pack(side="top", padx=10, pady=3, fill="x")
        
        self.scan_status = ttk.Label(device_management_frame, text="等待扫描...")
        self.scan_status.pack(side="top", padx=10, pady=1, fill="x")
        
        # 发现的设备区域
        devices_subframe = ttk.LabelFrame(device_management_frame, text="发现的设备")
        devices_subframe.pack(side="top", fill="both", expand=True, padx=10, pady=5)
        
        # 设备滚动区域 - 减小高度
        self.devices_canvas = tk.Canvas(devices_subframe, height=100)
        scrollbar = ttk.Scrollbar(
            devices_subframe, 
            orient="vertical", 
            command=self.devices_canvas.yview
        )
        self.devices_frame_inner = ttk.Frame(self.devices_canvas)
        
        self.devices_frame_inner.bind(
            "<Configure>",
            lambda e: self.devices_canvas.configure(
                scrollregion=self.devices_canvas.bbox("all")
            )
        )
        
        self.devices_canvas.create_window(
            (0, 0), 
            window=self.devices_frame_inner, 
            anchor="nw"
        )
        self.devices_canvas.configure(yscrollcommand=scrollbar.set)
        
        self.devices_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 右侧：登录信息区域 - 自适应占满剩余宽度（最小350），高200
        login_frame = ttk.LabelFrame(top_frame, text="登录信息", width=350, height=200)
        login_frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(5, 0),
            pady=5
        )
        login_frame.grid_propagate(False)  # 禁止内容撑开，强制固定尺寸
        
        ttk.Label(login_frame, text="IP地址:").pack(side="top", anchor="w", padx=5, pady=1)
        self.ip_entry = ttk.Entry(login_frame)
        self.ip_entry.pack(side="top", fill="x", padx=5, pady=1)
        
        ttk.Label(login_frame, text="用户名:").pack(side="top", anchor="w", padx=5, pady=1)
        self.user_entry = ttk.Entry(login_frame)
        self.user_entry.insert(0, "pi-star")
        self.user_entry.pack(side="top", fill="x", padx=5, pady=1)
        
        ttk.Label(login_frame, text="密码:").pack(side="top", anchor="w", padx=5, pady=1)
        self.pass_entry = ttk.Entry(login_frame, show="*")
        self.pass_entry.insert(0, "raspberry")
        self.pass_entry.pack(side="top", fill="x", padx=5, pady=1)
        
        self.login_button = ttk.Button(login_frame, text="登录", command=self.login)
        self.login_button.pack(side="top", padx=5, pady=3, fill="x")
        
        self.login_status = ttk.Label(login_frame, text="未登录")
        self.login_status.pack(side="top", padx=5, pady=1, fill="x")
        
        # 使用说明区域
        instruction_frame = ttk.LabelFrame(self.root, text="使用说明")
        instruction_frame.pack(fill="x", padx=10, pady=(0, 5))

        instruction_text = ("本软件为MMDVM联系人更新软件。\n"
                            "1、开始扫描，在发现的设备中单击填入登录信息（双击打开设备网页）\n"
                            "2、点击登录，自动识别盒子为国服或BM，并把呼号数据库下载到软件目录的 up 目录\n"
                            "3、（可选）点 编辑user.csv，按呼号查询后把数字联系人的姓名、QTH 改成中文并提交保存；勾选 BI7ANY大屏 则生成大屏中文联系人并配置显示\n"
                            "4、点 更新盒子，把 up 目录的数据上传到盒子（同时建 stripped.csv 软链接、锁定文件并禁用每日自动更新）\n"
                            "5、联系人工具用于生成手台联系人文件，模板放 CSV 目录，结果在 OUT 目录查找")
        instruction_label = ttk.Label(
            instruction_frame,
            text=instruction_text,
            justify="left",
            wraplength=800,
            font=('SimHei', 11, 'bold')
        )
        instruction_label.pack(padx=10, pady=10, fill="x")

        # 底部：更新框架 - 数据管理区域
        update_frame = ttk.LabelFrame(self.root, text="数据管理")
        update_frame.pack(fill="x", padx=10, pady=(10, 10))
        
        # 创建按钮水平框架
        buttons_frame = ttk.Frame(update_frame)
        buttons_frame.pack(fill="x", padx=5, pady=5)
        
        # 编辑 user.csv 按钮（放在更新盒子前面，根据 up/user.csv 是否存在启用）
        self.edit_user_button = ttk.Button(buttons_frame, text="编辑user.csv", command=self.edit_user_csv, state="disabled", width=15)
        self.edit_user_button.pack(side="left", padx=5)

        # 更新盒子按钮（合并原"国服数据下载④"与"合并服数据下载⑥"，按检测到的服务器类型自动选择）
        self.update_button = ttk.Button(buttons_frame, text="更新盒子", command=self.update_box, state="disabled", width=15)
        self.update_button.pack(side="left", padx=5)
        # 别名保留，兼容原有代码中对 bm_download_button 的状态更新引用
        self.bm_download_button = self.update_button
        
    # 写入盒子按钮已移除（按用户要求），此处保留占位以保持布局

        # 联系人转换按钮
        self.contact_convert_button = ttk.Button(buttons_frame, text="联系人工具", command=self.convert_contacts, state="normal", width=15)
        self.contact_convert_button.pack(side="left", padx=5)

        # BI7ANY 大屏选项：勾选后更新盒子时自动生成 nextionUsers.csv 并配置 MMDVMHost.ini
        self.bi7any_var = tk.BooleanVar(value=False)
        self.bi7any_check = ttk.Checkbutton(buttons_frame, text="BI7ANY大屏", variable=self.bi7any_var)
        self.bi7any_check.pack(side="left", padx=5)
        
        # 进度条框架
        progress_frame = ttk.Frame(update_frame)
        progress_frame.pack(fill="x", expand=True, padx=5, pady=5)
        
        # 进度条
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", expand=True)
        
        # 百分比标签
        self.progress_label = ttk.Label(progress_frame, text="0.00%")
        self.progress_label.pack(anchor="e", padx=5, pady=2)
        # 根据 up/user.csv 的存在情况更新按钮状态
        try:
            self.update_up_dependent_buttons()
        except Exception:
            pass
    
    def log(self, message):
        """日志方法保持存在，但不显示在界面上"""
        pass

    def update_up_dependent_buttons(self):
        """检查本地 up/user.csv 是否存在，根据结果启用或禁用相关按钮（仅修改 GUI 状态）。

    控制的按钮：
    - self.contact_convert_button
    - self.edit_user_button
        """
        try:
            import os, sys
            if getattr(sys, 'frozen', False):
                script_dir = os.path.dirname(sys.executable)
            else:
                script_dir = os.path.dirname(os.path.abspath(__file__))

            up_dir = os.path.join(script_dir, 'up')
            user_csv = os.path.join(up_dir, 'user.csv')
            exists = os.path.exists(user_csv)

            state = 'normal' if exists else 'disabled'

            # 保护性判断：按钮可能尚未创建
            if hasattr(self, 'contact_convert_button'):
                self.contact_convert_button.config(state=state)
            if hasattr(self, 'edit_user_button'):
                self.edit_user_button.config(state=state)
        except Exception:
            # 忽略任何检查时的错误，避免影响主流程
            pass
        
    def start_scan(self):
        """开始扫描局域网设备"""
        if self.scan_running:
            # 停止扫描
            self.scan_running = False
            self.scan_button.config(text="开始扫描")
            self.scan_status.config(text="扫描已停止")
            return
            
        self.scan_running = True
        self.scan_button.config(text="停止扫描")
        self.scan_status.config(text="扫描中...")
        
        # 清空之前的设备
        for widget in self.devices_frame_inner.winfo_children():
            widget.destroy()
        self.devices = []
        
        # 在新线程中执行扫描，避免界面卡顿
        scan_thread = threading.Thread(target=self.scan_devices)
        scan_thread.daemon = True
        scan_thread.start()
        
    def is_port_open(self, ip, port):
        """检查指定IP的端口是否开放"""
        if not self.scan_running:
            return False
            
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)  # 缩短超时时间
                result = s.connect_ex((ip, port))
                return result == 0
        except:
            return False
        
    def check_device(self, ip):
        """检查单个IP是否有开放的端口"""
        if not self.scan_running:
            return None
            
        # 检查是否开放22端口
        if self.is_port_open(ip, 22):
            return ip
        return None
        
    def scan_devices(self):
        """扫描局域网中开放指定端口的设备"""
        # 获取本地IP地址
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # 连接到一个不会响应的地址来获取本地IP
            s.connect(("10.255.255.255", 1))
            local_ip = s.getsockname()[0]
        except:
            local_ip = "192.168.1.1"
        finally:
            s.close()
        
        # 提取IP前缀（如192.168.1.）
        ip_prefix = ".".join(local_ip.split(".")[:3]) + "."
        
        # 使用线程池并行扫描，加快速度
        max_threads = 50  # 同时扫描的线程数
        found_devices = []
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            # 提交所有IP扫描任务
            futures = {executor.submit(self.check_device, f"{ip_prefix}{i}"): i for i in range(1, 255)}
            
            # 处理扫描结果
            for future in as_completed(futures):
                if not self.scan_running:  # 如果扫描已停止，取消所有任务
                        executor.shutdown(wait=False)  # Python 3.7.3不支持cancel_futures参数
                        break
                    
                ip = future.result()
                if ip:
                    found_devices.append(ip)
                    self.root.after(0, self.add_device_button, ip)
        
        # 扫描完成
        self.root.after(0, self.scan_complete, len(found_devices))
        
    def add_device_button(self, ip):
        """添加设备按钮到界面：单击填入登录信息，双击打开设备网页"""
        btn = ttk.Button(
            self.devices_frame_inner,
            text=ip,
            command=lambda: self.select_device(ip)
        )
        btn.bind("<Double-1>", lambda e: self.open_device_web(ip))
        btn.pack(fill="x", padx=5, pady=2)

    def open_device_web(self, ip):
        """在浏览器中打开设备网页"""
        try:
            webbrowser.open(f"http://{ip}/")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开网页: {e}")
        
    def scan_complete(self, device_count):
        """扫描完成后的处理"""
        self.scan_running = False
        self.scan_button.config(text="开始扫描")
        self.scan_status.config(text=f"扫描完成，发现 {device_count} 个设备")
        
    def select_device(self, ip):
        """选择设备，填充IP地址到输入框"""
        self.ip_entry.delete(0, tk.END)
        self.ip_entry.insert(0, ip)
        self.connected_ip = ip
        
    def login(self):
        """登录到选中的设备"""
        ip = self.ip_entry.get()
        username = self.user_entry.get()
        password = self.pass_entry.get()
        
        if not ip:
            messagebox.showerror("错误", "请输入或选择IP地址")
            return
        
        self.login_status.config(text="登录中...")
        self.login_button.config(state="disabled", text="登录")
        
        # 在新线程中执行登录，避免界面卡顿
        login_thread = threading.Thread(target=self.ssh_login, args=(ip, username, password))
        login_thread.daemon = True
        login_thread.start()
        
    def ssh_login(self, ip, username, password):
        """SSH登录到设备"""
        try:
            # 创建SSH客户端
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 连接
            self.ssh.connect(ip, port=22, username=username, password=password, timeout=10)
            
            # 登录成功
            self.root.after(0, self.login_success, ip)
        except Exception as e:
            self.root.after(0, self.login_failed, str(e))
        
    def login_success(self, ip):
        """登录成功处理"""
        self.login_status.config(text=f"已登录到 {ip}", foreground="green")
        self.login_button.config(state="normal", text="登录")
        self.update_button.config(state="normal", text="更新盒子")
        
        self.bm_download_button.config(state="normal")

        self.connected_ip = ip  # 确保设置连接的IP地址

        # 登录后根据 up 目录内容更新联系人转换按钮状态
        try:
            self.update_up_dependent_buttons()
        except Exception:
            pass

        # 登录后检查mmdvm.ini中的呼号ID，自动判断国服/BM并调用对应下载
        threading.Thread(target=self.detect_server_type, daemon=True).start()

    def detect_server_type(self):
        """登录后检查mmdvm.ini中的呼号ID，判断盒子服务器类型并自动调用对应下载链接"""
        # 常见的mmdvm配置文件路径
        cmd = ("for f in /usr/local/etc/mmdvm.ini /etc/mmdvm.ini /etc/mmdvmhost /etc/mmdvmhost.ini; do "
               "[ -f $f ] && echo ==FILE==$f && grep -iE '^[[:space:]]*(Id|DMRId|RadioId)[[:space:]]*=' $f; done")
        output = ""
        try:
            output = self.execute_ssh_command(cmd, check_output=False)
        except Exception:
            output = ""

        # 提取第一个有效的纯数字呼号ID（DMR ID一般为6位以上数字）
        dmr_id = ""
        for line in output.splitlines():
            if "=" in line:
                val = line.split("=", 1)[1].strip()
                if val.isdigit() and len(val) >= 6:
                    dmr_id = val
                    break

        if dmr_id.startswith("86"):
            server_type = "国服"
        elif dmr_id.startswith("46"):
            server_type = "BM"
        else:
            # 未识别到ID或前缀不匹配，不自动下载
            self.root.after(0, lambda: self.login_status.config(
                text=f"已登录到 {self.connected_ip}（未识别呼号ID，请手动处理）", foreground="orange"))
            return

        self.server_type = server_type
        self.root.after(0, lambda: self.login_status.config(
            text=f"已登录到 {self.connected_ip}（呼号ID {dmr_id}，{server_type}）", foreground="green"))

        # 识别成功后，自动把呼号数据库下载到本地 up 目录（不上传盒子）
        self.download_callsign_db_to_up(server_type)

    def download_callsign_db_to_up(self, server_type):
        """登录后自动下载呼号数据库（DMRIds.dat/user.csv/NXDN.csv）到软件目录 up，仅本地保存、不动盒子"""
        import requests
        import time

        if server_type == "国服":
            files = [(f["name"], f["url"]) for f in self.files_to_update]
        else:
            base_url = "http://downloads.zj130.com:9080/8601/860to460"
            files = [(name, f"{base_url}/{name}")
                     for name in ("DMRIds.dat", "user.csv", "NXDN.csv")]

        up_dir = self._get_up_dir()
        try:
            os.makedirs(up_dir, exist_ok=True)
            self.root.after(0, lambda: self.log(f"开始自动下载{server_type}呼号数据库到 up 目录..."))

            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            max_retries = 3

            for name, url in files:
                self.current_file = name
                final_path = os.path.join(up_dir, name)
                tmp_path = final_path + ".part"
                self.root.after(0, lambda fn=name: self.log(f"正在下载 {fn}..."))

                last_err = ""
                for attempt in range(1, max_retries + 1):
                    try:
                        with requests.get(url, stream=True, headers=headers, timeout=120, allow_redirects=True) as resp:
                            if resp.status_code != 200:
                                raise Exception(f"服务器返回状态码: {resp.status_code}")
                            with open(tmp_path, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=65536):
                                    if chunk:
                                        f.write(chunk)
                        # 下载完成，原子替换
                        os.replace(tmp_path, final_path)
                        size_mb = os.path.getsize(final_path) / (1024 * 1024)
                        self.root.after(0, lambda fn=name, s=size_mb: self.log(f"✅ {fn} 已保存到 up 目录 ({s:.2f} MB)"))
                        last_err = ""
                        break
                    except Exception as e:
                        last_err = str(e)
                        if os.path.exists(tmp_path):
                            try:
                                os.remove(tmp_path)
                            except OSError:
                                pass
                        if attempt < max_retries:
                            self.root.after(0, lambda fn=name, r=attempt, err=last_err:
                                self.log(f"⚠️ {fn} 下载失败({err})，第 {r} 次重试..."))
                            time.sleep(2)
                else:
                    self.root.after(0, lambda fn=name, err=last_err:
                        self.log(f"❌ {fn} 自动下载失败: {err}（可点击更新盒子重试）"))

            self.root.after(0, lambda: self.log("呼号数据库下载结束，可在联系人工具中查看/编辑"))
            self.root.after(0, self.update_up_dependent_buttons)
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.log(f"⚠️ 自动下载呼号数据库出错: {err}"))
        finally:
            self.root.after(0, lambda: setattr(self, 'current_file', ""))

    def update_box(self):
        """统一更新盒子入口：根据登录时检测的服务器类型调用对应的数据下载"""
        if self.server_type == "国服":
            self.update_all_data()
        elif self.server_type == "BM":
            self.download_bm_data()
        else:
            messagebox.showinfo("提示", "尚未识别到盒子服务器类型（国服/BM），请重新登录设备后再试。")
        
    def check_merge_ready_state(self):
        """检查hb1和hb2目录是否有可合并的文件，并更新合并按钮状态"""
        if not self.ssh or not self.connected_ip:
            return
        
        # 在新线程中执行检查，避免UI卡顿
        check_thread = threading.Thread(target=self._perform_merge_ready_check)
        check_thread.daemon = True
        check_thread.start()
        
    def _perform_merge_ready_check(self):
        """执行合并准备状态检查的实际操作"""
        try:
            remote_hb1_dir = '/home/mmdvm/hb1/'
            remote_hb2_dir = '/home/mmdvm/hb2/'
            
            # 检查远程目录中是否有文件
            dir1_files_cmd = f"ls {remote_hb1_dir} 2>/dev/null"
            dir1_files_output = self.execute_ssh_command(dir1_files_cmd, check_output=False)
            
            dir2_files_cmd = f"ls {remote_hb2_dir} 2>/dev/null"
            dir2_files_output = self.execute_ssh_command(dir2_files_cmd, check_output=False)
            
            # 检查两个目录是否都有文件
            has_hb1_files = bool(dir1_files_output.strip())
            has_hb2_files = bool(dir2_files_output.strip())
            
            # 更新按钮状态
            if has_hb1_files and has_hb2_files:
                self.root.after(0, lambda: self.log("发现可合并的文件，可以通过BM下载后自动合并上传功能使用"))
            else:
                # 使用f-string构建状态文本
                missing_parts = []
                if not has_hb1_files:
                    missing_parts.append("缺少国服数据")
                if not has_hb2_files:
                    missing_parts.append("缺少BM数据")

                if not has_hb1_files:
                    self.root.after(0, lambda: self.log("提示：请先执行国服数据下载"))
                if not has_hb2_files:
                    self.root.after(0, lambda: self.log("提示：请先执行BM数据下载"))
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.log(f"检查合并准备状态时出错: {err}"))
        
    def login_failed(self, error_msg):
        """登录失败处理"""
        self.login_status.config(text="登录失败", foreground="red")
        self.login_button.config(state="normal", text="登录")
        self.update_button.config(state="disabled", text="更新盒子")
        
        self.bm_download_button.config(state="disabled")  # 禁用BM数据下载按钮
        
        # 替换错误信息中的域名链接、纯域名和IP地址为"服务器"
        import re
        modified_error_msg = str(error_msg)
        # 匹配HTTP/HTTPS URL
        modified_error_msg = re.sub(r'https?://[^\s]+', '服务器', modified_error_msg)
        # 匹配纯域名(如example.com)
        modified_error_msg = re.sub(r'([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+\.?)', '服务器', modified_error_msg)
        # 匹配IP地址
        modified_error_msg = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '服务器', modified_error_msg)
        messagebox.showerror("失败", f"登录失败: {modified_error_msg}")
        self.ssh = None
        
    def perform_dual_data_merge_and_upload(self):
        """执行双服数据合并并自动上传到设备的操作"""
        try:
            self.root.after(0, lambda: self.log("🚀 开始执行自动合并和上传操作"))
            
            # 首先执行合并操作
            self.root.after(0, lambda: self.log("🔄 正在执行双服数据合并..."))
            self.perform_dual_data_merge()
            
            # 等待合并完成并获取合并文件
            import os, sys, time
            time.sleep(1)  # 给合并操作一点时间完成
            
            # 获取脚本所在目录
            if getattr(sys, 'frozen', False):
                script_dir = os.path.dirname(sys.executable)
            else:
                script_dir = os.path.dirname(os.path.abspath(__file__))
            
            up_dir = os.path.join(script_dir, 'up')
            
            # 检查up目录中是否有合并后的文件
            if not os.path.exists(up_dir):
                self.root.after(0, lambda: messagebox.showerror("上传失败", f"未找到合并文件目录: {up_dir}\n\n请手动执行上传操作。"))
                return
            
            # 获取up目录中的所有文件
            merge_files = [f for f in os.listdir(up_dir) if os.path.isfile(os.path.join(up_dir, f))]
            
            if not merge_files:
                self.root.after(0, lambda: messagebox.showerror("上传失败", f"合并文件目录为空: {up_dir}\n\n请手动执行上传操作。"))
                return
            
            self.root.after(0, lambda: self.log(f"📋 发现以下合并文件: {', '.join(merge_files)}"))
            
            # 上传每个文件到设备
            self.root.after(0, lambda: self.log("📤 开始上传合并文件到设备..."))
            
            # 执行文件系统可写挂载
            remount_cmd = "mount -o remount,rw /"
            self.execute_ssh_command_with_sudo(remount_cmd)
            
            # 设置进度
            total_files = len(merge_files)
            progress_step = 100 / total_files
            current_progress = 0
            
            # 定义目标目录
            remote_target_dir = "/usr/local/etc/"
            
            # 上传每个文件
            for index, file_name in enumerate(merge_files):
                local_file_path = os.path.join(up_dir, file_name)
                remote_file_path = os.path.join(remote_target_dir, file_name)
                
                self.root.after(0, lambda fn=file_name: self.log(f"📤 正在上传文件: {fn}"))
                
                # 设置当前文件名
                self.current_file = file_name
                
                try:
                    # 移除不可修改属性
                    chattr_unlock_cmd = f"chattr -i {remote_file_path}"
                    self.execute_ssh_command_with_sudo(chattr_unlock_cmd, check_output=False)
                    
                    # 设置文件权限
                    perm_cmd = f"chmod 777 {remote_file_path}"
                    self.execute_ssh_command_with_sudo(perm_cmd, check_output=False)
                    
                    # 使用SFTP上传文件
                    sftp = self.ssh.open_sftp()
                    tmp_path = f"/tmp/{file_name}"
                    sftp.put(local_file_path, tmp_path)
                    sftp.close()
                    
                    # 复制到目标位置
                    copy_cmd = f"cp {tmp_path} {remote_file_path}"
                    self.execute_ssh_command_with_sudo(copy_cmd)
                    
                    # 创建目标目录并移动临时文件到/home/mmdvm/hb1/目录
                    mkdir_cmd = "mkdir -p /home/mmdvm/hb1"
                    self.execute_ssh_command_with_sudo(mkdir_cmd, check_output=False)
                    move_cmd = f"mv {tmp_path} /home/mmdvm/hb1/"
                    self.execute_ssh_command_with_sudo(move_cmd, check_output=False)
                    
                    # 设置文件权限为755
                    chmod_cmd = f"chmod 755 {remote_file_path}"
                    self.execute_ssh_command_with_sudo(chmod_cmd, check_output=False)
                    
                    # 设置不可修改属性
                    chattr_lock_cmd = f"chattr +i {remote_file_path}"
                    self.execute_ssh_command_with_sudo(chattr_lock_cmd)
                    
                    current_progress = (index + 1) * progress_step
                    self.root.after(0, self.update_progress, current_progress)
                    
                    self.root.after(0, lambda fn=file_name: self.log(f"✅ {fn} 上传成功并设置为不可修改"))
                    
                except Exception as e:
                    self.root.after(0, lambda err=str(e), fn=file_name: self.log(f"❌ 上传{fn}时出错: {err}"))
                    # 继续上传其他文件，不中断整个过程
                    continue
            
            # 上传完成
            self.root.after(0, self.update_progress, 100)
            self.root.after(0, lambda: setattr(self, 'current_file', ""))
            self.root.after(0, lambda: self.log("✅ 所有合并文件上传完成！"))
            self.root.after(0, lambda: messagebox.showinfo("成功", "双服数据合并并自动上传完成！\n\n已将合并后的文件上传到设备的/usr/local/etc/目录。"))
            
            # 询问是否重启设备
            self.root.after(0, self.ask_restart_device)
            
        except Exception as e:
            self.root.after(0, lambda err=str(e): messagebox.showerror("自动合并上传失败", f"执行自动合并和上传时出错：{err}\n\n请手动执行双服数据合并和上传操作。"))
        finally:
            # 恢复按钮状态
            self.root.after(0, lambda: setattr(self, 'current_file', ""))
            self.root.after(0, lambda: self.bm_download_button.config(state="normal"))

    def perform_dual_data_merge(self):
        """执行双服数据合并操作 - 修复：确保本地和远程目录统一"""
        try:
            # 导入必要的模块
            import os, sys

            # 显示进度
            self.root.after(0, self.update_progress, 0)

            # 定义本地目录和远程目录
            # 使用脚本所在目录作为基准，而不是当前工作目录，确保路径一致性
            # 获取脚本所在目录（即使作为可执行文件运行）
            if getattr(sys, 'frozen', False):
                # 作为可执行文件运行
                script_dir = os.path.dirname(sys.executable)
            else:
                # 作为Python脚本运行
                script_dir = os.path.dirname(os.path.abspath(__file__))
                
            local_tmp_dir = os.path.join(script_dir, 'temp_bm_data')
            remote_hb1_dir = '/home/mmdvm/hb1/'
            remote_hb2_dir = '/home/mmdvm/hb2/'
            up_dir = os.path.join(script_dir, 'up')
            
            # 记录使用的目录路径以便调试
            self.root.after(0, lambda dir=script_dir: self.log(f"🔍 程序运行目录: {dir}"))
            self.root.after(0, lambda dir=local_tmp_dir: self.log(f"🔍 临时文件目录: {dir}"))
            self.root.after(0, lambda dir=up_dir: self.log(f"🔍 合并文件保存目录: {dir}"))
            
            # 创建必要的本地目录
            if not os.path.exists(local_tmp_dir):
                os.makedirs(local_tmp_dir)
            
            if not os.path.exists(up_dir):
                os.makedirs(up_dir)
            
            # 首先检查远程设备上的hb1和hb2目录是否存在
            self.root.after(0, lambda: self.log("检查远程设备上的目录..."))
            
            # 创建远程目录（如果不存在）
            self.execute_ssh_command_with_sudo(f"mkdir -p {remote_hb1_dir} {remote_hb2_dir}", check_output=False)
            
            # 检查远程目录中是否有文件
            dir1_files_cmd = f"ls {remote_hb1_dir} 2>/dev/null"
            dir1_files_output = self.execute_ssh_command(dir1_files_cmd, check_output=False)
            
            dir2_files_cmd = f"ls {remote_hb2_dir} 2>/dev/null"
            dir2_files_output = self.execute_ssh_command(dir2_files_cmd, check_output=False)
            
            # 检查两个目录是否都有文件
            if not dir1_files_output.strip():
                self.root.after(0, lambda: messagebox.showinfo("提示", "国服数据目录为空，请先执行国服数据下载。"))
                self.root.after(0, self.update_progress, 100)
                return
            
            if not dir2_files_output.strip():
                self.root.after(0, lambda: messagebox.showinfo("提示", "BM数据目录为空，请先执行BM数据下载。"))
                self.root.after(0, self.update_progress, 100)
                return
            
            # 获取远程目录中的文件名列表
            dir1_files = set(dir1_files_output.strip().split('\n'))
            dir2_files = set(dir2_files_output.strip().split('\n'))
            
            # 找出同名文件
            common_files = dir1_files.intersection(dir2_files)
            
            if not common_files:
                self.root.after(0, lambda: messagebox.showinfo("提示", "没有找到同名文件进行合并。"))
                self.root.after(0, self.update_progress, 100)
                return
            
            # 使用SFTP下载文件进行合并
            sftp = self.ssh.open_sftp()
            
            # 合并每个同名文件
            total_files = len(common_files)
            for index, file_name in enumerate(common_files, 1):
                # 更新当前文件名显示
                self.current_file = f"合并 {file_name}"
                
                try:
                    # 定义本地临时文件路径
                    local_file1 = os.path.join(local_tmp_dir, f"file1_{file_name}")
                    local_file2 = os.path.join(local_tmp_dir, f"file2_{file_name}")
                    merged_path = os.path.join(up_dir, file_name)
                    
                    # 从远程设备下载文件
                    self.root.after(0, lambda: self.log(f"下载文件: {file_name}"))
                    # 下载顺序调整：确保国服数据放在合并后的文件前面
                    # 先下载BM数据(hb2)到local_file1，用于保留表头信息
                    sftp.get(os.path.join(remote_hb2_dir, file_name), local_file1)
                    # 再下载国服数据(hb1)到local_file2，将在合并时放在前面
                    sftp.get(os.path.join(remote_hb1_dir, file_name), local_file2)
                    
                    # 读取两个文件的内容，并处理CSV表头
                    # 添加编码检测和容错处理，避免UTF-8解码错误
                    def read_file_with_fallback_encoding(file_path):
                        # 增加更多常见的中文编码支持
                        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'utf-16', 'latin-1']
                        detected_encoding = 'utf-8'  # 默认编码
                        for encoding in encodings:
                            try:
                                with open(file_path, 'r', encoding=encoding) as f:
                                    # 尝试读取全部内容以确保编码正确
                                    content = f.read()
                                    lines = content.splitlines(keepends=True)
                                    detected_encoding = encoding
                                    if encoding != 'utf-8':
                                        self.root.after(0, lambda fn=os.path.basename(file_path), enc=encoding: 
                                            self.log(f"⚠️ 注意: 文件 {fn} 使用了非UTF-8编码: {enc}"))
                                    return lines, detected_encoding
                            except UnicodeDecodeError:
                                continue
                        # 如果所有编码都失败，使用错误替换模式
                        self.root.after(0, lambda fn=os.path.basename(file_path): 
                            self.log(f"❌ 警告: 无法识别文件 {fn} 的编码，使用错误替换模式")
                        )
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                            lines = content.splitlines(keepends=True)
                            return lines, 'utf-8'

                    # 使用容错编码读取文件
                    lines1, encoding1 = read_file_with_fallback_encoding(local_file1)  # BM数据
                    all_lines2, encoding2 = read_file_with_fallback_encoding(local_file2)  # 国服数据
                    
                    # 记录检测到的编码
                    self.root.after(0, lambda e1=encoding1, e2=encoding2: 
                        self.log(f"🔍 检测到的编码 - BM数据: {e1}, 国服数据: {e2}"))
                    
                    # 智能检测并处理表头
                    # 对于不同类型的文件，决定是否跳过表头
                    lines2 = all_lines2  # 保留国服数据的表头
                    
                    # 处理BM数据的表头
                    if len(lines1) > 0:
                        # 对于CSV文件，跳过BM数据的表头
                        if file_name.lower().endswith('.csv'):
                            lines1 = lines1[1:]
                            self.root.after(0, lambda: 
                                self.log("⏭️ 跳过了BM数据的表头"))
                        elif file_name.lower() == 'dmrids.dat':
                            # 对于DMRIds.dat文件，检查BM数据第一行是否包含表头特征
                            first_line = lines1[0].strip()
                            # 检查是否包含表头特征（如逗号分隔的字段名）
                            if ',' in first_line and ('DMR ID' in first_line or 'CallSign' in first_line):
                                # 有表头特征，跳过BM数据的第一行
                                lines1 = lines1[1:]
                                self.root.after(0, lambda: 
                                    self.log("⏭️ 跳过了BM数据的表头"))
                            else:
                                # 没有表头，保留所有行
                                self.root.after(0, lambda: 
                                    self.log("🔄 保留DMRIds.dat的所有行（没有表头）"))
                        else:
                            # 其他文件类型，保留所有行
                            self.root.after(0, lambda fn=file_name: 
                                self.log(f"🔄 保留{fn}的所有行"))
                    
                    # 合并内容：使用国服数据的表头，先添加国服完整数据（包括表头），再添加BM数据内容（不包括表头）
                    merged_lines = lines2 + lines1
                    
                    # 确保每一行都有正确的换行符，避免没有折行的问题
                    normalized_lines = []
                    for line in merged_lines:
                        # 去除行尾的换行符，然后统一添加一个标准的换行符
                        clean_line = line.rstrip('\r\n')
                        normalized_lines.append(clean_line + '\n')
                    
                    # 合并为一个字符串，确保正确处理编码
                    merged_content = ''.join(normalized_lines)
                    
                    # 添加详细的文件写入错误处理
                    try:
                        # 写入合并后的文件 - 保留原始编码以避免中文乱码问题
                        # 优先使用国服数据的编码(encoding2)，因为国服数据包含更多中文内容
                        write_encoding = encoding2
                        # 如果国服数据是使用错误替换模式读取的，则尝试使用BM数据的编码作为备选
                        if write_encoding == 'utf-8' and ('utf-8 (with errors replaced)' in encoding2 or '错误替换' in encoding2):
                            write_encoding = encoding1
                        
                        self.root.after(0, lambda enc=write_encoding, fn=file_name: 
                            self.log(f"💾 使用编码 {enc} 写入合并文件: {fn}"))
                        
                        # 写入合并后的文件，使用检测到的原始编码
                        with open(merged_path, 'w', encoding=write_encoding, newline='') as merged_file:
                            merged_file.write(merged_content)
                        
                        # 验证文件是否成功写入
                        if os.path.exists(merged_path):
                            file_size = os.path.getsize(merged_path)
                            # 重新计算内容的字节长度用于比较
                            content_length = len(merged_content.encode(write_encoding))
                            
                            # 检查文件大小是否与内容长度匹配
                            if file_size == content_length:
                                self.root.after(0, lambda fn=file_name, size=file_size: 
                                    self.log(f"📝 成功写入合并文件: {fn} ({size/1024/1024:.2f} MB)"))
                            else:
                                self.root.after(0, lambda fn=file_name, actual=file_size, expected=content_length: 
                                    self.log(f"⚠️ 警告: 合并文件 {fn} 大小不匹配 (实际: {actual} 字节, 预期: {expected} 字节)"))
                        else:
                            self.root.after(0, lambda fn=file_name: 
                                self.log(f"❌ 错误: 合并文件 {fn} 写入失败，文件不存在"))
                        
                        # 清理临时文件
                        try:
                            os.remove(local_file1)
                            os.remove(local_file2)
                            self.root.after(0, lambda: self.log("🗑️ 已清理临时文件"))
                        except Exception as cleanup_error:
                            self.root.after(0, lambda err=str(cleanup_error): 
                                self.log(f"⚠️ 清理临时文件时出错: {err}"))
                        
                        # 更新进度
                        progress = (index / total_files) * 100
                        self.root.after(0, self.update_progress, progress)
                        
                    except IOError as io_err:
                        self.root.after(0, lambda fn=file_name, err=str(io_err): 
                            self.log(f"❌ IO错误: 写入合并文件 {fn} 时出错: {err}"))
                        raise Exception(f"写入合并文件时出现IO错误: {str(io_err)}")
                    except IOError as io_err:
                        self.root.after(0, lambda fn=file_name, err=str(io_err): 
                            self.log(f"❌ IO错误: 写入合并文件 {fn} 时出错: {err}"))
                        raise Exception(f"写入合并文件时出现IO错误: {str(io_err)}")
                    
                except Exception as e:
                    # 修复NameError: cannot access free variable 'e'的问题
                    # 通过参数传递e的值，确保lambda函数执行时可以访问到
                    self.root.after(0, lambda err=str(e), fn=file_name: messagebox.showerror("合并失败", f"合并文件 {fn} 时出错:\n{err}"))
                    continue
            
            # 关闭SFTP连接
            sftp.close()
            
            # 合并完成 - 添加详细日志记录
            self.root.after(0, self.update_progress, 100)
            self.root.after(0, lambda: setattr(self, 'current_file', ""))
            
            # 获取up_dir的绝对路径，确保显示正确位置
            absolute_up_dir = os.path.abspath(up_dir)
            
            # 检查合并后的文件是否真的存在
            merged_files_exist = False
            try:
                if os.path.exists(absolute_up_dir):
                    merged_files = [f for f in os.listdir(absolute_up_dir) if f.startswith('merged_')]
                    merged_files_exist = len(merged_files) > 0
                    if merged_files_exist:
                        self.root.after(0, lambda files=merged_files, dir=absolute_up_dir: self.log(f"✅ 成功保存以下合并文件到 {dir}:\n" + "\n".join(files)))
                    else:
                        self.root.after(0, lambda: self.log(f"⚠️ 警告：合并操作完成，但在 {absolute_up_dir} 中未找到合并文件"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"检查合并文件时出错: {err}"))
            
            # 显示完成消息，使用绝对路径
            self.root.after(0, lambda: messagebox.showinfo("成功", f"双服数据合并完成！\n合并后的文件已保存到:\n{absolute_up_dir}\n\n请检查该目录确认文件是否存在。"))
            
            # 询问用户是否清空远程的hb1和hb2目录
            self.root.after(0, self.ask_clear_remote_dirs)
            # 合并完成后更新 up 目录相关按钮状态
            self.root.after(0, self.update_up_dependent_buttons)
            
        except Exception as e:
            self.root.after(0, lambda err=str(e): messagebox.showerror("失败", f"双服数据合并失败:\n{err}"))
        finally:
            # 恢复按钮状态
            self.root.after(0, lambda: setattr(self, 'current_file', ""))

    def download_bm_data(self):
        """合并服数据下载⑥功能 - 直接下载已合并的数据"""
        if not self.ssh or not self.connected_ip:
            messagebox.showerror("错误", "请先登录设备")
            return

        self.bm_download_button.config(state="disabled")
        
        # 在新线程中执行下载操作
        download_thread = threading.Thread(target=self.perform_bm_download)
        download_thread.daemon = True
        download_thread.start()

    def upload_up_files_to_box(self, file_specs):
        """把本地 up 目录中的文件通过 SFTP 上传到盒子。

        file_specs: [(本地文件名, 盒子上的绝对路径), ...]
        上传流程：可写挂载 → 解除不可修改属性 → SFTP 上传到 /tmp →
                 复制到目标位置 → 权限 755 → 设置不可修改属性 → 清理临时文件
        """
        up_dir = self._get_up_dir()

        # 预检：本地文件必须全部存在
        missing = [name for name, _ in file_specs
                   if not os.path.exists(os.path.join(up_dir, name))]
        if missing:
            raise Exception("本地 up 目录缺少文件：" + "、".join(missing) +
                            "，请等待登录后自动下载完成后再试")

        # 文件系统重新挂载为可写
        self.execute_ssh_command_with_sudo("mount -o remount,rw /", check_output=False)

        total = len(file_specs)
        for index, (file_name, remote_path) in enumerate(file_specs):
            self.current_file = file_name
            local_path = os.path.join(up_dir, file_name)
            tmp_remote = f"/tmp/{file_name}"

            progress_start = (index / total) * 100
            progress_end = ((index + 1) / total) * 100

            self.root.after(0, self.update_progress, progress_start)
            self.root.after(0, lambda fn=file_name: self.log(f"正在上传 {fn} 到设备..."))

            # 解除不可修改属性并放开权限（文件不存在时忽略错误）
            self.execute_ssh_command_with_sudo(f"chattr -i {remote_path}", check_output=False)
            self.execute_ssh_command_with_sudo(f"chmod 777 {remote_path}", check_output=False)

            # SFTP 上传到 /tmp
            sftp = self.ssh.open_sftp()
            try:
                sftp.put(local_path, tmp_remote)
            finally:
                sftp.close()

            # 复制到目标位置并设置权限/不可修改属性
            self.execute_ssh_command_with_sudo(f"cp {tmp_remote} {remote_path}")
            self.execute_ssh_command_with_sudo(f"chmod 755 {remote_path}", check_output=False)
            self.execute_ssh_command_with_sudo(f"chattr +i {remote_path}")

            # 清理 /tmp 临时文件
            self.execute_ssh_command_with_sudo(f"rm -f {tmp_remote}", check_output=False)

            self.root.after(0, self.update_progress, progress_end)
            self.root.after(0, lambda fn=file_name: self.log(f"✅ {fn} 上传完成"))

        # 全部上传完成后，创建 stripped.csv -> user.csv 软链接
        # （服务器不再单独提供 stripped.csv，让读取它的服务改读 user.csv）
        try:
            stripped_path = "/usr/local/etc/stripped.csv"
            user_path = "/usr/local/etc/user.csv"
            self.execute_ssh_command_with_sudo(f"chattr -i {stripped_path}", check_output=False)
            self.execute_ssh_command_with_sudo(f"rm -f {stripped_path}", check_output=False)
            self.execute_ssh_command_with_sudo(f"ln -s {user_path} {stripped_path}", check_output=False)
            self.root.after(0, lambda: self.log("✅ 已创建 stripped.csv 指向 user.csv 的软链接"))
        except Exception as link_err:
            self.root.after(0, lambda err=str(link_err): self.log(f"⚠️ 创建 stripped.csv 软链接失败: {err}"))

        # 勾选 BI7ANY 大屏时：生成 nextionUsers.csv 上传，并配置 MMDVMHost.ini
        if getattr(self, 'bi7any_var', None) and self.bi7any_var.get():
            try:
                self.configure_bi7any_big_screen(up_dir, enable=True)
            except Exception as bi_err:
                self.root.after(0, lambda err=str(bi_err): self.log(f"⚠️ BI7ANY大屏配置失败: {err}"))
        elif getattr(self, 'bi7any_var', None):
            # 取消勾选：切回原生 stripped.csv 并重启服务
            try:
                self.configure_bi7any_big_screen(up_dir, enable=False)
            except Exception as bi_err:
                self.root.after(0, lambda err=str(bi_err): self.log(f"⚠️ BI7ANY大屏还原失败: {err}"))

    def configure_bi7any_big_screen(self, up_dir, enable=True):
        """BI7ANY 大屏配置。
        enable=True ：从 up/user.csv 生成 nextionUsers.csv 上传，MMDVMHost.ini 的
                      DMRidFile 指向 nextionUsers.csv，并重启 mmdvmhost 服务。
        enable=False：DMRidFile 切回原生 stripped.csv，并重启 mmdvmhost 服务。"""
        ini_path = "/etc/MMDVMHost.ini"

        if enable:
            import csv
            self.root.after(0, lambda: self.log("🖥️ 开始配置 BI7ANY 大屏..."))

            # 1. 从 user.csv 生成 nextionUsers.csv（仅 460 段：ID,呼号,姓名,城市,省份,国家）
            user_csv = os.path.join(up_dir, "user.csv")
            nextion_csv = os.path.join(up_dir, "nextionUsers.csv")
            count = 0
            with open(user_csv, 'r', encoding='utf-8-sig', newline='') as fin, \
                 open(nextion_csv, 'w', encoding='utf-8', newline='') as fout:
                reader = csv.reader(fin)
                writer = csv.writer(fout)
                writer.writerow(["DMR ID", "Callsign", "Name", "City", "Province", "Country"])
                for row in reader:
                    if not row or not row[0].strip():
                        continue
                    dmr_id = row[0].strip()
                    if not dmr_id.isdigit() or not dmr_id.startswith("460"):
                        continue
                    callsign = row[1].strip() if len(row) > 1 else ""
                    name = row[2].strip() if len(row) > 2 else ""
                    city = row[3].strip() if len(row) > 3 else ""
                    province = row[4].strip() if len(row) > 4 else ""
                    country = row[5].strip() if len(row) > 5 else ""
                    writer.writerow([dmr_id, callsign, name, city, province, country])
                    count += 1
            self.root.after(0, lambda c=count: self.log(f"✅ nextionUsers.csv 生成完成（中国 460 段 {c} 条）"))

            # 2. 上传到盒子 /usr/local/etc/nextionUsers.csv
            remote_nextion = "/usr/local/etc/nextionUsers.csv"
            tmp_remote = "/tmp/nextionUsers.csv"
            self.execute_ssh_command_with_sudo(f"chattr -i {remote_nextion}", check_output=False)
            sftp = self.ssh.open_sftp()
            try:
                sftp.put(nextion_csv, tmp_remote)
            finally:
                sftp.close()
            self.execute_ssh_command_with_sudo(f"cp {tmp_remote} {remote_nextion}")
            self.execute_ssh_command_with_sudo(f"chmod 755 {remote_nextion}", check_output=False)
            self.execute_ssh_command_with_sudo(f"chattr +i {remote_nextion}", check_output=False)
            self.execute_ssh_command_with_sudo(f"rm -f {tmp_remote}", check_output=False)
            self.root.after(0, lambda: self.log("✅ nextionUsers.csv 已上传到盒子"))

            # 3. sed 指向 nextionUsers.csv
            sed_cmd = r'sed -i "s/^DMRidFile=.*/DMRidFile=nextionUsers.csv/" /etc/MMDVMHost.ini'
        else:
            # 切回原生 stripped.csv
            self.root.after(0, lambda: self.log("↩️ 还原为原生 stripped.csv ..."))
            sed_cmd = r'sed -i "s/^DMRidFile=.*/DMRidFile=stripped.csv/" /etc/MMDVMHost.ini'

        # 4. 修改配置并重启 mmdvmhost 服务使改动生效
        self.execute_ssh_command_with_sudo(f"chattr -i {ini_path}", check_output=False)
        self.execute_ssh_command_with_sudo(sed_cmd, check_output=False)
        target = "nextionUsers.csv" if enable else "stripped.csv"
        self.root.after(0, lambda t=target: self.log(f"✅ MMDVMHost.ini 的 DMRidFile 已指向 {t}"))
        self.execute_ssh_command_with_sudo("systemctl restart mmdvmhost", check_output=False)
        self.root.after(0, lambda: self.log("✅ mmdvmhost 服务已重启，配置生效"))

    def perform_bm_download(self):
        """执行合并服数据更新 - 将本地 up 目录中的数据文件通过 SFTP 上传到设备"""
        try:
            self.root.after(0, self.update_progress, 0)
            self.root.after(0, lambda: self.log("开始上传合并服数据到设备..."))

            file_specs = [
                ("DMRIds.dat", "/usr/local/etc/DMRIds.dat"),
                ("user.csv", "/usr/local/etc/user.csv"),
                ("NXDN.csv", "/usr/local/etc/NXDN.csv"),
            ]

            # 直接从本地 up 目录上传（文件由登录后自动下载或用户编辑后产生）
            self.upload_up_files_to_box(file_specs)

            self.root.after(0, self.update_progress, 100)
            self.root.after(0, lambda: self.log("✅ 合并服数据上传完成！"))
            self.root.after(0, lambda: messagebox.showinfo("成功", "合并服数据上传完成！"))
            self.root.after(0, self.update_up_dependent_buttons)
            self.root.after(0, self.ask_restart_device)

        except Exception as e:
            import re
            error_msg = str(e)
            error_msg = re.sub(r'https?://[^\s]+', '服务器', error_msg)
            error_msg = re.sub(r'([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+\.?)', '服务器', error_msg)
            self.root.after(0, lambda: messagebox.showerror("失败", f"合并服数据上传失败:\n{error_msg}"))
            self.root.after(0, lambda err=error_msg: self.log(f"❌ 合并服数据上传失败: {err}"))
        finally:
            self.root.after(0, lambda: setattr(self, 'current_file', ""))
            self.root.after(0, lambda: self.bm_download_button.config(state="normal"))

    def perform_specific_file_import(self, local_file_path, target_file_name, target_file_path):
        """执行导入特定文件的操作，返回是否成功"""
        try:
            # 导入os模块
            import os
            
            # 设置当前文件名
            self.current_file = target_file_name
            
            tmp_path = f"/tmp/{target_file_name}"
            
            # 检查文件是否存在
            if not os.path.exists(local_file_path):
                self.root.after(0, lambda: messagebox.showerror("错误", f"找不到文件:\n{local_file_path}"))
                return False
            
            # 显示进度
            self.root.after(0, self.update_progress, 10)
            
            # 检查远程文件是否存在以及版本是否相同
            file_already_up_to_date = False
            try:
                # 获取本地文件信息
                local_stat = os.stat(local_file_path)
                local_modified_time = local_stat.st_mtime
                local_file_size = local_stat.st_size
                
                # 检查远程文件是否存在
                remote_stat_cmd = f"stat -c '%Y %s' {target_file_path} 2>/dev/null"
                remote_stat_result = self.execute_ssh_command(remote_stat_cmd, check_output=False)
                
                if remote_stat_result.strip():
                    # 解析远程文件信息
                    remote_modified_time_str, remote_file_size_str = remote_stat_result.strip().split()
                    remote_modified_time = float(remote_modified_time_str)
                    remote_file_size = int(remote_file_size_str)
                    
                    # 比较版本信息（修改时间和文件大小）
                    time_diff = abs(local_modified_time - remote_modified_time)
                    if time_diff < 5 and local_file_size == remote_file_size:
                        file_already_up_to_date = True
                        self.root.after(0, lambda: messagebox.showinfo("提示", f"{target_file_name}文件版本已经是最新的，无需更新。"))
            except Exception:
                # 如果获取远程文件信息失败（比如文件不存在），则继续执行导入
                pass
            
            # 如果文件版本相同，则停止更新
            if file_already_up_to_date:
                self.root.after(0, self.update_progress, 100)
                return True
            
            # 执行文件系统可写挂载
            self.root.after(0, self.update_progress, 20)
            remount_cmd = "mount -o remount,rw /"
            self.execute_ssh_command_with_sudo(remount_cmd)
            
            # 移除不可修改属性
            self.root.after(0, self.update_progress, 30)
            chattr_unlock_cmd = f"chattr -i {target_file_path}"
            self.execute_ssh_command_with_sudo(chattr_unlock_cmd, check_output=False)
            
            # 设置文件权限
            self.root.after(0, self.update_progress, 40)
            # 检查文件是否存在
            check_file_cmd = f"ls {target_file_path} 2>/dev/null"
            file_check_result = self.execute_ssh_command(check_file_cmd, check_output=False)
            
            if "No such file or directory" in file_check_result:
                # 创建空文件并设置权限
                perm_cmd = f"touch {target_file_path} && chmod 777 {target_file_path}"
            else:
                # 文件存在，直接修改权限
                perm_cmd = f"chmod 777 {target_file_path}"
            self.execute_ssh_command_with_sudo(perm_cmd)
            
            # 使用SFTP上传文件（支持断点续传）
            self.root.after(0, self.update_progress, 50)
            sftp = self.ssh.open_sftp()
            
            # 先上传到临时目录 - 支持断点续传
            self.root.after(0, self.update_progress, 60)
            
            try:
                # 检查远程临时文件是否存在
                remote_file_size = 0
                try:
                    remote_stat = sftp.stat(tmp_path)
                    remote_file_size = remote_stat.st_size
                except FileNotFoundError:
                    # 文件不存在，从头开始上传
                    pass
                
                # 获取本地文件大小
                local_file_size = os.path.getsize(local_file_path)
                
                # 如果远程文件大小小于本地文件大小，尝试断点续传
                if remote_file_size < local_file_size:
                    self.root.after(0, lambda: self.log(f"发现部分上传的文件，尝试断点续传: {target_file_name}"))
                    # 设置断点续传标志
                    self.root.after(0, lambda: setattr(self, 'is_resuming', True))
                    self.root.after(0, lambda: setattr(self, 'resume_file', target_file_name))
                    
                    # 使用自定义的断点续传上传方法
                    def upload_with_resume(local_path, remote_path, already_uploaded):
                        # 打开本地文件，从已上传的位置继续读取
                        with open(local_path, 'rb') as local_file:
                            local_file.seek(already_uploaded)
                            
                            # 打开远程文件，使用append模式
                            with sftp.file(remote_path, 'ab') as remote_file:
                                # 分块上传
                                block_size = 32768  # 32KB
                                total_blocks = (local_file_size - already_uploaded) // block_size + 1
                                current_block = 0
                                
                                while True:
                                    data = local_file.read(block_size)
                                    if not data:
                                        break
                                    
                                    remote_file.write(data)
                                    current_block += 1
                                    
                                    # 更新进度
                                    upload_progress = 60 + ((current_block / total_blocks) * 10)
                                    self.root.after(0, self.update_progress, upload_progress)
                        # 上传完成后清除断点续传标志
                        self.root.after(0, lambda: setattr(self, 'is_resuming', False))
                        self.root.after(0, lambda: setattr(self, 'resume_file', ""))
                
                # 调用断点续传上传方法
                upload_with_resume(local_file_path, tmp_path, remote_file_size)
                
            except Exception as e:
                # 如果断点续传失败，回退到完整上传
                self.root.after(0, lambda err=str(e): self.log(f"断点续传失败，尝试完整上传: {err}"))
                sftp.put(local_file_path, tmp_path)
            self.root.after(0, self.update_progress, 70)
            sftp.close()
            
            # 复制到目标位置
            self.root.after(0, self.update_progress, 80)
            copy_cmd = f"cp {tmp_path} {target_file_path}"
            self.execute_ssh_command_with_sudo(copy_cmd)
            
            # 创建目标目录并移动临时文件到/home/mmdvm/hb1/目录
            self.root.after(0, self.update_progress, 90)
            # 先创建目录（如果不存在）
            mkdir_cmd = "mkdir -p /home/mmdvm/hb1"
            self.execute_ssh_command_with_sudo(mkdir_cmd, check_output=False)
            # 移动文件
            move_cmd = f"mv {tmp_path} /home/mmdvm/hb1/"
            self.execute_ssh_command_with_sudo(move_cmd, check_output=False)
            
            # 更新后设置文件为不可修改
            self.root.after(0, self.update_progress, 95)
            chattr_lock_cmd = f"chattr +i {target_file_path}"
            self.execute_ssh_command_with_sudo(chattr_lock_cmd)
            
            # 完成
            self.root.after(0, self.update_progress, 100)
            # 清除当前文件名
            self.current_file = ""
            return True
            
        except Exception as e:
            self.root.after(0, lambda err=str(e): messagebox.showerror("失败", f"导入文件失败:\n{err}"))
            return False
            
    def perform_import_hosts(self, is_dmr_hosts=True, custom_file_path=None):
        """执行导入DMR_Hosts.txt或APRSHosts.txt文件的操作，返回是否成功"""
        try:
            # 根据参数确定文件类型
            import os
            if is_dmr_hosts:
                file_name = "DMR_Hosts.txt"
                remote_file_path = "/usr/local/etc/DMR_Hosts.txt"
            else:
                file_name = "APRSHosts.txt"
                remote_file_path = "/usr/local/etc/APRSHosts.txt"
            
            # 设置当前文件名
            self.current_file = file_name
            
            # 使用自定义文件路径或获取用户选择的路径
            if custom_file_path:
                local_file_path = custom_file_path
            else:
                # 这部分逻辑保留以兼容可能的直接调用
                from tkinter import filedialog
                file_types = [("文本文件", "*.txt"), ("所有文件", "*.*")]
                title = f"选择{file_name}文件"
                
                local_file_path = filedialog.askopenfilename(
                    title=title,
                    filetypes=file_types,
                    defaultextension=".txt"
                )
                
                if not local_file_path:
                    return False
            
            tmp_path = f"/tmp/{file_name}"
            
            # 检查文件是否存在
            if not os.path.exists(local_file_path):
                self.root.after(0, lambda: messagebox.showerror("错误", f"找不到{file_name}文件:\n{local_file_path}"))
                return False
            
            # 显示进度
            self.root.after(0, self.update_progress, 10)
            
            # 检查远程文件是否存在以及版本是否相同
            file_already_up_to_date = False
            try:
                # 获取本地文件信息
                local_stat = os.stat(local_file_path)
                local_modified_time = local_stat.st_mtime
                local_file_size = local_stat.st_size
                
                # 检查远程文件是否存在
                remote_stat_cmd = f"stat -c '%Y %s' {remote_file_path} 2>/dev/null"
                remote_stat_result = self.execute_ssh_command(remote_stat_cmd, check_output=False)
                
                if remote_stat_result.strip():
                    # 解析远程文件信息
                    remote_modified_time_str, remote_file_size_str = remote_stat_result.strip().split()
                    remote_modified_time = float(remote_modified_time_str)
                    remote_file_size = int(remote_file_size_str)
                    
                    # 比较版本信息（修改时间和文件大小）
                    time_diff = abs(local_modified_time - remote_modified_time)
                    if time_diff < 5 and local_file_size == remote_file_size:
                        file_already_up_to_date = True
                        self.root.after(0, lambda: messagebox.showinfo("提示", f"{file_name}文件版本已经是最新的，无需更新。"))
            except Exception:
                # 如果获取远程文件信息失败（比如文件不存在），则继续执行导入
                pass
            
            # 如果文件版本相同，则停止更新
            if file_already_up_to_date:
                self.root.after(0, self.update_progress, 100)
                return True
            
            # 执行文件系统可写挂载 - 修复：使用安全的sudo命令执行方式
            self.root.after(0, self.update_progress, 20)
            remount_cmd = "mount -o remount,rw /"
            self.execute_ssh_command_with_sudo(remount_cmd)
            
            # 移除不可修改属性 - 修复：使用安全的sudo命令执行方式
            self.root.after(0, self.update_progress, 30)
            chattr_unlock_cmd = f"chattr -i {remote_file_path}"
            self.execute_ssh_command_with_sudo(chattr_unlock_cmd, check_output=False)
            
            # 设置文件权限 - 修复：使用安全的sudo命令执行方式
            self.root.after(0, self.update_progress, 40)
            perm_cmd = f"chmod 777 {remote_file_path}"
            self.execute_ssh_command_with_sudo(perm_cmd, check_output=False)
            
            # 使用SFTP上传文件（支持断点续传）
            self.root.after(0, self.update_progress, 50)
            sftp = self.ssh.open_sftp()
            
            # 先上传到临时目录 - 支持断点续传
            self.root.after(0, self.update_progress, 60)
            
            try:
                # 检查远程临时文件是否存在
                remote_file_size = 0
                try:
                    remote_stat = sftp.stat(tmp_path)
                    remote_file_size = remote_stat.st_size
                except FileNotFoundError:
                    # 文件不存在，从头开始上传
                    pass
                
                # 获取本地文件大小
                local_file_size = os.path.getsize(local_file_path)
                
                # 如果远程文件大小小于本地文件大小，尝试断点续传
                if remote_file_size < local_file_size:
                    self.root.after(0, lambda: self.log(f"发现部分上传的文件，尝试断点续传: {file_name}"))
                    # 设置断点续传标志
                    self.root.after(0, lambda: setattr(self, 'is_resuming', True))
                    self.root.after(0, lambda: setattr(self, 'resume_file', file_name))
                    
                    # 使用自定义的断点续传上传方法
                    def upload_with_resume(local_path, remote_path, already_uploaded):
                        # 打开本地文件，从已上传的位置继续读取
                        with open(local_path, 'rb') as local_file:
                            local_file.seek(already_uploaded)
                            
                            # 打开远程文件，使用append模式
                            with sftp.file(remote_path, 'ab') as remote_file:
                                # 分块上传
                                block_size = 32768  # 32KB
                                total_blocks = (local_file_size - already_uploaded) // block_size + 1
                                current_block = 0
                                
                                while True:
                                    data = local_file.read(block_size)
                                    if not data:
                                        break
                                    
                                    remote_file.write(data)
                                    current_block += 1
                                    
                                    # 更新进度
                                    upload_progress = 60 + ((current_block / total_blocks) * 10)
                                    self.root.after(0, self.update_progress, upload_progress)
                        # 上传完成后清除断点续传标志
                        self.root.after(0, lambda: setattr(self, 'is_resuming', False))
                        self.root.after(0, lambda: setattr(self, 'resume_file', ""))
                
                # 调用断点续传上传方法
                upload_with_resume(local_file_path, tmp_path, remote_file_size)
                
            except Exception as e:
                # 如果断点续传失败，回退到完整上传
                self.root.after(0, lambda err=str(e): self.log(f"断点续传失败，尝试完整上传: {err}"))
                sftp.put(local_file_path, tmp_path)
            self.root.after(0, self.update_progress, 70)
            sftp.close()
            
            # 复制到目标位置 - 修复：使用安全的sudo命令执行方式
            self.root.after(0, self.update_progress, 80)
            copy_cmd = f"cp {tmp_path} {remote_file_path}"
            self.execute_ssh_command_with_sudo(copy_cmd)
            
            # 创建目标目录并移动临时文件到/home/mmdvm/hb1/目录
            self.root.after(0, self.update_progress, 90)
            # 先创建目录（如果不存在）
            mkdir_cmd = "mkdir -p /home/mmdvm/hb1"
            self.execute_ssh_command_with_sudo(mkdir_cmd, check_output=False)
            # 移动文件
            move_cmd = f"mv {tmp_path} /home/mmdvm/hb1/"
            self.execute_ssh_command_with_sudo(move_cmd, check_output=False)
            
            # 更新后设置文件为不可修改 - 修复：使用安全的sudo命令执行方式
            self.root.after(0, self.update_progress, 95)
            chattr_lock_cmd = f"chattr +i {remote_file_path}"
            self.execute_ssh_command_with_sudo(chattr_lock_cmd)
            
            # 完成
            self.root.after(0, self.update_progress, 100)
            # 清除当前文件名
            self.current_file = ""
            return True
            
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.import_hosts_failed(err, is_dmr_hosts))
            return False
    
    def update_all_data(self):
        """国服数据下载功能"""
        if not self.ssh or not self.connected_ip:
            messagebox.showerror("错误", "请先登录设备")
            return
        
        # 立即创建/home/mmdvm/hb1目录（无论之前是否存在）
        try:
            create_dir_cmd = "mkdir -p /home/mmdvm/hb1"
            self.execute_ssh_command_with_sudo(create_dir_cmd, check_output=False)
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.log(f"创建目录/home/mmdvm/hb1时出错: {err}"))
        
        self.update_button.config(state="disabled", text="更新盒子")
        self.progress_var.set(0)
        
        # 在新线程中执行更新操作
        update_thread = threading.Thread(target=self.perform_all_updates)
        update_thread.daemon = True
        update_thread.start()
        
    def perform_all_updates(self):
        """执行国服数据更新：将本地 up 目录的数据文件通过 SFTP 上传到设备"""
        try:
            self.root.after(0, self.update_progress, 0)

            # 创建 hb1 目录（兼容盒子原有结构）
            self.execute_ssh_command_with_sudo("mkdir -p /home/mmdvm/hb1", check_output=False)

            # 本地 up 目录中的数据文件上传到盒子（文件由登录后自动下载或用户编辑后产生）
            file_specs = [(file_info["name"], file_info["target"])
                          for file_info in self.files_to_update]
            self.upload_up_files_to_box(file_specs)

            # 所有文件更新完成，清除当前文件名
            self.current_file = ""
            
            try:
                # 导入up文件夹下的DMR_Hosts.txt和APRSHosts.txt文件到/usr/local/etc目录
                self.root.after(0, lambda: self.log("🔄 开始导入主机文件到/usr/local/etc目录"))
                
                # 定义要导入的主机文件
                host_files_to_import = [
                    {"name": "DMR_Hosts.txt", "local_path": os.path.join(self._get_up_dir(), "DMR_Hosts.txt"), "remote_path": "/usr/local/etc/DMR_Hosts.txt"},
                    {"name": "APRSHosts.txt", "local_path": os.path.join(self._get_up_dir(), "APRSHosts.txt"), "remote_path": "/usr/local/etc/APRSHosts.txt"}
                ]
                
                # 执行导入
                for host_file in host_files_to_import:
                    local_file_path = host_file["local_path"]
                    remote_file_path = host_file["remote_path"]
                    file_name = host_file["name"]
                    
                    if os.path.exists(local_file_path):
                        self.root.after(0, lambda fn=file_name: self.log(f"📤 正在导入{fn}到远程设备"))
                        
                        # 设置当前文件名
                        self.current_file = file_name
                        
                        # 执行文件系统可写挂载
                        remount_cmd = "mount -o remount,rw /"
                        self.execute_ssh_command_with_sudo(remount_cmd)
                        
                        # 移除不可修改属性
                        chattr_unlock_cmd = f"chattr -i {remote_file_path}"
                        self.execute_ssh_command_with_sudo(chattr_unlock_cmd, check_output=False)
                        
                        # 设置文件权限
                        perm_cmd = f"chmod 777 {remote_file_path}"
                        self.execute_ssh_command_with_sudo(perm_cmd, check_output=False)
                        
                        # 使用SFTP上传文件
                        sftp = self.ssh.open_sftp()
                        tmp_path = f"/tmp/{file_name}"
                        sftp.put(local_file_path, tmp_path)
                        sftp.close()
                        
                        # 复制到目标位置
                        copy_cmd = f"cp {tmp_path} {remote_file_path}"
                        self.execute_ssh_command_with_sudo(copy_cmd)
                        
                        # 创建目标目录并移动临时文件到/home/mmdvm/hb1/目录
                        mkdir_cmd = "mkdir -p /home/mmdvm/hb1"
                        self.execute_ssh_command_with_sudo(mkdir_cmd, check_output=False)
                        move_cmd = f"mv {tmp_path} /home/mmdvm/hb1/"
                        self.execute_ssh_command_with_sudo(move_cmd, check_output=False)
                        
                        self.root.after(0, lambda fn=file_name: self.log(f"✅ {fn}导入成功"))
                    else:
                        self.root.after(0, lambda fn=file_name: self.log(f"⚠️ 警告: 未找到{fn}文件，跳过导入"))
                
                # 为所有五个文件(DMRIds.dat, user.csv, NXDN.csv, DMR_Hosts.txt, APRSHosts.txt)设置统一的权限和不可修改属性
                self.root.after(0, lambda: self.log("🔒 为所有文件设置统一权限和不可修改属性"))
                
                # 获取所有需要设置权限的文件列表
                all_files_to_set_permissions = self.files_to_unlock.copy()
                all_files_to_set_permissions.extend([
                    "/usr/local/etc/DMR_Hosts.txt",
                    "/usr/local/etc/APRSHosts.txt"
                ])
                
                # 设置统一权限(755)和不可修改属性
                for file_path in all_files_to_set_permissions:
                    # 设置权限为755
                    perm_cmd = f"chmod 755 {file_path}"
                    self.execute_ssh_command_with_sudo(perm_cmd, check_output=False)
                    
                    # 设置不可修改属性
                    chattr_lock_cmd = f"chattr +i {file_path}"
                    self.execute_ssh_command_with_sudo(chattr_lock_cmd)
                
                self.root.after(0, lambda: self.log("✅ 所有文件权限设置完成"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"❌ 导入主机文件或设置权限时出错: {err}"))

            # 数据上传完成（本地 up 目录本身就是数据来源，无需再从盒子回传）
            self.root.after(0, lambda: self.bm_download_button.config(state="normal"))
            # 更新 up 目录相关按钮状态
            self.root.after(0, self.update_up_dependent_buttons)
            # 询问是否重启设备
            self.root.after(0, self.ask_restart_device)
            
        except Exception as e:
            self.root.after(0, self.update_failed, str(e))

    def ask_restart_device(self):
        """询问用户是否重启MMDVM设备⑤"""
        restart = messagebox.askyesno(
            "重启设备",
            "所有数据文件更新完成！\n是否需要重启MMDVM设备以使更改生效？\n重启过程中设备将暂时无法使用。"
        )
        
        if restart:
            self.root.after(0, self.restart_mmdvm_device)
        else:
            self.update_button.config(state="normal")
            messagebox.showinfo("完成", "数据更新已完成，部分更改可能需要重启设备后生效")
        
    def restart_mmdvm_device(self):
        """重启MMDVM设备"""
        try:
            self.progress_var.set(0)
            
            # 执行重启命令 - 修复：使用安全的sudo命令执行方式
            restart_cmd = "systemctl restart mmdvmhost"
            # 忽略未使用的返回值，因为我们不需要检查输出
            self.execute_ssh_command_with_sudo(restart_cmd, check_output=False)
            
            # 等待重启完成
            for i in range(100):
                self.root.after(0, self.update_progress, i)
                time.sleep(0.1)
            
            self.update_button.config(state="normal")
            self.progress_var.set(100)
            messagebox.showinfo("成功", "设备重启命令已执行完成，设备可能需要几分钟才能完全启动并恢复连接")
            
        except Exception as e:
            self.update_button.config(state="normal")
            messagebox.showerror("错误", f"重启设备失败: {str(e)}")
        finally:
            # 重启后关闭SSH连接
            if self.ssh:
                try:
                    self.ssh.close()
                except Exception:
                    pass  # 忽略关闭SSH连接时的错误
            self.ssh = None
            self.login_status.config(text="设备已重启，连接已断开", foreground="orange")
        
    def execute_ssh_command(self, command, check_output=True):
        """执行SSH命令"""
        stdin, stdout, stderr = self.ssh.exec_command(command)
        
        # 等待命令执行完成
        exit_status = stdout.channel.recv_exit_status()
        
        # 读取输出
        output = stdout.read().decode()
        error = stderr.read().decode()
        
        if exit_status != 0 and check_output:
            # 替换错误信息中的域名链接、纯域名和IP地址为"服务器"
            import re
            # 匹配HTTP/HTTPS URL
            modified_error = re.sub(r'https?://[^\s]+', '服务器', error)
            modified_command = re.sub(r'https?://[^\s]+', '服务器', command)
            # 匹配纯域名(如example.com)
            modified_error = re.sub(r'([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+\.?)', '服务器', modified_error)
            modified_command = re.sub(r'([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+\.?)', '服务器', modified_command)
            # 匹配IP地址
            modified_error = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '服务器', modified_error)
            modified_command = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '服务器', modified_command)
            raise Exception(f"命令执行失败: {modified_command}\n错误信息: {modified_error}")
        
        return output + error
        
    def execute_ssh_command_with_sudo(self, command, check_output=True):
        """执行带sudo权限的SSH命令 - 安全的密码传递方式"""
        # 获取密码
        password = self.pass_entry.get()
        
        # 使用Paramiko的交互式方式执行sudo命令，而不是在命令行中明文传递密码
        stdin, stdout, stderr = self.ssh.exec_command(f"sudo -S {command}")
        
        # 通过标准输入发送密码，而不是在命令行中显示
        stdin.write(password + "\n")
        stdin.flush()
        
        # 等待命令执行完成
        exit_status = stdout.channel.recv_exit_status()
        
        # 读取输出
        output = stdout.read().decode()
        error = stderr.read().decode()
        
        if exit_status != 0 and check_output:
            # 替换错误信息中的域名链接为"服务器"
            import re
            modified_error = re.sub(r'https?://[^\s]+', '服务器', error)
            modified_command = re.sub(r'https?://[^\s]+', '服务器', command)
            raise Exception(f"命令执行失败: {modified_command}\n错误信息: {modified_error}")
        
        return output + error
        
    def ask_clear_remote_dirs(self):
        """询问用户是否清空远程的hb1和hb2目录"""
        if not self.ssh or not self.connected_ip:
            return
        
        # 询问用户是否清空目录
        response = messagebox.askyesno(
            "清空目录确认",
            "双服数据合并已完成！\n\n是否要清空远程设备上的\n/home/mmdvm/hb1/ 和 /home/mmdvm/hb2/ 目录？\n\n注意：此操作将删除这些目录中的所有文件，但不会删除目录本身。"
        )
        
        if response:
            # 在新线程中执行清空操作，避免UI卡顿
            clear_thread = threading.Thread(target=self._perform_clear_remote_dirs)
            clear_thread.daemon = True
            clear_thread.start()
    
    def _perform_clear_remote_dirs(self):
        """执行清空远程hb1和hb2目录的操作"""
        try:
            remote_hb1_dir = '/home/mmdvm/hb1/'
            remote_hb2_dir = '/home/mmdvm/hb2/'
            
            # 执行清空命令 - 使用sudo权限
            self.root.after(0, lambda: self.log("正在清空远程hb1目录..."))
            clear_hb1_cmd = f"rm -rf {remote_hb1_dir}/* 2>/dev/null"
            self.execute_ssh_command_with_sudo(clear_hb1_cmd, check_output=False)
            
            self.root.after(0, lambda: self.log("正在清空远程hb2目录..."))
            clear_hb2_cmd = f"rm -rf {remote_hb2_dir}/* 2>/dev/null"
            self.execute_ssh_command_with_sudo(clear_hb2_cmd, check_output=False)
            
            # 清空完成
            self.root.after(0, lambda: self.log("✅ 远程hb1和hb2目录已成功清空"))
            
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.log(f"清空远程目录时出错: {err}"))
            self.root.after(0, lambda err=str(e): messagebox.showerror("错误", f"清空远程目录失败:\n{err}"))
    
    def update_progress(self, value):
        """更新进度条和百分比显示"""
        self.progress_var.set(value)
        # 更新百分比标签，精确到小数点后两位
        if hasattr(self, 'current_file') and self.current_file:
            if self.is_resuming:
                self.progress_label.config(
                    text=f"{self.current_file} {value:.2f}% 断点续传"
                )
            else:
                self.progress_label.config(
                    text=f"{self.current_file} {value:.2f}%"
                )
        else:
            if self.is_resuming and self.resume_file:
                self.progress_label.config(
                    text=f"{self.resume_file} {value:.2f}% 断点续传"
                )
            else:
                self.progress_label.config(text=f"{value:.2f}%")
    
    def convert_contacts(self):
        """联系人转换功能⑦"""
        try:
            # 每次打开时都重新初始化品牌数据库，确保临时模板的删除能立即反映
            self.brand_db = BrandDatabase(enable_translation=True)
            
            # 获取所有可用品牌（中文名称用于显示）
            display_brands = self.brand_db.get_all_brands(translate=True)
            # 获取原始品牌名称（英文）用于实际转换
            original_brands = self.brand_db.get_all_brands(translate=False)
            
            if not display_brands or not original_brands:
                messagebox.showerror("错误", "未找到可用的品牌模板")
                return
            
            # 创建转换对话框，传递显示品牌和原始品牌
            self.create_contact_conversion_dialog(display_brands, original_brands)
            
        except Exception as e:
            messagebox.showerror("错误", f"初始化联系人工具失败: {str(e)}")

    def _get_up_dir(self):
        """获取软件目录下 up 文件夹的绝对路径（兼容脚本运行和打包 exe 运行）"""
        if getattr(sys, 'frozen', False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, "up")

    def _resolve_user_csv_path(self):
        """获取 up/user.csv 的绝对路径（兼容脚本运行和打包 exe 运行）"""
        return os.path.join(self._get_up_dir(), "user.csv")

    def edit_user_csv(self):
        """打开 user.csv 编辑窗口：输入呼号自动带出姓名/QTH，修改后提交写回文件"""
        import shutil
        import pandas as pd

        csv_path = self._resolve_user_csv_path()
        if not os.path.exists(csv_path):
            messagebox.showerror("错误", "未找到 up/user.csv，请先下载数据")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("编辑 user.csv 联系人")
        dlg.geometry("470x470")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        self.center_window(dlg)

        frm = ttk.Frame(dlg, padding=15)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(1, weight=1)

        # 第一行：呼号/ID 查询
        ttk.Label(frm, text="输入呼号/ID:").grid(row=0, column=0, sticky="w", pady=6)
        search_var = tk.StringVar()
        search_entry = ttk.Entry(frm, textvariable=search_var, width=20)
        search_entry.grid(row=0, column=1, sticky="w", pady=6, padx=(4, 6))
        search_entry.focus_set()

        # 字段：(列名, 显示标签, 是否可编辑)
        field_defs = [
            ("RADIO_ID", "ID", False),
            ("CALLSIGN", "呼号", False),
            ("NAME", "姓名", True),
            ("CITY", "QTH 城市", True),
            ("STATE", "省份", True),
            ("COUNTRY", "国家", True),
            ("REMARKS", "备注", True),
        ]
        entries = {}
        for i, (col, label, editable) in enumerate(field_defs, start=1):
            ttk.Label(frm, text=label + ":").grid(row=i, column=0, sticky="w", pady=3)
            ent = ttk.Entry(frm, width=34)
            ent.grid(row=i, column=1, columnspan=2, sticky="ew", pady=3, padx=(4, 0))
            if not editable:
                ent.config(state="readonly")
            entries[col] = ent

        # 同一呼号可能有多条记录，提供切换
        nav_frame = ttk.Frame(frm)
        nav_frame.grid(row=8, column=0, columnspan=3, pady=(8, 2))
        prev_btn = ttk.Button(nav_frame, text="上一条", state="disabled")
        prev_btn.pack(side="left", padx=5)
        next_btn = ttk.Button(nav_frame, text="下一条", state="disabled")
        next_btn.pack(side="left", padx=5)
        nav_label = ttk.Label(nav_frame, text="", foreground="blue")
        nav_label.pack(side="left", padx=8)

        # 批量修改开关：一个呼号对应多个 ID 时，一次应用到全部记录
        apply_all_var = tk.BooleanVar(value=False)
        apply_all_check = ttk.Checkbutton(
            frm, text="同时修改该呼号的全部记录（姓名/QTH 等应用到所有匹配 ID）", variable=apply_all_var
        )
        apply_all_check.grid(row=9, column=0, columnspan=3, sticky="w", pady=(6, 0))
        apply_all_check.state(["disabled"])

        status_var = tk.StringVar()
        status_label = ttk.Label(frm, textvariable=status_var, foreground="green")
        status_label.grid(row=10, column=0, columnspan=3, pady=4)

        state = {"df": None, "matches": [], "pos": 0, "backed_up": False}
        required_cols = ["RADIO_ID", "CALLSIGN", "NAME", "CITY", "STATE", "COUNTRY", "REMARKS"]

        def clear_form():
            for col, ent in entries.items():
                ent.config(state="normal")
                ent.delete(0, tk.END)
                if col in ("RADIO_ID", "CALLSIGN"):
                    ent.config(state="readonly")
            nav_label.config(text="")
            prev_btn.config(state="disabled")
            next_btn.config(state="disabled")
            apply_all_var.set(False)
            apply_all_check.state(["disabled"])

        def populate():
            idx = state["matches"][state["pos"]]
            row = state["df"].loc[idx]
            for col, ent in entries.items():
                ent.config(state="normal")
                ent.delete(0, tk.END)
                ent.insert(0, str(row.get(col, "")))
                if col in ("RADIO_ID", "CALLSIGN"):
                    ent.config(state="readonly")
            total = len(state["matches"])
            nav_label.config(text=f"第 {state['pos'] + 1}/{total} 条" if total > 1 else "")
            prev_btn.config(state="normal" if state["pos"] > 0 else "disabled")
            next_btn.config(state="normal" if state["pos"] < total - 1 else "disabled")
            if total > 1:
                apply_all_check.state(["!disabled"])
            else:
                apply_all_var.set(False)
                apply_all_check.state(["disabled"])
            status_var.set("")

        def do_search(event=None):
            key = search_var.get().strip()
            if not key:
                return
            try:
                df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            except Exception as ex:
                messagebox.showerror("错误", f"读取 user.csv 失败:\n{ex}", parent=dlg)
                return
            df.columns = [str(c).lstrip("\ufeff").strip() for c in df.columns]
            for col in required_cols:
                if col not in df.columns:
                    df[col] = ""

            calls = df["CALLSIGN"].astype(str).str.strip()
            ids = df["RADIO_ID"].astype(str).str.strip()
            key_up = key.upper()
            mask = calls.str.upper() == key_up
            if not mask.any() and key.isdigit():
                mask = ids == key
            if not mask.any():
                # 精确匹配不到时，退化为包含匹配
                mask = calls.str.upper().str.contains(re.escape(key_up), na=False)

            matches = df.index[mask].tolist()
            if not matches:
                state.update(df=None, matches=[], pos=0)
                clear_form()
                status_label.config(foreground="red")
                status_var.set(f"未找到呼号/ID：{key}")
                return
            status_label.config(foreground="green")
            state["df"] = df
            state["matches"] = matches
            state["pos"] = 0
            populate()

        def go(delta):
            if not state["matches"]:
                return
            new_pos = state["pos"] + delta
            if 0 <= new_pos < len(state["matches"]):
                state["pos"] = new_pos
                populate()

        def do_save():
            if state["df"] is None or not state["matches"]:
                messagebox.showwarning("提示", "请先输入呼号查询到记录", parent=dlg)
                return

            new_values = {col: entries[col].get().strip()
                          for col in ("NAME", "CITY", "STATE", "COUNTRY", "REMARKS")}
            apply_all = apply_all_var.get() and len(state["matches"]) > 1
            target_indexes = state["matches"] if apply_all else [state["matches"][state["pos"]]]

            if apply_all:
                ok = messagebox.askyesno(
                    "确认批量修改",
                    f"将把姓名/QTH 等信息应用到该呼号的全部 {len(target_indexes)} 条记录，是否继续？",
                    parent=dlg)
                if not ok:
                    return

            for idx in target_indexes:
                for col, val in new_values.items():
                    state["df"].at[idx, col] = val
            try:
                if not state["backed_up"]:
                    shutil.copy2(csv_path, csv_path + ".bak")
                    state["backed_up"] = True
                state["df"].to_csv(csv_path, index=False, encoding="utf-8")
            except Exception as ex:
                messagebox.showerror("错误", f"保存失败:\n{ex}", parent=dlg)
                return
            status_label.config(foreground="green")
            callsign = entries["CALLSIGN"].get()
            if apply_all:
                status_var.set(f"已批量保存：{callsign} 共 {len(target_indexes)} 条（原文件已备份为 user.csv.bak）")
            else:
                status_var.set(f"已保存：{callsign}（原文件已备份为 user.csv.bak）")

        # 查询 / 切换 / 保存 / 关闭
        query_btn = ttk.Button(frm, text="查询", command=do_search)
        query_btn.grid(row=0, column=2, sticky="e", pady=6)
        prev_btn.config(command=lambda: go(-1))
        next_btn.config(command=lambda: go(1))
        search_entry.bind("<Return>", do_search)

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=11, column=0, columnspan=3, pady=(8, 0))
        ttk.Button(btn_frame, text="提交修改", command=do_save).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="关闭", command=dlg.destroy).pack(side="left", padx=8)
    
    def create_contact_conversion_dialog(self, display_brands, original_brands):
        """创建联系人转换对话框"""
        # 创建顶层窗口
        dialog = tk.Toplevel(self.root)
        dialog.title("联系人工具")
        dialog.geometry("500x300")  # 调整高度以适应新布局
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 将对话框固定在程序窗口中心
        self.center_window(dialog)
        
        # 主框架
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 源文件信息显示（固定使用 up/user.csv）
        ttk.Label(main_frame, text="源联系人文件:").grid(row=0, column=0, sticky="w", pady=5)
        source_file_path = os.path.join("up", "user.csv")
        source_file_label = ttk.Label(main_frame, text="up/user.csv", foreground="blue")
        source_file_label.grid(row=0, column=1, sticky="w", pady=5, padx=(10, 0))

        # 检查文件是否存在，并设置转换按钮状态
        source_file_exists = os.path.exists(source_file_path)
        if not source_file_exists:
            source_file_label.config(text="up/user.csv (文件不存在)", foreground="red")
        
        # 目标品牌选择
        ttk.Label(main_frame, text="目标品牌:").grid(row=1, column=0, sticky="w", pady=5)
        self.target_brand_var = tk.StringVar()
        self.brand_combo = ttk.Combobox(main_frame, textvariable=self.target_brand_var, values=display_brands, width=38)
        self.brand_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 10))
        
        # 存储品牌映射关系
        self.brand_mapping = dict(zip(display_brands, original_brands))
        
        # 输出文件选择
        ttk.Label(main_frame, text="输出文件:").grid(row=2, column=0, sticky="w", pady=5)
        self.output_file_var = tk.StringVar()
        self.output_file_entry = ttk.Entry(main_frame, textvariable=self.output_file_var, width=40)
        self.output_file_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 5))
        
        # 中文区复选框
        self.chinese_region_var = tk.BooleanVar(value=False)
        chinese_region_checkbox = ttk.Checkbutton(
            main_frame,
            text="中文区（只导出454、455、46、86开头的呼号）",
            variable=self.chinese_region_var,
            onvalue=True,
            offvalue=False
        )
        chinese_region_checkbox.grid(row=3, column=0, columnspan=3, sticky="w", pady=5)
        
        # 翻译开关复选框
        self.translation_var = tk.BooleanVar(value=True)  # 默认启用翻译
        translation_checkbox = ttk.Checkbutton(
            main_frame,
            text="启用地理信息翻译（将英文国家/城市/省份翻译为中文）",
            variable=self.translation_var,
            onvalue=True,
            offvalue=False
        )
        translation_checkbox.grid(row=4, column=0, columnspan=2, sticky="w", pady=5)
        
        # 转换按钮 - 根据源文件存在状态设置
        convert_button = ttk.Button(main_frame, text="开始转换", command=self.perform_contact_conversion)
        convert_button.grid(row=4, column=2, sticky="e", pady=5)
        
        # 如果源文件不存在，禁用转换按钮
        if not source_file_exists:
            convert_button.config(state="disabled")
        
        # 状态显示
        self.conversion_status = ttk.Label(main_frame, text="")
        self.conversion_status.grid(row=5, column=0, columnspan=3, pady=5)
        
        # 添加说明文字
        instruction_text = "如果列表里没有您的设备，请将您设备数字联系人的模板文件保存到CSV目录，就可以生成适合您设备的联系人文件。"
        instruction_label = ttk.Label(
            main_frame, 
            text=instruction_text,
            wraplength=460,
            justify="left",
            foreground="#666666",
            font=("SimHei", 9)
        )
        instruction_label.grid(row=6, column=0, columnspan=3, pady=(10, 5), sticky="w")
        
        # 配置列权重
        main_frame.columnconfigure(1, weight=1)
        
        # 设置默认输出文件名（空，将在选择品牌时自动生成）
        self.output_file_var.set("")
        
        # 绑定品牌选择事件，自动生成文件名
        def on_brand_selected(event):
            selected_brand = self.target_brand_var.get()
            if selected_brand and selected_brand in self.brand_mapping:
                original_brand = self.brand_mapping[selected_brand]
                # 修改输出文件路径到CSV\OUT目录
                output_file = os.path.join("CSV", "OUT", f"{original_brand}_converted.csv")
                self.output_file_var.set(output_file)
        
        self.brand_combo.bind("<<ComboboxSelected>>", on_brand_selected)

        # 添加合并数据下载按钮（只在 GUI 中显示“服务器”，不暴露真实链接）
        def on_bm_download_clicked():
            # 在新线程中执行下载，避免阻塞UI
            threading.Thread(target=self._download_bm_user_to_up_thread, daemon=True).start()

        bm_frame = ttk.Frame(main_frame)
        bm_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        bm_label = ttk.Label(bm_frame, text="合并数据来源:")
        bm_label.pack(side="left")
        bm_source_label = ttk.Label(bm_frame, text="感谢 BH5HWP提供服务器", foreground="blue")
        bm_source_label.pack(side="left", padx=(6, 12))

        self.bm_download_local_button = ttk.Button(bm_frame, text="下载合并数据", command=on_bm_download_clicked)
        self.bm_download_local_button.pack(side="left")
    


    def _download_bm_user_to_up_thread(self):
        """后台线程：从服务器下载 user.csv 到本地 up/user.csv（不在 UI 中暴露真实链接）。"""
        try:
            # 禁用按钮以防重复点击
            try:
                self.root.after(0, lambda: self.bm_download_local_button.config(state='disabled'))
            except Exception:
                pass

            # 计算 up 目录
            if getattr(sys, 'frozen', False):
                script_dir = os.path.dirname(sys.executable)
            else:
                script_dir = os.path.dirname(os.path.abspath(__file__))
            up_dir = os.path.join(script_dir, 'up')
            os.makedirs(up_dir, exist_ok=True)

            dest_path = os.path.join(up_dir, 'user.csv')
            tmp_path = dest_path + '.part'

            # 为避免在界面中暴露真实下载地址，UI 只显示“服务器”；真实地址仅在这里使用
            bm_url = 'http://downloads.zj130.com:9080/8601/j-star/update/user.csv'

            # 断点续传支持
            headers = {}
            mode = 'wb'
            downloaded = 0
            if os.path.exists(tmp_path):
                downloaded = os.path.getsize(tmp_path)
                headers['Range'] = f'bytes={downloaded}-'
                mode = 'ab'

            import requests
            with requests.get(bm_url, stream=True, headers=headers, timeout=60) as r:
                if r.status_code not in (200, 206):
                    # 不在 UI 中显示 URL，统一称为服务器
                    self.root.after(0, lambda: messagebox.showerror('下载失败', f"从 服务器 下载合并数据失败 (HTTP {r.status_code})"))
                    return

                with open(tmp_path, mode) as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)

            # 下载完成，重命名
            try:
                os.replace(tmp_path, dest_path)
            except Exception:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(tmp_path, dest_path)

            # 更新界面上的源文件存在提示
            self.root.after(0, lambda: messagebox.showinfo('成功', '合并数据已下载并保存到 up/user.csv'))
            # 更新联系人转换对话框的源文件标签（如果存在）
            self.root.after(0, lambda: self.update_up_dependent_buttons())

        except requests.exceptions.RequestException:
            self.root.after(0, lambda: messagebox.showerror('下载失败', '从 服务器 下载合并数据时网络错误'))
        except Exception as e:
            # 不在UI中泄露URL，错误信息中使用“服务器”替代
            err = str(e)
            self.root.after(0, lambda: messagebox.showerror('错误', f'合并数据下载失败: {err}'))
        finally:
            try:
                self.root.after(0, lambda: self.bm_download_local_button.config(state='normal'))
            except Exception:
                pass
    
    def perform_contact_conversion(self):
        """执行联系人转换"""
        display_brand = self.target_brand_var.get()
        output_file = self.output_file_var.get()
        chinese_region = self.chinese_region_var.get()
        enable_translation = self.translation_var.get()  # 获取翻译开关状态
        
        # 固定使用 up/user.csv 作为源文件
        source_file = os.path.join("up", "user.csv")
        
        if not display_brand:
            messagebox.showerror("错误", "请选择目标品牌")
            return
        
        # 检查源文件是否存在
        if not os.path.exists(source_file):
            messagebox.showerror("错误", f"源文件不存在: {source_file}\
请确保 up/user.csv 文件存在")
            return
        
        # 在新线程中执行转换操作，避免阻塞GUI
        conversion_thread = threading.Thread(
            target=self._perform_conversion_in_background,
            args=(display_brand, source_file, output_file, chinese_region, enable_translation),
            daemon=True
        )
        conversion_thread.start()
    
    def _perform_conversion_in_background(self, display_brand, source_file, output_file, chinese_region=False, enable_translation=True):
        """在后台线程中执行联系人转换"""
        try:
            # 延迟导入 pandas，只在真正需要时导入
            import pandas as pd

            # 更新状态
            self.root.after(0, lambda: self.conversion_status.config(text="正在转换..."))
            
            # 将显示的品牌名称转换为原始品牌名称
            if display_brand in self.brand_mapping:
                original_brand = self.brand_mapping[display_brand]
            else:
                original_brand = display_brand
            
            # 如果用户没有指定输出文件，自动生成文件名
            if not output_file:
                # 根据品牌生成输出文件名，保存到CSV\OUT目录
                if chinese_region:
                    output_file = os.path.join("CSV", "OUT", f"{original_brand}_中文区_converted.csv")
                else:
                    output_file = os.path.join("CSV", "OUT", f"{original_brand}_converted.csv")
                self.root.after(0, lambda: self.output_file_var.set(output_file))
            
            # 确保输出目录存在
            output_dir = os.path.dirname(output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # 读取源文件，尝试不同的编码格式
            encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'utf-16']
            source_df = None
            
            for encoding in encodings:
                try:
                    source_df = pd.read_csv(source_file, encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if source_df is None:
                # 如果所有编码都失败，使用错误处理模式读取
                source_df = pd.read_csv(source_file, encoding='utf-8', encoding_errors='replace')
            
            # 如果启用了中文区过滤，过滤RADIO_ID
            if chinese_region:
                # 查找RADIO_ID列
                radio_id_column = None
                for col in source_df.columns:
                    if isinstance(col, str) and col.lower() in ["radio_id", "radio id", "dmr id", "id"]:
                        radio_id_column = col
                        break
                
                if radio_id_column:
                    # 过滤中文区RADIO_ID（454、455、46、86开头）
                    def is_chinese_region_radio_id(radio_id):
                        if pd.isna(radio_id) or not str(radio_id).strip():
                            return False
                        radio_id_str = str(radio_id).strip()
                        # 检查是否以454、455、46、86开头
                        return (radio_id_str.startswith('454') or 
                                radio_id_str.startswith('455') or 
                                radio_id_str.startswith('46') or 
                                radio_id_str.startswith('86'))
                    
                    # 应用过滤
                    chinese_region_mask = source_df[radio_id_column].apply(is_chinese_region_radio_id)
                    source_df = source_df[chinese_region_mask]
                    
                    # 如果没有符合条件的记录，提示用户
                    if len(source_df) == 0:
                        self.root.after(0, lambda: self.conversion_status.config(text="转换完成（无中文区RADIO_ID）"))
                        self.root.after(0, lambda: messagebox.showinfo("完成", "未找到符合条件的中文区RADIO_ID（454、455、46、86开头）"))
                        self.root.after(0, self._close_conversion_dialog)
                        return
            
            # 在后台线程中创建新的BrandDatabase实例
            brand_db = BrandDatabase(enable_translation=enable_translation)
            
            # 使用品牌数据库进行转换（使用原始品牌名称）
            converted_df = brand_db.convert_data(original_brand, source_df)
            
            # 关闭数据库连接
            brand_db.close()
            
            if converted_df is None:
                raise Exception("转换失败：无法将数据转换为目标格式")
            
            # 保存转换后的文件
            if original_brand == "DM9100":
                # 清理GB18030不支持的字符
                cleaned_df = converted_df.copy()
                for col in cleaned_df.columns:
                    if cleaned_df[col].dtype == 'object':
                        cleaned_df[col] = cleaned_df[col].astype(str).str.replace('[^\x00-\xff]', '', regex=True)
                cleaned_df.to_csv(output_file, index=False, encoding='gb18030')
            elif original_brand == "AnyTone":
                # 自由通品牌使用ANSI编码（GBK），忽略无法转换的字符
                converted_df.to_csv(output_file, index=False, encoding='gbk', errors='ignore')
            elif original_brand == "如意通6900 ":
                # 如意通6900品牌使用ANSI编码（GBK），忽略无法转换的字符
                converted_df.to_csv(output_file, index=False, encoding='gbk', errors='ignore')
            else:
                converted_df.to_csv(output_file, index=False, encoding='utf-8-sig')
            
            # 更新状态
            self.root.after(0, lambda: self.conversion_status.config(text="转换完成！"))
            self.root.after(0, lambda: messagebox.showinfo("成功", f"转换完成！\n输出文件: {output_file}\n\n文件已根据品牌 '{display_brand}' 自动命名"))
            
            # 关闭对话框
            self.root.after(0, self._close_conversion_dialog)
            
        except Exception as e:
            import traceback
            error_details = f"转换失败: {str(e)}\n\n详细错误信息:\n{traceback.format_exc()}"
            self.root.after(0, lambda: self.conversion_status.config(text="转换失败"))
            self.root.after(0, lambda err=str(e): messagebox.showerror("错误", f"转换失败: {err}"))
            # 打印详细错误信息到控制台，便于调试
            print(error_details)
    
    def _close_conversion_dialog(self):
        """关闭转换对话框"""
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Toplevel):
                widget.destroy()
    
    def _ask_convert_to_ansi(self, output_file):
        """询问是否将自由通文件转存为ANSI编码"""
        import os
        import pandas as pd
        
        # 检查文件是否存在
        if not os.path.exists(output_file):
            return
            
        # 询问用户是否需要转存为ANSI编码
        ans = messagebox.askyesno("编码转换", "自由通文件已保存为UTF-8编码。\n\n是否需要将其转存为ANSI编码（GBK）以兼容旧版设备？")
        
        if ans:
            try:
                # 读取UTF-8编码的文件
                df = pd.read_csv(output_file, encoding='utf-8-sig')
                
                # 生成ANSI编码的文件名
                base_name, ext = os.path.splitext(output_file)
                ansi_file = f"{base_name}_ansi{ext}"
                
                # 保存为ANSI编码（GBK），直接忽略无法转换的字符
                df.to_csv(ansi_file, index=False, encoding='gbk', errors='ignore')
                
                # 提示用户
                messagebox.showinfo("成功", f"文件已转存为ANSI编码！\n\n原文件: {output_file}\nANSI编码文件: {ansi_file}")
            except Exception as e:
                messagebox.showerror("错误", f"转存ANSI编码时出错: {str(e)}")
        
    def update_success(self):
        """所有文件更新成功处理"""
        self.update_button.config(state="normal", text="更新盒子")
        messagebox.showinfo("成功", "所有数据文件更新完成！")
        
    def update_failed(self, error_msg):
        """更新失败处理"""
        self.update_button.config(state="normal", text="更新盒子")
        # 替换错误信息中的域名链接、纯域名和IP地址为"服务器"
        import re
        modified_error_msg = str(error_msg)
        # 匹配HTTP/HTTPS URL
        modified_error_msg = re.sub(r'https?://[^\s]+', '服务器', modified_error_msg)
        # 匹配纯域名(如example.com)
        modified_error_msg = re.sub(r'([a-zA-Z0-9][-a-zA-Z0-9]{0,62}(\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+\.?)', '服务器', modified_error_msg)
        # 匹配IP地址
        modified_error_msg = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '服务器', modified_error_msg)
        messagebox.showerror("失败", f"数据更新失败: {modified_error_msg}")
        
    def parse_version(self, version_str):
        """解析版本字符串，返回整数元组用于比较"""
        try:
            # 提取版本号数字部分，例如从"1.07"提取"1"和"07"
            parts = re.findall(r'\d+', version_str)
            # 转换为整数元组
            return tuple(int(part) for part in parts)
        except Exception:
            # 如果解析失败，返回一个非常小的版本号
            return (0, 0)
            
    def check_for_updates(self):
        """启动时检查 GitHub Releases 是否有新版本"""
        import requests
        try:
            self.log("检查程序更新中...")
            headers = {
                "User-Agent": f"MMDVMUpdater/{self.VERSION}",
                "Accept": "application/vnd.github+json",
            }
            resp = requests.get(self.GITHUB_API_URL, headers=headers, timeout=10)
            resp.raise_for_status()
            release = resp.json()

            # tag 形如 v2.1，去掉开头的 v
            tag = str(release.get("tag_name", "")).lstrip("vV")
            release_notes = release.get("body", "") or ""

            # 在 Release 资产里查找主程序 exe
            download_url = ""
            for asset in release.get("assets", []):
                if asset.get("name") == self.UPDATE_ASSET_NAME:
                    download_url = asset.get("browser_download_url", "")
                    break

            if not download_url:
                self.log("检查更新: 最新 Release 中未找到更新文件")
                return

            if self._version_tuple(tag) > self._version_tuple(self.VERSION):
                self.root.after(0, lambda: self.prompt_update(tag, download_url, release_notes))
            else:
                self.log(f"当前已是最新版本: v{self.VERSION}")
        except requests.exceptions.RequestException:
            # 网络错误时静默失败，不影响程序使用
            self.log("检查更新失败: 网络连接问题")
        except Exception as e:
            self.log(f"检查更新失败: {e}")

    @staticmethod
    def _version_tuple(version_str):
        """版本字符串转定长整数元组，如 '2.10' -> (2, 10, 0)"""
        parts = [int(p) for p in re.findall(r"\d+", str(version_str))[:3]]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)

    def prompt_update(self, latest_version, download_url, release_notes):
        """提示用户有新版本可用"""
        message = f"发现新版本: v{latest_version}\n\n"
        if release_notes.strip():
            message += f"更新内容:\n{release_notes.strip()}\n\n"
        message += "是否立即下载并更新？\n更新时程序将自动关闭并重启。"
        if messagebox.askyesno("更新可用", message):
            threading.Thread(
                target=self.download_and_update, args=(download_url,), daemon=True
            ).start()

    def download_and_update(self, download_url):
        """从 GitHub Release 下载新 exe（含国内镜像备选），替换自身并重启"""
        import requests
        import subprocess
        try:
            self.root.after(0, lambda: self.log("开始下载新版本..."))

            if getattr(sys, "frozen", False):
                current_exe = os.path.abspath(sys.executable)
            else:
                # 脚本运行模式不支持自替换，只保存新 exe 供手动使用
                current_exe = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), self.UPDATE_ASSET_NAME
                )
            current_dir = os.path.dirname(current_exe)
            new_exe = os.path.join(current_dir, "mmdvm_updater_new.exe")

            # 依次尝试 GitHub 直链和国内加速镜像
            candidates = []
            for prefix in self.UPDATE_MIRROR_PREFIXES:
                candidates.append(prefix + download_url if prefix else download_url)

            response = None
            last_err = None
            for url in candidates:
                try:
                    host = url.split("/")[2]
                    self.root.after(0, lambda h=host: self.log(f"尝试下载: {h}"))
                    r = requests.get(url, stream=True, timeout=30)
                    r.raise_for_status()
                    response = r
                    break
                except requests.exceptions.RequestException as ex:
                    last_err = ex
                    continue
            if response is None:
                raise last_err if last_err else Exception("所有下载地址均失败")

            total = int(response.headers.get("content-length", 0))
            done = 0
            with open(new_exe, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if total > 0:
                            progress = done / total * 100
                            self.root.after(0, lambda p=progress: self.update_progress(p))

            self.root.after(0, lambda: self.log("新版本下载完成，准备替换并重启..."))

            if not getattr(sys, "frozen", False):
                self.root.after(0, lambda: messagebox.showinfo(
                    "更新完成", f"新程序已保存到:\n{new_exe}\n\n脚本运行模式不支持自动替换，请手动使用该 exe。"))
                return

            # 生成批处理：等待主程序退出 -> 覆盖 exe -> 重启新程序 -> 清理临时文件
            bat = os.path.join(current_dir, "do_update.bat")
            with open(bat, "w", encoding="gbk", errors="ignore") as bf:
                bf.write("@echo off\r\n")
                bf.write(":wait\r\n")
                bf.write("ping 127.0.0.1 -n 2 >nul\r\n")
                bf.write(f'copy /y "{new_exe}" "{current_exe}" >nul 2>nul\r\n')
                bf.write("if errorlevel 1 goto wait\r\n")
                bf.write(f'start "" "{current_exe}"\r\n')
                bf.write(f'del /f /q "{new_exe}" >nul 2>nul\r\n')
                bf.write('del "%~f0" >nul 2>nul\r\n')

            subprocess.Popen(
                ["cmd", "/c", bat], cwd=current_dir,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # 关闭主程序，让批处理完成覆盖并重启
            self.root.after(300, self.root.destroy)

        except Exception as e:
            self.root.after(0, lambda err=str(e): messagebox.showerror("更新错误", f"更新失败: {err}"))
            self.root.after(0, lambda err=str(e): self.log(f"更新失败: {err}"))
            self.root.after(0, lambda: self.update_progress(0))

if __name__ == "__main__":
    import os, sys
    root = tk.Tk()
    
    # 设置窗口图标
    # 获取脚本/可执行文件所在目录
    if getattr(sys, 'frozen', False):
        # 作为可执行文件运行
        app_path = os.path.dirname(sys.executable)
    else:
        # 作为Python脚本运行
        app_path = os.path.dirname(os.path.abspath(__file__))
    
    # 指定自定义图标文件路径
    # 用户可以将自定义图标文件放在与程序相同的目录下，并修改下面的文件名
    icon_file = os.path.join(app_path, "icon.ico")  # 默认使用icon.ico
    
    # 如果图标文件存在，则设置窗口图标
    if os.path.exists(icon_file):
        root.iconbitmap(icon_file)
    
    # 先隐藏主窗口，显示警告后再显示
    root.withdraw()
    app = MMDVMUpdater(root)
    # 显示主窗口
    root.deiconify()
    root.mainloop()
# 版权所有 国服8601版权所有  开发者 BH2VLF  版本 1.12
