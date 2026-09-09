"""初始化数据：首次启动时自动建表并写入演示数据（已有数据则跳过）。

同时负责轻量迁移：为老数据库的 users 表补充 title 列。
"""
from datetime import datetime, timedelta

from sqlalchemy import text

from . import models
from .database import Base, SessionLocal, engine
from .security import hash_password
from .services import add_log, gen_order_no, gen_request_no


def _add_order(db, order: models.WorkOrder, logs: list[tuple]) -> models.WorkOrder:
    """先落库拿到 ID，再写流转日志。"""
    db.add(order)
    db.flush()
    for operator, action, detail in logs:
        add_log(db, order, operator, action, detail)
    return order


def _migrate(db) -> None:
    """轻量迁移：为老数据库补充后加的列，并按角色回填默认模块权限。"""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(users)"))]
    if "title" not in cols:
        db.execute(text("ALTER TABLE users ADD COLUMN title VARCHAR(64) DEFAULT ''"))
    if "permissions" not in cols:
        db.execute(text("ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT ''"))
        for role, mods in models.DEFAULT_MODULES.items():
            db.execute(
                text("UPDATE users SET permissions = :p WHERE role = :r"),
                {"p": ",".join(mods), "r": role},
            )
    # 新增模块（如文件共享/孪生对接）后，为已有账号补齐模块权限
    for u in db.query(models.User).all():
        mods = [m for m in (u.permissions or "").split(",") if m]
        if "files" not in mods:
            mods.append("files")
        # 孪生对接仅调度员/管理员默认开通
        if "twin" not in mods and u.role in (models.ROLE_ADMIN, models.ROLE_DISPATCHER):
            mods.append("twin")
        u.permissions = ",".join(mods)
    # 老库工单表补 updated_at 列（供孪生增量同步），回填为最后变更时间
    wo_cols = [row[1] for row in db.execute(text("PRAGMA table_info(work_orders)"))]
    if "updated_at" not in wo_cols:
        db.execute(text("ALTER TABLE work_orders ADD COLUMN updated_at DATETIME"))
        db.execute(text(
            "UPDATE work_orders SET updated_at = "
            "COALESCE(verify_time, cancel_time, finish_time, accept_time, dispatch_time, created_at)"
        ))
    db.commit()


def ensure_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _migrate(db)
        if db.query(models.User).count() > 0:
            return

        dept_ops = models.Department(name="设备运维部", description="负责设备维修、巡检与保养")
        dept_prod = models.Department(name="生产制造部", description="一线生产与设备操作")
        dept_admin = models.Department(name="综合管理部", description="行政、调度与综合事务")
        db.add_all([dept_ops, dept_prod, dept_admin])
        db.flush()

        pw = "123456"
        users = [
            models.User(username="admin", password_hash=hash_password(pw),
                        real_name="系统管理员", role=models.ROLE_ADMIN,
                        phone="13800000001", dept_id=dept_admin.id,
                        permissions=",".join(models.DEFAULT_MODULES[models.ROLE_ADMIN])),
            models.User(username="dispatcher", password_hash=hash_password(pw),
                        real_name="王调度", role=models.ROLE_DISPATCHER,
                        phone="13800000002", dept_id=dept_admin.id,
                        permissions=",".join(models.DEFAULT_MODULES[models.ROLE_DISPATCHER])),
            models.User(username="engineer1", password_hash=hash_password(pw),
                        real_name="技术员1", role=models.ROLE_DISPATCHER,  # 调度员身份
                        title="物联网工程技术员", phone="13800000003", dept_id=dept_ops.id,
                        permissions=",".join(models.DEFAULT_MODULES[models.ROLE_DISPATCHER])),
            models.User(username="engineer2", password_hash=hash_password(pw),
                        real_name="技术员2", role=models.ROLE_ENGINEER,
                        title="物联网安装调试员", phone="13800000004", dept_id=dept_ops.id,
                        permissions=",".join(models.DEFAULT_MODULES[models.ROLE_ENGINEER])),
            models.User(username="engineer3", password_hash=hash_password(pw),
                        real_name="技术员3", role=models.ROLE_ENGINEER,
                        title="人工智能工程技术员", phone="13800000005", dept_id=dept_ops.id,
                        permissions=",".join(models.DEFAULT_MODULES[models.ROLE_ENGINEER])),
            models.User(username="engineer4", password_hash=hash_password(pw),
                        real_name="技术员4", role=models.ROLE_ENGINEER,
                        title="机器人工程技术员", phone="13800000006", dept_id=dept_ops.id,
                        permissions=",".join(models.DEFAULT_MODULES[models.ROLE_ENGINEER])),
        ]
        db.add_all(users)
        db.flush()
        admin, dispatcher, t1, t2, t3, t4 = users

        devices = [
            models.Device(code="EQ-001", name="数控机床 CNC-01", location="一号车间-1F",
                          twin_id="cnc-01", status="ALARM", owner_id=t3.id,
                          description="五轴联动加工中心，负责关键零件精加工"),
            models.Device(code="EQ-002", name="工业机器人 RB-02", location="一号车间-2F",
                          twin_id="robot-02", status="RUNNING", owner_id=t2.id,
                          description="六轴焊接机器人，承担车身焊接工序"),
            models.Device(code="EQ-003", name="空压机 AC-03", location="动力站房",
                          twin_id="ac-03", status="RUNNING", owner_id=t4.id,
                          description="全厂压缩空气供应主机"),
            models.Device(code="EQ-004", name="输送线 CV-04", location="一号车间-1F",
                          twin_id="cv-04", status="RUNNING", owner_id=t2.id,
                          description="零件传送带，连接上下道工序"),
            models.Device(code="EQ-005", name="AGV 小车 AGV-05", location="仓储区",
                          twin_id="agv-05", status="OFFLINE", owner_id=t4.id,
                          description="物料自动搬运小车"),
        ]
        db.add_all(devices)
        db.flush()
        cnc, robot, ac, cv, agv = devices

        now = datetime.now()

        # 示例工单 1：待派发（孪生告警）
        _add_order(db, models.WorkOrder(
            order_no=gen_order_no(db), title=f"[{cnc.name}] 主轴温度过高告警",
            order_type="FAULT", device_id=cnc.id,
            description="数字孪生系统监测到 CNC-01 主轴温度 98.5°C，超过阈值 85°C，请尽快处理。",
            alarm_data='{"temp": 98.5, "threshold": 85.0, "zone": "spindle", "ts": "2026-09-02T08:30:00"}',
            priority="P1", creator_id=None, created_at=now - timedelta(hours=1),
            status=models.WO_PENDING_DISPATCH,
        ), [(None, "CREATE", "数字孪生系统自动下发：主轴温度过高")])

        # 示例工单 2：待接单（已派给技术员2）
        _add_order(db, models.WorkOrder(
            order_no=gen_order_no(db), title=f"[{cv.name}] 例行巡检",
            order_type="INSPECTION", device_id=cv.id,
            description="按计划对输送线进行每日例行巡检，重点检查皮带张紧度与电机异响。",
            priority="P3", creator_id=dispatcher.id, assignee_id=t2.id,
            dispatcher_id=dispatcher.id, dispatch_time=now - timedelta(hours=2),
            created_at=now - timedelta(hours=2),
            status=models.WO_PENDING_ACCEPT,
        ), [
            (dispatcher, "CREATE", "调度创建巡检工单"),
            (dispatcher, "DISPATCH", f"派单给 {t2.real_name}"),
        ])

        # 示例工单 3：处理中（技术员3）
        _add_order(db, models.WorkOrder(
            order_no=gen_order_no(db), title=f"[{robot.name}] 季度保养",
            order_type="MAINTENANCE", device_id=robot.id,
            description="按保养计划对焊接机器人进行季度保养：润滑、紧固、精度校准。",
            priority="P2", creator_id=dispatcher.id, assignee_id=t3.id,
            dispatcher_id=dispatcher.id, dispatch_time=now - timedelta(days=1, hours=3),
            accept_time=now - timedelta(days=1, hours=1),
            created_at=now - timedelta(days=1, hours=3),
            status=models.WO_PROCESSING,
        ), [
            (dispatcher, "CREATE", "调度创建保养工单"),
            (dispatcher, "DISPATCH", f"派单给 {t3.real_name}"),
            (t3, "ACCEPT", "接单，开始保养作业"),
        ])

        # 示例工单 4：待验收（技术员4）
        _add_order(db, models.WorkOrder(
            order_no=gen_order_no(db), title=f"[{ac.name}] 出气压力不足故障处理",
            order_type="FAULT", device_id=ac.id,
            description="空压机出气压力 0.55MPa 低于正常值，已更换进气滤芯并检查管路。",
            priority="P2", creator_id=None, assignee_id=t4.id,
            dispatch_time=now - timedelta(hours=6), accept_time=now - timedelta(hours=5),
            finish_time=now - timedelta(hours=2),
            created_at=now - timedelta(hours=6),
            status=models.WO_PENDING_VERIFY,
        ), [
            (None, "CREATE", "数字孪生系统自动下发：出气压力不足"),
            (dispatcher, "DISPATCH", f"派单给 {t4.real_name}"),
            (t4, "ACCEPT", "接单，开始排查"),
            (t4, "COMPLETE", "更换滤芯并重新标定压力开关，试机正常"),
        ])

        # 示例工单 5：已完成（技术员2）
        _add_order(db, models.WorkOrder(
            order_no=gen_order_no(db), title=f"[{agv.name}] 电池充电异常检修",
            order_type="FAULT", device_id=agv.id,
            description="AGV-05 充电时反复中断，更换充电接口后恢复正常。",
            priority="P3", creator_id=None, assignee_id=t2.id,
            dispatch_time=now - timedelta(days=2), accept_time=now - timedelta(days=1, hours=23),
            finish_time=now - timedelta(days=1, hours=20), verify_time=now - timedelta(days=1, hours=18),
            created_at=now - timedelta(days=2),
            status=models.WO_COMPLETED,
        ), [
            (None, "CREATE", "数字孪生系统自动下发：电池充电异常"),
            (dispatcher, "DISPATCH", f"派单给 {t2.real_name}"),
            (t2, "ACCEPT", "接单，检查充电桩与小车接口"),
            (t2, "COMPLETE", "更换充电接口模块，连续充电测试正常"),
            (admin, "VERIFY_PASS", "验收通过"),
        ])

        # 示例报修单：待审核（技术员2 提报）
        db.add(models.RepairRequest(
            request_no=gen_request_no(db), title=f"[{cv.name}] 皮带跑偏报修",
            device_id=cv.id,
            description="输送线皮带出现跑偏现象，边缘磨损加重，请求检修调整。",
            priority="P3", creator_id=t2.id,
            created_at=now - timedelta(minutes=30),
        ))

        db.commit()
        print("[seed] 初始化数据完成：6 个账号 / 5 台设备 / 5 张示例工单 / 1 张示例报修单")
    finally:
        db.close()
