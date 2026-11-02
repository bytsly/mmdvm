# -*- coding: utf-8 -*-
"""
P2P 联系人同步模块

协议：TCP 长连接 + JSON Lines（每条消息一行 JSON）。
拓扑：所有节点运行相同代码，互为对等节点；常开的公网节点作为引导节点，
      客户端节点主动外连，消息通过 flooding（转发+去重）传遍全网。

消息类型：
- hello        握手：{type, callsign, listen_port, peers:[...]}
- user_update  联系人修改：{type, msg_id, radio_id, callsign, name, city,
              state, country, remarks, ts, author}
- sync_request 反熵请求：{type, since}  要求对方发送 ts > since 的更新
- peer_list    节点列表交换：{type, peers:[...]}
"""

import json
import os
import socket
import threading
import time
import uuid
from collections import deque

PROTO_VERSION = 1
MAX_SEEN_IDS = 20000
MAX_HISTORY = 5000          # 本地历史消息保留条数（用于反熵）
RECONNECT_INTERVAL = 15     # 引导节点重连间隔（秒）
PEER_EXCHANGE_INTERVAL = 60 # 节点列表交换间隔（秒）


class PeerConnection:
    """一条到对等节点的 TCP 连接"""

    def __init__(self, node, sock, address, inbound):
        self.node = node
        self.sock = sock
        self.address = address          # (host, port)
        self.inbound = inbound          # True=对方连入, False=本方外连
        self.send_lock = threading.Lock()
        self.alive = True
        self.callsign = ""
        self.listen_port = 0
        self.rfile = sock.makefile("r", encoding="utf-8", newline="\n")

    def send(self, msg):
        """发送一条 JSON 消息，失败返回 False"""
        if not self.alive:
            return False
        try:
            data = json.dumps(msg, ensure_ascii=False) + "\n"
            with self.send_lock:
                self.sock.sendall(data.encode("utf-8"))
            return True
        except OSError:
            self.alive = False
            return False

    def close(self):
        self.alive = False
        try:
            self.rfile.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class P2PNode:
    """P2P 同步节点：广播/接收 user.csv 联系人修改"""

    def __init__(self, callsign, listen_enabled, listen_port, bootstrap,
                 data_dir, on_user_update=None, on_status=None, on_log=None):
        """
        callsign:       本机呼号（消息 author 字段）
        listen_enabled: 是否监听入站连接（有公网 IP 的节点开启）
        listen_port:    监听端口
        bootstrap:      引导节点列表 ["host:port", ...]
        data_dir:       历史消息/状态存储目录
        on_user_update: 收到联系人更新时的回调 func(msg)（在接收线程中调用）
        on_status:      节点数变化回调 func(peer_count)
        on_log:         日志回调 func(text)
        """
        self.callsign = callsign
        self.node_id = uuid.uuid4().hex  # 每次启动随机，用于识别自连接
        self.listen_enabled = listen_enabled
        self.listen_port = listen_port
        self.bootstrap = list(bootstrap or [])
        self.data_dir = data_dir
        self.on_user_update = on_user_update
        self.on_status = on_status
        self.on_log = on_log or (lambda t: None)

        self.peers = []                 # List[PeerConnection]
        self.peers_lock = threading.Lock()
        self.seen_ids = set()
        self.seen_order = deque(maxlen=MAX_SEEN_IDS)
        self.history = []               # 最近收到的 user_update（用于反熵）
        self.history_lock = threading.Lock()
        self.known_peers = set()        # "host:port" 字符串
        self.stop_event = threading.Event()
        self.server_sock = None
        self.threads = []

        os.makedirs(self.data_dir, exist_ok=True)
        self.history_file = os.path.join(self.data_dir, "p2p_updates.jsonl")
        self._load_history()

    # ------------------------------------------------------------------ 日志
    def _log(self, text):
        try:
            self.on_log(text)
        except Exception:
            pass

    # -------------------------------------------------------------- 历史记录
    def _load_history(self):
        """启动时加载本地历史消息"""
        if not os.path.exists(self.history_file):
            return
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "user_update" and msg.get("msg_id"):
                        self.history.append(msg)
                        self._mark_seen(msg["msg_id"])
            # 裁剪过长历史
            if len(self.history) > MAX_HISTORY:
                self.history = self.history[-MAX_HISTORY:]
                self._save_history()
        except OSError as ex:
            self._log(f"P2P 历史加载失败: {ex}")

    def _save_history(self):
        """历史全量写回（用于裁剪后）"""
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                for msg in self.history:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        except OSError as ex:
            self._log(f"P2P 历史保存失败: {ex}")

    def _append_history(self, msg):
        with self.history_lock:
            self.history.append(msg)
            overflow = len(self.history) - MAX_HISTORY
            if overflow > 0:
                del self.history[:overflow]
                self._save_history()
                return
        try:
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        except OSError as ex:
            self._log(f"P2P 历史写入失败: {ex}")

    @staticmethod
    def _msg_ts(msg):
        """安全提取消息时间戳，畸形数据返回 0"""
        try:
            return float(msg.get("ts", 0))
        except (TypeError, ValueError):
            return 0.0

    def _latest_ts(self):
        with self.history_lock:
            if not self.history:
                return 0.0
            return max(self._msg_ts(m) for m in self.history)

    # ---------------------------------------------------------------- 去重
    def _mark_seen(self, msg_id):
        if len(self.seen_order) == self.seen_order.maxlen:
            old = self.seen_order[0]
            self.seen_ids.discard(old)
        self.seen_order.append(msg_id)
        self.seen_ids.add(msg_id)

    def _is_new(self, msg_id):
        return msg_id not in self.seen_ids

    # ---------------------------------------------------------------- 启动
    def start(self):
        """启动节点（全部后台线程，立即返回）"""
        if self.listen_enabled and self.listen_port > 0:
            t = threading.Thread(target=self._listen_loop, daemon=True,
                                 name="p2p-listen")
            t.start()
            self.threads.append(t)
        t = threading.Thread(target=self._connect_loop, daemon=True,
                             name="p2p-connect")
        t.start()
        self.threads.append(t)
        t = threading.Thread(target=self._peer_exchange_loop, daemon=True,
                             name="p2p-peerx")
        t.start()
        self.threads.append(t)

    def stop(self):
        self.stop_event.set()
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass
        with self.peers_lock:
            peers = list(self.peers)
        for p in peers:
            p.close()

    # ---------------------------------------------------------------- 监听
    def _listen_loop(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.listen_port))
            srv.listen(16)
            srv.settimeout(2)
            self.server_sock = srv
            self._log(f"P2P 监听端口 {self.listen_port} 已开启")
        except OSError as ex:
            self._log(f"P2P 监听端口 {self.listen_port} 失败: {ex}")
            return
        while not self.stop_event.is_set():
            try:
                client, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(None)
            peer = PeerConnection(self, client, addr, inbound=True)
            self._add_peer(peer)
            threading.Thread(target=self._recv_loop, args=(peer,),
                             daemon=True, name="p2p-recv").start()

    # ---------------------------------------------------------------- 外连
    def _connect_loop(self):
        """维护到引导节点和已知节点的外连"""
        while not self.stop_event.is_set():
            targets = set(self.bootstrap) | set(self.known_peers)
            for target in targets:
                if self.stop_event.is_set():
                    break
                host, sep, port_s = target.rpartition(":")
                if not sep or not host:
                    continue
                try:
                    port = int(port_s)
                except ValueError:
                    continue
                # 解析为 IP，统一按 IP 比较，避免 域名/IP 双重连接
                try:
                    ip = socket.gethostbyname(host)
                except OSError:
                    continue
                # 跳过自己（回环地址+自己的监听端口）
                if self.listen_enabled and port == self.listen_port and \
                        ip == "127.0.0.1":
                    continue
                if self._is_connected(ip, port):
                    continue
                try:
                    sock = socket.create_connection((ip, port), timeout=8)
                except OSError:
                    continue
                peer = PeerConnection(self, sock, (ip, port), inbound=False)
                self._add_peer(peer)
                self._log(f"P2P 已连接节点 {ip}:{port}")
                threading.Thread(target=self._recv_loop, args=(peer,),
                                 daemon=True, name="p2p-recv").start()
            self.stop_event.wait(RECONNECT_INTERVAL)

    def _is_connected(self, host, port):
        with self.peers_lock:
            for p in self.peers:
                if p.alive and not p.inbound and p.address == (host, port):
                    return True
                # 入站连接也算已连（对方可能是从该地址连入的引导节点）
                if p.alive and p.inbound and p.address[0] == host \
                        and p.listen_port == port:
                    return True
        return False

    # ------------------------------------------------------------ 节点交换
    def _peer_exchange_loop(self):
        while not self.stop_event.is_set():
            self.stop_event.wait(PEER_EXCHANGE_INTERVAL)
            if self.stop_event.is_set():
                break
            peers_info = self._my_peer_info()
            msg = {"type": "peer_list", "peers": peers_info}
            with self.peers_lock:
                peers = list(self.peers)
            for p in peers:
                p.send(msg)

    def _my_peer_info(self):
        """当前已知的可连接节点地址列表"""
        info = set(self.bootstrap) | set(self.known_peers)
        with self.peers_lock:
            for p in self.peers:
                if p.alive and p.listen_port:
                    info.add(f"{p.address[0]}:{p.listen_port}")
        return sorted(info)

    def _add_known_peer(self, addr):
        """登记已知节点地址（上限 200，防止无限增长）"""
        if not isinstance(addr, str) or ":" not in addr:
            return
        if addr in self.known_peers or len(self.known_peers) < 200:
            self.known_peers.add(addr)

    # ------------------------------------------------------------ 连接管理
    def _add_peer(self, peer):
        with self.peers_lock:
            self.peers.append(peer)
        self._notify_status()
        # 握手：hello + 反熵请求
        my_info = self._my_peer_info()
        peer.send({
            "type": "hello",
            "v": PROTO_VERSION,
            "node_id": self.node_id,
            "callsign": self.callsign,
            "listen_port": self.listen_port if self.listen_enabled else 0,
            "peers": my_info,
        })
        peer.send({"type": "sync_request", "since": self._latest_ts()})

    def _remove_peer(self, peer):
        with self.peers_lock:
            if peer in self.peers:
                self.peers.remove(peer)
        peer.close()
        self._notify_status()
        self._log(f"P2P 节点断开 {peer.address[0]}:{peer.address[1]}")

    def _notify_status(self):
        if not self.on_status:
            return
        with self.peers_lock:
            count = sum(1 for p in self.peers if p.alive)
        try:
            self.on_status(count)
        except Exception:
            pass

    def peer_count(self):
        with self.peers_lock:
            return sum(1 for p in self.peers if p.alive)

    def status(self):
        """当前运行状态快照（供 GUI 状态窗口展示）"""
        with self.peers_lock:
            peers = [{
                "address": f"{p.address[0]}:{p.address[1]}",
                "inbound": bool(p.inbound),
                "callsign": p.callsign,
                "listen_port": p.listen_port,
                "alive": bool(p.alive),
            } for p in self.peers if p.alive]
        with self.history_lock:
            history_count = len(self.history)
            last_ts = max((self._msg_ts(m) for m in self.history), default=0.0)
        return {
            "running": not self.stop_event.is_set(),
            "callsign": self.callsign,
            "listen_enabled": bool(self.listen_enabled),
            "listen_port": self.listen_port,
            "bootstrap": list(self.bootstrap),
            "known_peers": sorted(self.known_peers),
            "peers": peers,
            "peer_count": len(peers),
            "history_count": history_count,
            "last_ts": last_ts,
        }

    # ---------------------------------------------------------------- 收消息
    def _recv_loop(self, peer):
        try:
            while not self.stop_event.is_set() and peer.alive:
                try:
                    line = peer.rfile.readline()
                except (OSError, ValueError):
                    break
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._handle_message(peer, msg)
        finally:
            self._remove_peer(peer)

    def _handle_message(self, source, msg):
        mtype = msg.get("type")

        if mtype == "hello":
            # 自连接检测：对方 hello 里的 node_id 与本机相同 → 是自己连自己
            if msg.get("node_id") == self.node_id:
                self._log("P2P 检测到自连接，已断开")
                source.close()
                return
            source.callsign = str(msg.get("callsign", ""))
            try:
                source.listen_port = int(msg.get("listen_port", 0))
            except (TypeError, ValueError):
                source.listen_port = 0
            for addr in msg.get("peers", []) or []:
                self._add_known_peer(addr)
            if source.listen_port:
                self._add_known_peer(
                    f"{source.address[0]}:{source.listen_port}")
            return

        if mtype == "peer_list":
            for addr in msg.get("peers", []) or []:
                self._add_known_peer(addr)
            return

        if mtype == "sync_request":
            try:
                since = float(msg.get("since", 0))
            except (TypeError, ValueError):
                since = 0.0
            with self.history_lock:
                newer = [m for m in self.history
                         if self._msg_ts(m) > since]
            for m in newer:
                source.send(m)
            return

        if mtype == "user_update":
            msg_id = msg.get("msg_id")
            if not msg_id or not self._is_new(msg_id):
                return
            self._mark_seen(msg_id)
            self._append_history(msg)
            # 回调处理合并
            if self.on_user_update:
                try:
                    self.on_user_update(msg)
                except Exception as ex:
                    self._log(f"P2P 更新处理出错: {ex}")
            # flooding：转发给除来源外的所有节点
            self._forward(msg, exclude=source)
            return

    def _forward(self, msg, exclude=None):
        with self.peers_lock:
            peers = [p for p in self.peers if p is not exclude]
        for p in peers:
            if not p.send(msg):
                self._remove_peer(p)

    # ---------------------------------------------------------------- 广播
    def broadcast_user_update(self, radio_id, callsign, name, city, state,
                              country, remarks):
        """本地编辑保存后调用：生成消息并广播。返回消息 dict。"""
        msg = {
            "type": "user_update",
            "msg_id": uuid.uuid4().hex,
            "radio_id": str(radio_id),
            "callsign": str(callsign),
            "name": str(name),
            "city": str(city),
            "state": str(state),
            "country": str(country),
            "remarks": str(remarks),
            "ts": time.time(),
            "author": self.callsign,
        }
        self._mark_seen(msg["msg_id"])
        self._append_history(msg)
        self._forward(msg)
        return msg
