"""OA协同办公助手 v8（置顶弹窗提醒）

功能：工程师端运行后最小化即可。轮询 OA 服务器，发现派给自己的新工单时，
在屏幕右下角弹出置顶提醒卡片：圆角卡片 + 品牌图标 + 倒计时进度条 + 滑入动画，
带声音、显示在所有窗口之上，任何页面都能看到，不依赖 Windows 通知设置。

v14 改进：
  - 修复间歇性漏提醒：相关工单超过 100 张时旧单会掉出跟踪范围
    （只拉了第一页），现在自动翻页拉全量；
  - 登录令牌过期自动重连时明确提示"重建基线，期间变化不再提醒"。

v13 改进：
  - 修复：弹窗倒计时自动关闭（及点 ✕ 关闭）时误打开工单详情链接；
    现在只有点击卡片本体才会跳转。

v12 改进：
  - "接收工单反馈提醒"改为权限控制（OA 权限管理中的「工单跟踪」模块）：
    管理员可勾给任何账号（如 engineer1），勾选后该账号的助手会收到
    与自己相关工单的 接单/反馈/验收/取消 提醒；
  - 工程师账号可同时接收"新工单 + 反馈"两种提醒；管理员/调度员默认开启。

v11 改进：
  - 调度员可跟踪"自己派发"的工单（含他人创建、孪生下发的单）；
  - 弹窗标题带工程师姓名：如"技术员2 反馈了工单"。

v10 改进：
  - 弹窗可直接点击：点击提醒卡片自动打开浏览器并直达该工单详情页。

v9 改进：
  - 管理员/调度员账号登录时自动启用"管理提醒"：与自己相关的工单
    在 工程师接单 / 提交验收 / 验收通过 / 验收驳回 / 取消 时弹窗提醒；
  - 工程师账号保持原有"收到新工单"提醒不变。

v8 改进：
  - 登录信息记忆：首次输入服务器地址、账号、密码后自动保存为 exe 同目录下的
    OA助手.ini，之后双击 exe 直接使用，无需再次输入；
  - 换账号或清除配置：命令行运行 exe --reset；
  - 自动登录失败（如密码被改）时退回交互输入并重新记忆；
  - 只提醒"真正指派给自己"的工单：按 assignee_id 二次过滤，修复派发者
    （工单创建人）自己的助手也弹"收到新工单"的问题。

用法：
    双击 OATool-Notifier.exe —— 首次输入一次，之后双击即用；
    或命令行：OATool-Notifier.exe http://192.168.1.100:8001 engineer2 123456
    仅测试弹窗：OATool-Notifier.exe --test
    清除记忆配置：OATool-Notifier.exe --reset

依赖：仅 Python 标准库。
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import winsound
from getpass import getpass

POLL_SECONDS = 5
VERSION = "v14"
POPUP_SECONDS = 8

CONFIG_FILE = "OA助手.ini"
SERVER_ROOT = ""  # 登录后设置，用于弹窗点击跳转的页面地址


def _config_path() -> str:
    """配置文件与 exe/脚本同目录，便于随拷随用。"""
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0])) or "."
    return os.path.join(exe_dir, CONFIG_FILE)


def _obscure(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _deobscure(s: str) -> str:
    try:
        return base64.b64decode(s.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def load_config():
    """读取记忆的登录配置（首次输入后自动保存，之后双击 exe 直接使用）。"""
    try:
        d = json.load(open(_config_path(), encoding="utf-8"))
        base = d.get("base", "")
        username = _deobscure(d.get("username", ""))
        password = _deobscure(d.get("password", ""))
        if base and username:
            return {"base": base, "username": username, "password": password}
    except Exception:
        pass
    return None


def save_config(base: str, username: str, password: str) -> None:
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(
                {"base": base, "username": _obscure(username), "password": _obscure(password)},
                f, ensure_ascii=False, indent=2,
            )
    except Exception:
        pass


def clear_config() -> None:
    try:
        os.remove(_config_path())
    except Exception:
        pass


def popup(title: str, message: str, seconds: int = POPUP_SECONDS, accent: str = "#2f8bff", url: str = "") -> bool:
    """右下角置顶弹窗：现代卡片风格，显示在所有窗口之上，不依赖 Windows 通知设置。"""
    W, H = 400, 150
    CARD = "#0e2036"      # 卡片底色
    BORDER = "#1d3f63"    # 描边
    TEXT = "#e8eef6"      # 正文
    SUB = "#7f95b3"       # 次要文字
    MAGIC = "#ff00fe"     # 透明色（圆角外区域镂空用，不支持时退回卡片色）

    try:
        import tkinter as tk
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-transparentcolor", MAGIC)
        except Exception:
            MAGIC = CARD  # 系统不支持透明色：保留直角卡片
        root.configure(bg=MAGIC)
        root.attributes("-alpha", 0.0)
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x_end = sw - W - 20
        y_end = sh - H - 60  # 右下角，任务栏上方
        x_start = sw + 10  # 从屏幕右缘外滑入

        cv = tk.Canvas(root, width=W, height=H, highlightthickness=0, bg=MAGIC)
        cv.pack(fill="both", expand=True)

        def round_rect(x1, y1, x2, y2, r, **kw):
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                   x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
            return cv.create_polygon(pts, smooth=True, **kw)

        # 卡片：外圈描边 + 内层底色
        round_rect(1, 1, W - 1, H - 1, 14, fill=BORDER)
        round_rect(3, 3, W - 3, H - 3, 13, fill=CARD)

        # 左侧品牌图标徽章（蓝底白铃铛）
        round_rect(14, 16, 48, 50, 8, fill=accent)
        cv.create_arc(22, 22, 40, 37, start=0, extent=180, style=tk.ARC, outline="#ffffff", width=2)
        cv.create_line(20, 37, 42, 37, fill="#ffffff", width=2)
        cv.create_oval(29, 37, 33, 41, fill="#ffffff", outline="")

        # 标题与关闭按钮
        cv.create_text(60, 19, anchor="nw", text="OA · " + title,
                       font=("Microsoft YaHei UI", 12, "bold"), fill="#ffffff")
        close_tag = cv.create_text(W - 18, 20, anchor="ne", text="✕",
                                   font=("Microsoft YaHei UI", 12), fill=SUB)

        # 正文
        cv.create_text(18, 58, anchor="nw", text=message, width=W - 36,
                       font=("Microsoft YaHei UI", 10), fill=TEXT)

        # 底部信息行
        cv.create_text(16, H - 22, anchor="sw", text=time.strftime("%H:%M"),
                       font=("Microsoft YaHei UI", 8), fill=SUB)
        cv.create_text(W - 16, H - 22, anchor="se", text=("点击查看工单" if url else "点击任意处关闭"),
                       font=("Microsoft YaHei UI", 8), fill=SUB)

        # 底部倒计时进度条
        cv.create_line(14, H - 5, W - 14, H - 5, fill=BORDER, width=3)
        bar = cv.create_line(14, H - 5, W - 14, H - 5, fill=accent, width=3)

        total_ms = int(seconds * 1000)
        start_ts = time.time()
        dismissed = {"v": False}

        def _fade_out(step: int = 10) -> None:
            if step <= 0:
                root.destroy()
                return
            root.attributes("-alpha", max(step / 10, 0.0))
            root.after(30, lambda: _fade_out(step - 1))

        def _close_only() -> None:
            """仅关闭弹窗（超时自动关闭 / 点 ✕）：不打开链接。"""
            if dismissed["v"]:
                return
            dismissed["v"] = True
            _fade_out()

        def _open_link(_evt=None) -> None:
            """点击卡片：打开工单详情并关闭。"""
            if dismissed["v"]:
                return
            dismissed["v"] = True
            if url:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            _fade_out()

        def _tick() -> None:
            if dismissed["v"]:
                return
            remain = total_ms - (time.time() - start_ts) * 1000
            if remain <= 0:
                _close_only()
                return
            w = 14 + (W - 28) * (remain / total_ms)
            cv.coords(bar, 14, H - 5, w, H - 5)
            root.after(100, _tick)

        cv.tag_bind(close_tag, "<Enter>", lambda e: cv.itemconfig(close_tag, fill="#ff7043"))
        cv.tag_bind(close_tag, "<Leave>", lambda e: cv.itemconfig(close_tag, fill=SUB))
        cv.tag_bind(close_tag, "<Button-1>", lambda e: (_close_only(), "break")[1])
        root.bind("<Button-1>", _open_link)

        # 滑入 + 淡入动画
        for i in range(11):
            t = i / 10
            root.geometry(f"{W}x{H}+{int(x_start + (x_end - x_start) * t)}+{y_end}")
            root.attributes("-alpha", t)
            root.update()
            time.sleep(0.015)
        root.after(100, _tick)
        root.mainloop()
        return True
    except Exception:
        return False


def order_link(order_id) -> str:
    """工单详情页直达链接（点击弹窗跳转用）。"""
    if not order_id or not SERVER_ROOT:
        return ""
    return SERVER_ROOT + "/?open_order=" + str(order_id)


def notify(title: str, message: str, order_id=None) -> None:
    """置顶弹窗提醒（品牌蓝卡片），带工单 ID 时点击可直达详情页。"""
    popup(title, message, accent="#2f8bff", url=order_link(order_id))


class OAClient:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/") + "/api/v1"
        self.username = username
        self.password = password
        self.token = None
        self.user_id = None

    def login(self) -> bool:
        data = json.dumps({"username": self.username, "password": self.password}).encode("utf-8")
        req = urllib.request.Request(self.base + "/auth/login", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
                self.token = d["token"]
                return True
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail", "登录失败")
            except Exception:
                detail = "登录失败"
            print("登录失败：", detail)
            return False
        except Exception as e:
            print("无法连接服务器：", e)
            return False

    def me(self):
        """当前账号信息（姓名、角色），用于确认登录的是被派单的工程师。"""
        s, d = self._call("/auth/me")
        if s == 200:
            self.user_id = d.get("id")
            return d
        return None

    def _only_mine(self, items):
        """只保留真正指派给自己的工单。

        后端的 mine=1 过滤包含"我创建的"工单（如调度员自己创建的工单），
        会导致派发者自己也收到提醒，这里按 assignee_id 再过滤一次。
        """
        if self.user_id is None:
            self.me()  # 拿到自己的用户 ID；失败则本轮不提醒，避免误报
        if self.user_id is None:
            return []
        return [o for o in items if o.get("assignee_id") == self.user_id]

    def _call(self, path):
        req = urllib.request.Request(self.base + path)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"_error": str(e)}

    def my_related_orders(self):
        """与我相关的全部工单（我创建/我派发/派给我），任意状态，自动翻页取全量。

        旧版只取第一页 100 张：工单累积超 100 后，被顶出首页的在办工单
        会悄悄失去跟踪（表现为"有时候收不到反馈提醒"）。
        """
        items = []
        page = 1
        while page <= 50:  # 安全上限 50 页 = 5000 张
            s, d = self._call(f"/work-orders?mine=1&page_size=100&page={page}")
            if s == 401:
                self.token = None
                return None
            if s != 200:
                return None
            batch = d.get("items", [])
            items.extend(batch)
            if len(items) >= d.get("total", 0) or not batch:
                break
            page += 1
        return items

    def my_pending_orders(self):
        """派给我且待接单的工单。返回 None 表示需要重新登录或网络异常。"""
        s, d = self._call("/work-orders?status=PENDING_ACCEPT&mine=1&page_size=100")
        if s == 401:
            self.token = None
            return None
        if s != 200:
            return None
        return self._only_mine(d.get("items", []))


# 管理提醒：工单状态迁移 -> 弹窗文案（old_status, new_status -> (标题, 说明)）
STATUS_TRANSITIONS = {
    ("PENDING_ACCEPT", "PROCESSING"): ("工程师已接单", "已开始处理"),
    ("PROCESSING", "PENDING_VERIFY"): ("工单已提交验收", "请及时验收"),
    ("PENDING_VERIFY", "COMPLETED"): ("工单验收通过", "该工单已完成"),
    ("PENDING_VERIFY", "PROCESSING"): ("工单验收驳回", "已退回工程师重新处理"),
}


def manager_transition_msg(old: str, new: str, o: dict):
    """根据工单状态变化返回 (标题, 内容) 或 None（不打扰的变化）。

    按新状态的语义判断（弹窗阻塞轮询期间状态可能连跳两级，
    如 处理中→已完成 跳过了 待验收，因此不做精确的 old->new 组合匹配）。
    """
    who = o.get("assignee_name") or "工程师"
    order = f"{o.get('order_no', '')}  {o.get('title', '')}"
    if new == "CANCELLED":
        return ("工单已取消", order)
    if new == "COMPLETED":
        return ("工单验收通过", order + chr(10) + who + " · 该工单已完成")
    if new == "PENDING_VERIFY":
        return (who + " 反馈了工单", order + chr(10) + who + " · 已提交验收，请及时查验")
    if new == "PROCESSING":
        if old == "PENDING_VERIFY":
            return ("工单验收驳回", order + chr(10) + who + " · 已退回重新处理")
        if old == "PENDING_ACCEPT":
            return (who + " 反馈了工单", order + chr(10) + who + " · 已接单开始处理")
        return None  # 其余进入处理中的路径不提醒
    return None



def main() -> None:
    print("=" * 52)
    print(f"  OA协同办公助手 {VERSION}（置顶弹窗提醒）")
    print("  收到派给自己的新工单时：屏幕右下角弹出提醒卡片")
    print("  首次输入一次账号密码，之后双击 exe 即可直接使用")
    print("=" * 52)

    if len(sys.argv) == 2 and sys.argv[1] == "--test":
        print("正在发送测试提醒...")
        ok_popup = popup("测试通知", "如果你看到这个置顶弹窗，说明提醒工作正常（8 秒后自动关闭）")
        print("置顶弹窗测试：", "成功" if ok_popup else "失败")
        input("按回车退出...")
        return

    if len(sys.argv) == 2 and sys.argv[1] == "--reset":
        clear_config()
        print("已清除记忆的登录配置，请重新输入：")

    # 登录参数来源：命令行参数 > 记忆配置 > 交互输入
    cfg_source = None
    base = username = password = None
    if len(sys.argv) >= 4:
        base, username, password = sys.argv[1], sys.argv[2], sys.argv[3]
        cfg_source = "cli"
    else:
        cfg = load_config()
        if cfg:
            base, username, password = cfg["base"], cfg["username"], cfg["password"]
            cfg_source = "config"

    global SERVER_ROOT
    SERVER_ROOT = (base or "").rstrip("/")
    if SERVER_ROOT.endswith("/api/v1"):
        SERVER_ROOT = SERVER_ROOT[:-7]
    client = OAClient(base, username, password) if base else None
    logged = client.login() if client is not None else False
    if not logged:
        if client is not None:
            print("自动登录失败，请重新输入服务器地址、账号、密码：")
        base = input("服务器地址（如 http://192.168.1.100:8001）：").strip() or "http://127.0.0.1:8001"
        username = input("登录账号：").strip()
        password = getpass("密码：")
        client = OAClient(base, username, password)
        if not client.login():
            input("按回车退出...")
            return
        save_config(base, username, password)
        print("登录成功，配置已记忆：以后双击 exe 即可直接使用")
    elif cfg_source == "config":
        print(f"已自动登录：{username}（使用记忆的配置，换账号请运行 exe --reset）")
    else:
        save_config(base, username, password)
        print(f"已登录：{username}（配置已记忆，以后双击 exe 即可直接使用）")

    info = client.me()
    # 反馈提醒（接单/完成/验收/取消）：管理员、调度员默认开通；
    # 其他账号由 OA「权限管理」中的「工单跟踪」模块控制
    perms = (info or {}).get("permissions") or []
    track_enabled = bool(info and (info.get("role") in ("ADMIN", "DISPATCHER") or "track" in perms))
    if info:
        print(f"已登录：{info['real_name']}（{info['role_label']}）")
        if info["role"] not in ("ENGINEER", "ADMIN", "DISPATCHER"):
            print("⚠ 该账号角色未知，可能收不到提醒。")
    print(f"开始监听新工单（每 {POLL_SECONDS} 秒刷新，窗口可最小化）")
    ok_popup = popup("提醒助手已启动", f"{username} 已连接工单系统\n收到新工单时右下角会弹出提醒")
    print("置顶弹窗自检：", "通过（屏幕右下角应有弹窗）" if ok_popup else "失败")
    print("说明：只要弹窗正常，无论窗口是否最小化、无论在看哪个页面都能看到提醒。")

    known_orders: set = set()
    known_status: dict = {}
    # 首次轮询静默初始化：不提醒启动前已存在的工单/状态
    first_related = client.my_related_orders()
    if first_related is not None:
        known_status = {o["id"]: o["status"] for o in first_related}
        known_orders = {o["id"] for o in first_related}
    if track_enabled:
        print(f"工单跟踪已开启：正在跟踪与您相关的 {len(known_status)} 张工单")
        print("工程师接单 / 反馈工单 / 验收通过 / 驳回 / 取消 时会弹窗提醒（启动前的状态不再提醒）")
    print(f"当前待接单 {sum(1 for s in known_status.values() if s == 'PENDING_ACCEPT')} 张（启动前的工单不再提醒）")

    last_err_ts = 0.0
    last_beat_ts = 0.0

    while True:
        try:
            related = client.my_related_orders()
            if related is None and client.token is None:
                print(time.strftime("%H:%M:%S"), "登录失效，自动重新登录...")
                if not client.login():
                    print("重新登录失败，10 秒后重试")
                    time.sleep(10)
                    continue
                related = client.my_related_orders() or []
                # 重连后避免重复轰炸：重建基线（重连期间发生的变化不再提醒）
                known_status = {o["id"]: o["status"] for o in related}
                known_orders = {o["id"] for o in related}
                print("已重新连接（基线已重建，断线期间发生的变化不再提醒）")
            if related is None:
                # 网络瞬断：保持去重状态，下一轮重试
                now = time.time()
                if now - last_err_ts > 60:
                    print(time.strftime("%H:%M:%S"), "连接服务器失败，自动重试中...")
                    last_err_ts = now
                time.sleep(POLL_SECONDS)
                continue

            cur = {o["id"]: o for o in related}
            events = []
            # 事件一：派给我的新工单（任何账号，待接单状态）
            for o in cur.values():
                if (o["status"] == "PENDING_ACCEPT"
                        and o.get("assignee_id") == client.user_id
                        and o["id"] not in known_orders):
                    events.append(("new", o))
            # 事件二：相关工单的状态反馈（需 track 权限或管理角色）
            if track_enabled:
                for oid, o in cur.items():
                    old_st = known_status.get(oid)
                    if old_st is not None and old_st != o["status"]:
                        msg = manager_transition_msg(old_st, o["status"], o)
                        if msg:
                            events.append(("feedback", msg[0], msg[1], o["status"], oid, o["order_no"]))
            # 先更新基线再弹窗：弹窗阻塞期间到达的新状态下一轮仍能检出
            known_status = {oid: o["status"] for oid, o in cur.items()}
            known_orders |= set(cur.keys())
            for ev in events:
                if ev[0] == "new":
                    o = ev[1]
                    notify(
                        "收到新工单",
                        f"{o['order_no']}  {o['title']}" + chr(10) + f"优先级：{o['priority_label']} · 点击卡片可直接查看工单",
                        order_id=o["id"],
                    )
                    print(time.strftime("%H:%M:%S"), "[新工单]", o["order_no"], o["title"])
                else:
                    _, title, body, new_st, oid, order_no = ev
                    accent = "#67c23a" if new_st == "COMPLETED" else "#2f8bff"
                    popup(title, body, accent=accent, url=order_link(oid))
                    print(time.strftime("%H:%M:%S"), f"[{title}]", order_no)

            now = time.time()
            if now - last_beat_ts > 60:
                pending_n = sum(1 for s in known_status.values() if s == "PENDING_ACCEPT")
                print(time.strftime("%H:%M:%S"), f"监听中：相关工单 {len(known_status)} 张 / 待接单 {pending_n} 张")
                last_beat_ts = now
        except KeyboardInterrupt:
            print("\n提醒助手已退出")
            return
        except Exception as e:
            print(time.strftime("%H:%M:%S"), "异常：", e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
