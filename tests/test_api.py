"""核心接口自动化测试（pytest）。

运行：.venv/Scripts/python.exe -m pytest tests -v
说明：测试使用临时 SQLite 数据库，不影响正式数据。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# 必须在导入 app 之前指向临时数据库
_tmp = tempfile.mkdtemp(prefix="oatool-test-")
os.environ["OATOOL_DB_URL"] = f"sqlite:///{_tmp}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # 触发 lifespan：建表 + 初始化种子数据
        yield c


_token_cache = {}


def login(client, username="admin", password="123456"):
    # 缓存 token，避免触发登录限流（同 IP 每分钟 30 次）
    if username not in _token_cache:
        r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        _token_cache[username] = r.json()["token"]
    return _token_cache[username]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["app"] == "OA"


def test_login_fail_and_lock(client):
    # 使用独立用户名做爆破测试，避免锁定演示账号影响其他用例
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "bruteforce_test", "password": "wrong"})
        assert r.status_code == 401
    # 连续失败 5 次后账号锁定
    r = client.post("/api/v1/auth/login", json={"username": "bruteforce_test", "password": "wrong"})
    assert r.status_code == 423


def test_work_order_full_flow(client):
    """完整工单流转：创建 → 派单 → 接单 → 完成 → 验收。"""
    t_admin = login(client)
    t_disp = login(client, "dispatcher")
    t_eng = login(client, "engineer3")

    # 工程师不能直接创建工单（两段式职责分离）
    r = client.post("/api/v1/work-orders", json={"title": "越权创建"}, headers=auth(t_eng))
    assert r.status_code == 403

    # 调度员创建并直接指派
    r = client.post("/api/v1/work-orders", json={
        "title": "测试工单：输送带检修", "order_type": "FAULT",
        "assignee_id": 5, "priority": "P2",
    }, headers=auth(t_disp))
    assert r.status_code == 200
    wo = r.json()
    assert wo["status"] == "PENDING_ACCEPT" and wo["assignee_name"] == "技术员3"

    # 接单 → 处理中
    r = client.post(f"/api/v1/work-orders/{wo['id']}/accept", json={}, headers=auth(t_eng))
    assert r.status_code == 200 and r.json()["status"] == "PROCESSING"

    # 提交完成 → 待验收
    r = client.post(f"/api/v1/work-orders/{wo['id']}/complete",
                    json={"result": "更换轴承，试机正常"}, headers=auth(t_eng))
    assert r.status_code == 200 and r.json()["status"] == "PENDING_VERIFY"

    # 验收通过 → 已完成
    r = client.post(f"/api/v1/work-orders/{wo['id']}/verify",
                    json={"passed": True, "comment": "复测正常"}, headers=auth(t_admin))
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"

    # 流转日志完整
    r = client.get(f"/api/v1/work-orders/{wo['id']}/logs", headers=auth(t_admin))
    actions = [log["action"] for log in r.json()]
    assert actions == ["CREATE", "DISPATCH", "ACCEPT", "COMPLETE", "VERIFY_PASS"]


def test_repair_two_stage_flow(client):
    """两段式：工程师报修 → 调度员审核立项 → 生成工单。"""
    t_eng = login(client, "engineer2")
    t_disp = login(client, "dispatcher")

    r = client.post("/api/v1/repair-requests", json={
        "title": "报修：配电柜异响", "priority": "P3",
    }, headers=auth(t_eng))
    assert r.status_code == 200 and r.json()["status"] == "PENDING_REVIEW"
    rid = r.json()["id"]

    r = client.post(f"/api/v1/repair-requests/{rid}/approve", json={
        "priority": "P3", "order_type": "FAULT", "assignee_id": 4,
        "review_comment": "先断电挂牌",
    }, headers=auth(t_disp))
    assert r.status_code == 200
    data = r.json()
    assert data["request"]["status"] == "APPROVED"
    assert data["work_order"]["status"] == "PENDING_ACCEPT"


def test_approval_chain(client):
    """通用审批：请假申请 调度员→管理员 两级流转。"""
    t_eng = login(client, "engineer2")
    t_disp = login(client, "dispatcher")
    t_admin = login(client)

    r = client.post("/api/v1/approvals", json={
        "type": "LEAVE", "title": "请假一天", "content": "测试",
    }, headers=auth(t_eng))
    assert r.status_code == 200
    apid = r.json()["id"]

    # 工程师自己不能审批
    r = client.post(f"/api/v1/approvals/{apid}/approve", json={}, headers=auth(t_eng))
    assert r.status_code == 403

    r = client.post(f"/api/v1/approvals/{apid}/approve", json={"comment": "同意"}, headers=auth(t_disp))
    assert r.status_code == 200 and r.json()["current_step"] == 1

    r = client.post(f"/api/v1/approvals/{apid}/approve", json={"comment": "同意"}, headers=auth(t_admin))
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"


def test_twin_integration(client):
    """数字孪生对接：P1 直接生成紧急工单，P2~P4 生成报修单；设备状态同步（白名单免鉴权）。"""
    # 不带请求头直接下发（白名单模式）
    r = client.post("/api/v1/work-orders/external",
                    json={"deviceCode": "EQ-001", "alarmLevel": 1})
    assert r.status_code == 200

    # P2 告警 → 报修单
    r = client.post("/api/v1/work-orders/external",
                    json={"deviceCode": "EQ-002", "alarmLevel": 2},
                    headers={"X-API-Key": "twin-2026-secret"})
    assert r.status_code == 200 and r.json()["kind"] == "repair_request"

    # P1 告警 → 紧急工单
    r = client.post("/api/v1/work-orders/external",
                    json={"deviceCode": "EQ-002", "alarmLevel": 1},
                    headers={"X-API-Key": "twin-2026-secret"})
    assert r.status_code == 200 and r.json()["kind"] == "work_order"

    # 设备状态同步
    r = client.post("/api/v1/devices/sync-status",
                    json={"deviceCode": "EQ-003", "status": "ALARM"})
    assert r.status_code == 200 and r.json()["status"] == "ALARM"

    t_admin = login(client)
    r = client.get("/api/v1/devices", headers=auth(t_admin))
    dev = next(d for d in r.json() if d["code"] == "EQ-003")
    assert dev["status"] == "ALARM"


def test_permissions_and_modules(client):
    """模块权限：撤销工单管理权限后接口被拦截。"""
    t_admin = login(client)
    r = client.get("/api/v1/users", headers=auth(t_admin))
    e2 = next(u for u in r.json() if u["username"] == "engineer2")

    r = client.put(f"/api/v1/users/{e2['id']}", json={
        "real_name": e2["real_name"], "title": e2["title"], "role": "ENGINEER",
        "enabled": True, "permissions": ["dashboard"],
    }, headers=auth(t_admin))
    assert r.status_code == 200

    t_eng = login(client, "engineer2")
    r = client.get("/api/v1/work-orders", headers=auth(t_eng))
    assert r.status_code == 403

    # 恢复
    client.put(f"/api/v1/users/{e2['id']}", json={
        "real_name": e2["real_name"], "title": e2["title"], "role": "ENGINEER",
        "enabled": True,
        "permissions": ["dashboard", "orders", "repairs", "reports", "devices", "plans", "announce", "approvals", "files"],
    }, headers=auth(t_admin))


def test_change_password(client):
    """自助修改密码：旧密码验证 + 新密码生效。"""
    t_eng = login(client, "engineer3")
    r = client.post("/api/v1/auth/change-password", json={
        "old_password": "123456", "new_password": "654321",
    }, headers=auth(t_eng))
    assert r.status_code == 200

    # 旧密码失效，新密码可登录
    r = client.post("/api/v1/auth/login", json={"username": "engineer3", "password": "123456"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"username": "engineer3", "password": "654321"})
    assert r.status_code == 200

    # 管理员重置回初始密码
    t_admin = login(client)
    r = client.get("/api/v1/users", headers=auth(t_admin))
    e3 = next(u for u in r.json() if u["username"] == "engineer3")
    r = client.put(f"/api/v1/users/{e3['id']}/reset-password",
                   json={"new_password": "123456"}, headers=auth(t_admin))
    assert r.status_code == 200


def test_files_and_attachments(client):
    """文件共享与工单附件：上传 → 列表 → 下载 → 权限 → 删除。"""
    t_admin = login(client)
    t_disp = login(client, "dispatcher")
    t_eng = login(client, "engineer2")
    t_eng3 = login(client, "engineer3")

    # 上传共享文件（工程师上传，全员可见）
    r = client.post("/api/v1/files", files={"file": ("测试文档.txt", b"hello oatool", "text/plain")},
                    headers=auth(t_eng))
    assert r.status_code == 200
    fid = r.json()["id"]
    assert r.json()["category"] == "SHARED" and r.json()["name"] == "测试文档.txt"

    # 共享列表可见 + 下载内容一致
    r = client.get("/api/v1/files", headers=auth(t_admin))
    assert any(f["id"] == fid for f in r.json()["items"])
    r = client.get(f"/api/v1/files/{fid}/download", headers=auth(t_admin))
    assert r.status_code == 200 and r.content == b"hello oatool"

    # 工单附件：给技术员2派一张工单，技术员2 上传附件
    r = client.post("/api/v1/work-orders", json={
        "title": "附件测试工单", "order_type": "FAULT", "assignee_id": 4, "priority": "P3",
    }, headers=auth(t_disp))
    oid = r.json()["id"]
    r = client.post("/api/v1/files", data={"order_id": str(oid)},
                    files={"file": ("现场照片.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}, headers=auth(t_eng))
    assert r.status_code == 200 and r.json()["category"] == "ORDER"

    # 附件列表：本工单相关人可见
    r = client.get(f"/api/v1/files?order_id={oid}", headers=auth(t_eng))
    assert r.status_code == 200 and len(r.json()["items"]) == 1
    r = client.get(f"/api/v1/files?order_id={oid}", headers=auth(t_admin))
    assert r.status_code == 200

    # 无关工程师不可查看该工单附件
    r = client.get(f"/api/v1/files?order_id={oid}", headers=auth(t_eng3))
    assert r.status_code == 403

    # 删除权限：非上传者不可删，上传者可删
    r = client.delete(f"/api/v1/files/{fid}", headers=auth(t_eng3))
    assert r.status_code == 403
    r = client.delete(f"/api/v1/files/{fid}", headers=auth(t_eng))
    assert r.status_code == 200
    r = client.get(f"/api/v1/files/{fid}/download", headers=auth(t_admin))
    assert r.status_code == 404

    # 草稿附件：上传（draft=1）→ 仅本人可见 → 创建工单时自动绑定
    r = client.post("/api/v1/files", data={"draft": "1"},
                    files={"file": ("预上传图纸.pdf", b"draft-bytes", "application/pdf")}, headers=auth(t_disp))
    assert r.status_code == 200 and r.json()["category"] == "DRAFT"
    draft_id = r.json()["id"]
    # 本人草稿列表可见
    r = client.get("/api/v1/files?draft=1", headers=auth(t_disp))
    assert any(f["id"] == draft_id for f in r.json()["items"])
    # 他人看不到（列表隔离）
    r = client.get("/api/v1/files?draft=1", headers=auth(t_eng))
    assert not any(f["id"] == draft_id for f in r.json()["items"])
    # 他人下载/预览被拒（仅本人与管理员）
    r = client.get(f"/api/v1/files/{draft_id}/download", headers=auth(t_eng3))
    assert r.status_code == 403
    # 创建工单绑定草稿附件
    r = client.post("/api/v1/work-orders", json={
        "title": "草稿附件绑定测试", "draft_file_ids": [draft_id], "assignee_id": 5,
    }, headers=auth(t_disp))
    oid2 = r.json()["id"]
    r = client.get(f"/api/v1/files?order_id={oid2}", headers=auth(t_disp))
    names = [f["name"] for f in r.json()["items"]]
    assert "预上传图纸.pdf" in names and all(f["category"] == "ORDER" for f in r.json()["items"])

    # 管理员清空全部文件；工程师无权
    r = client.delete("/api/v1/files/all", headers=auth(t_eng))
    assert r.status_code == 403
    r = client.delete("/api/v1/files/all", headers=auth(t_admin))
    assert r.status_code == 200
    r = client.get("/api/v1/files", headers=auth(t_admin))
    assert r.json()["total"] == 0


def test_twin_sync(client):
    """孪生对接：API Key 拉取工单列表/详情 + 增量同步 + 管理端配置与日志。"""
    t_admin = login(client)
    t_disp = login(client, "dispatcher")
    H = {"X-API-Key": "twin-2026-secret"}

    # 白名单模式：不带任何请求头即可调用（兼容旧调用带任意 X-API-Key）
    r = client.get("/api/v1/twin/orders")
    assert r.status_code == 200

    # 孪生下发一张 P1 工单（复用 external）
    r = client.post("/api/v1/work-orders/external",
                    json={"deviceCode": "EQ-001", "alarmLevel": 1},
                    headers=H)
    assert r.status_code == 200
    order_no = r.json()["data"]["order_no"]
    order_id = r.json()["data"]["id"]

    # 拉取工单列表：能看到该工单
    r = client.get("/api/v1/twin/orders?page_size=50", headers=H)
    assert r.status_code == 200
    assert any(o["order_no"] == order_no for o in r.json()["items"])
    assert "updated_at" in r.json()["items"][0]

    # 状态过滤
    r = client.get("/api/v1/twin/orders?status=PENDING_ACCEPT&page_size=50", headers=H)
    assert r.status_code == 200
    assert all(o["status"] == "PENDING_ACCEPT" for o in r.json()["items"])

    # 增量拉取：未来时间应返回 0 条
    r = client.get("/api/v1/twin/orders?updated_after=2099-01-01T00:00:00", headers=H)
    assert r.status_code == 200 and r.json()["total"] == 0

    # 工单详情 + 日志
    r = client.get(f"/api/v1/twin/orders/{order_id}", headers=H)
    assert r.status_code == 200
    assert r.json()["order"]["order_no"] == order_no
    assert isinstance(r.json()["logs"], list)

    # 管理端：概览 + 日志 + 配置（管理员）
    r = client.get("/api/v1/twin/overview", headers=auth(t_admin))
    assert r.status_code == 200 and r.json()["total_orders"] > 0
    r = client.get("/api/v1/twin/logs?page_size=50", headers=auth(t_admin))
    actions = [x["action"] for x in r.json()["items"]]
    assert "孪生下发工单" in actions and "拉取工单列表" in actions
    r = client.put("/api/v1/twin/config", json={"twin_callback_url": "http://127.0.0.1:9/url"}, headers=auth(t_admin))
    assert r.status_code == 200
    r = client.get("/api/v1/twin/overview", headers=auth(t_admin))
    assert r.json()["callback_url"] == "http://127.0.0.1:9/url"
    # 清回空，避免影响其它用例
    client.put("/api/v1/twin/config", json={"twin_callback_url": ""}, headers=auth(t_admin))

    # 工程师无孪生对接模块权限
    t_eng = login(client, "engineer2")
    r = client.get("/api/v1/twin/overview", headers=auth(t_eng))
    assert r.status_code == 403

    # 指派工程师下发（P3 + assigneeUsername）→ 直接成单并派单，跳过报修审核
    r = client.post("/api/v1/work-orders/external", json={
        "deviceCode": "EQ-002", "alarmLevel": 3,
        "assigneeUsername": "engineer3", "priority": "P2", "orderType": "INSPECTION",
    }, headers=H)
    assert r.status_code == 200
    d = r.json()["data"]
    assert r.json()["kind"] == "work_order"
    assert d["status"] == "PENDING_ACCEPT" and d["assignee_name"] == "技术员3"
    assert d["priority"] == "P2" and d["order_type"] == "INSPECTION"

    # 指派不存在的工程师 → 400
    r = client.post("/api/v1/work-orders/external", json={
        "deviceCode": "EQ-002", "alarmLevel": 3, "assigneeUsername": "nobody",
    }, headers=H)
    assert r.status_code == 400

    # 工程师列表接口（孪生端下拉框用）
    r = client.get("/api/v1/twin/engineers", headers=H)
    assert r.status_code == 200
    assert any(u["username"] == "engineer3" for u in r.json()["items"])
    # 设备列表接口
    r = client.get("/api/v1/twin/devices", headers=H)
    assert r.status_code == 200
    assert any(x["code"] == "EQ-001" for x in r.json()["items"])

    # 报修单列表（孪生跟踪 P2~P4 下发的审核进展）
    r = client.post("/api/v1/work-orders/external",
                    json={"deviceCode": "EQ-003", "alarmLevel": 2},
                    headers=H)
    assert r.json()["kind"] == "repair_request"
    r = client.get("/api/v1/twin/repair-requests?status=PENDING_REVIEW", headers=H)
    assert r.status_code == 200 and r.json()["total"] >= 1
    item = r.json()["items"][0]
    assert "request_no" in item and "status_label" in item


def test_audit_logs(client):
    """审计日志记录了关键操作。"""
    t_admin = login(client)
    r = client.get("/api/v1/audit-logs?page=1&page_size=50", headers=auth(t_admin))
    assert r.status_code == 200
    actions = {item["action"] for item in r.json()["items"]}
    assert "LOGIN_SUCCESS" in actions
    assert {"ORDER_CREATE", "ORDER_DISPATCH", "ORDER_VERIFY"} & actions

    # 非管理员不可查看
    t_eng = login(client, "engineer2")
    r = client.get("/api/v1/audit-logs", headers=auth(t_eng))
    assert r.status_code == 403


def test_clear_all_orders_and_devices(client):
    """管理员清空全部工单与设备台账；工程师无权；顺序防呆。"""
    t_admin = login(client)
    t_eng = login(client, "engineer2")

    # 工程师无权
    r = client.delete("/api/v1/work-orders/all", headers=auth(t_eng))
    assert r.status_code == 403
    r = client.delete("/api/v1/devices/all", headers=auth(t_eng))
    assert r.status_code == 403

    # 有关联工单时清设备被拒（防呆）
    r = client.delete("/api/v1/devices/all", headers=auth(t_admin))
    assert r.status_code == 400

    # 清空全部工单（连带报修单）
    r = client.delete("/api/v1/work-orders/all", headers=auth(t_admin))
    assert r.status_code == 200 and r.json()["deleted_orders"] > 0
    r = client.get("/api/v1/work-orders?page=1&page_size=5", headers=auth(t_admin))
    assert r.json()["total"] == 0
    r = client.get("/api/v1/repair-requests?page=1&page_size=5", headers=auth(t_admin))
    assert r.json()["total"] == 0

    # 再清空设备（连带保养计划）
    r = client.delete("/api/v1/devices/all", headers=auth(t_admin))
    assert r.status_code == 200 and r.json()["deleted"] > 0
    r = client.get("/api/v1/devices", headers=auth(t_admin))
    assert r.json() == []
