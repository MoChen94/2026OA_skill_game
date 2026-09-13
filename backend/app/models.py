"""数据模型：部门 / 用户 / 设备 / 工单 / 工单流转日志。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# ---------- 角色 ----------
ROLE_ADMIN = "ADMIN"          # 管理员：全部权限，验收
ROLE_DISPATCHER = "DISPATCHER"  # 调度员：派单、验收
ROLE_ENGINEER = "ENGINEER"    # 工程师：接单、处理
ROLE_LABELS = {"ADMIN": "管理员", "DISPATCHER": "调度员", "ENGINEER": "工程师"}

# ---------- 功能模块权限 ----------
MODULES = {
    "dashboard": "工作台",
    "orders": "工单管理",
    "repairs": "报修管理",
    "reports": "报表中心",
    "devices": "设备台账",
    "plans": "保养计划",
    "announce": "公告通知",
    "approvals": "审批中心",
    "files": "文件共享",
    "twin": "孪生对接",
    "track": "工单跟踪",
    "chat": "在线沟通",
    "admin": "权限管理",
}
# 各角色创建账号时的默认模块权限（管理员始终拥有全部模块）
DEFAULT_MODULES = {
    ROLE_ADMIN: list(MODULES.keys()),
    ROLE_DISPATCHER: ["dashboard", "orders", "repairs", "reports", "devices", "plans", "announce", "approvals", "files", "twin", "track", "chat"],
    ROLE_ENGINEER: ["dashboard", "orders", "repairs", "reports", "devices", "plans", "announce", "approvals", "files", "chat"],
}

# ---------- 工单状态机 ----------
WO_PENDING_DISPATCH = "PENDING_DISPATCH"  # 待派发
WO_PENDING_ACCEPT = "PENDING_ACCEPT"      # 待接单
WO_PROCESSING = "PROCESSING"              # 处理中
WO_PENDING_VERIFY = "PENDING_VERIFY"      # 待验收
WO_COMPLETED = "COMPLETED"                # 已完成
WO_CANCELLED = "CANCELLED"                # 已取消
WO_STATUS_LABELS = {
    WO_PENDING_DISPATCH: "待派发",
    WO_PENDING_ACCEPT: "待接单",
    WO_PROCESSING: "处理中",
    WO_PENDING_VERIFY: "待验收",
    WO_COMPLETED: "已完成",
    WO_CANCELLED: "已取消",
}

# ---------- 工单类型 ----------
WO_TYPES = {"FAULT": "故障维修", "INSPECTION": "巡检", "MAINTENANCE": "保养", "TASK": "任务"}
WO_PRIORITIES = {"P1": "紧急", "P2": "高", "P3": "中", "P4": "低"}

# ---------- 设备状态 ----------
DEVICE_STATUS = {"RUNNING": "运行", "ALARM": "告警", "MAINTENANCE": "维修中", "OFFLINE": "停机"}

# ---------- 报修单状态（两段式：报修 → 审核立项 → 正式工单） ----------
RR_PENDING_REVIEW = "PENDING_REVIEW"  # 待审核
RR_APPROVED = "APPROVED"              # 已立项（已生成正式工单）
RR_REJECTED = "REJECTED"              # 已驳回
RR_WITHDRAWN = "WITHDRAWN"            # 已撤回
RR_STATUS_LABELS = {
    RR_PENDING_REVIEW: "待审核",
    RR_APPROVED: "已立项",
    RR_REJECTED: "已驳回",
    RR_WITHDRAWN: "已撤回",
}

# ---------- 通用审批流 ----------
AP_PENDING = "PENDING"      # 审批中
AP_APPROVED = "APPROVED"    # 已通过
AP_REJECTED = "REJECTED"    # 已驳回
AP_STATUS_LABELS = {AP_PENDING: "审批中", AP_APPROVED: "已通过", AP_REJECTED: "已驳回"}
# 审批类型与流转配置：按顺序逐级审批（角色）
APPROVAL_TYPES = {
    "LEAVE": {"label": "请假申请", "steps": ["DISPATCHER", "ADMIN"]},
    "REQUISITION": {"label": "领料申请", "steps": ["DISPATCHER"]},
    "PURCHASE": {"label": "采购申请", "steps": ["DISPATCHER", "ADMIN"]},
}


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    users: Mapped[list["User"]] = relationship(back_populates="department")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    real_name: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_ENGINEER)
    title: Mapped[str] = mapped_column(String(64), default="")  # 岗位，如"人工智能工程技术员"
    phone: Mapped[str] = mapped_column(String(32), default="")
    dept_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
    permissions: Mapped[str] = mapped_column(Text, default="")  # 可用的功能模块，逗号分隔
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    department: Mapped[Optional[Department]] = relationship(back_populates="users")

    @property
    def modules(self) -> list[str]:
        """当前用户可访问的功能模块键列表。"""
        return [m for m in (self.permissions or "").split(",") if m in MODULES]


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # 与数字孪生设备编号一致
    name: Mapped[str] = mapped_column(String(64))
    location: Mapped[str] = mapped_column(String(128), default="")
    twin_id: Mapped[str] = mapped_column(String(64), default="")  # 数字孪生模型/实体 ID
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # 设备档案（企业级字段）
    model: Mapped[str] = mapped_column(String(64), default="")        # 规格型号
    manufacturer: Mapped[str] = mapped_column(String(64), default="")  # 制造商
    purchase_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 购置日期
    warranty_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)      # 保修期(月)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    owner: Mapped[Optional[User]] = relationship()


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    order_type: Mapped[str] = mapped_column(String(16), default="FAULT")
    device_id: Mapped[Optional[int]] = mapped_column(ForeignKey("devices.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    alarm_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 孪生告警数据快照(JSON)
    priority: Mapped[str] = mapped_column(String(8), default="P3")
    status: Mapped[str] = mapped_column(String(32), default=WO_PENDING_DISPATCH, index=True)

    creator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    dispatcher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("maintenance_plans.id"), nullable=True)  # 保养计划来源

    dispatch_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    accept_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finish_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    verify_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 任何字段变更（派单/接单/完成/验收/取消...）时自动刷新，供孪生增量同步
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    device: Mapped[Optional[Device]] = relationship()
    creator: Mapped[Optional[User]] = relationship(foreign_keys=[creator_id])
    dispatcher: Mapped[Optional[User]] = relationship(foreign_keys=[dispatcher_id])
    assignee: Mapped[Optional[User]] = relationship(foreign_keys=[assignee_id])
    logs: Mapped[list["WorkOrderLog"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="WorkOrderLog.id"
    )


class WorkOrderLog(Base):
    __tablename__ = "work_order_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), index=True)
    operator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    order: Mapped[WorkOrder] = relationship(back_populates="logs")
    operator: Mapped[Optional[User]] = relationship()


class RepairRequest(Base):
    """报修单：工程师/数字孪生提报，调度员审核立项后生成正式工单。"""
    __tablename__ = "repair_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    device_id: Mapped[Optional[int]] = mapped_column(ForeignKey("devices.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    alarm_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 孪生告警数据快照(JSON)
    priority: Mapped[str] = mapped_column(String(8), default="P3")
    status: Mapped[str] = mapped_column(String(32), default=RR_PENDING_REVIEW, index=True)

    creator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    review_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    work_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("work_orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    device: Mapped[Optional[Device]] = relationship()
    creator: Mapped[Optional[User]] = relationship(foreign_keys=[creator_id])
    reviewer: Mapped[Optional[User]] = relationship(foreign_keys=[reviewer_id])
    work_order: Mapped[Optional[WorkOrder]] = relationship()


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, default="")
    publisher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_top: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    publisher: Mapped[Optional[User]] = relationship()


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Approval(Base):
    """通用审批单：按配置的审批链逐级流转。"""
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, default="")
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default=AP_PENDING, index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    applicant: Mapped[User] = relationship()
    steps: Mapped[list["ApprovalStep"]] = relationship(
        back_populates="approval", cascade="all, delete-orphan", order_by="ApprovalStep.step_index"
    )


class ApprovalStep(Base):
    __tablename__ = "approval_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # 本环节审批角色
    approver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=AP_PENDING)
    comment: Mapped[str] = mapped_column(Text, default="")
    acted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    approval: Mapped[Approval] = relationship(back_populates="steps")
    approver: Mapped[Optional[User]] = relationship()


class MaintenancePlan(Base):
    """定期保养计划：到期自动生成保养工单。"""
    __tablename__ = "maintenance_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
    cycle_days: Mapped[int] = mapped_column(Integer, default=30)   # 保养周期(天)
    next_due_date: Mapped[datetime] = mapped_column(DateTime)       # 下次应执行日期
    last_run_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # 默认执行工程师
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    device: Mapped[Device] = relationship()
    owner: Mapped[Optional[User]] = relationship()


class AuditLog(Base):
    """操作审计日志。"""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(32), default="系统")
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class FileRecord(Base):
    """文件库：工单附件（category=ORDER）+ 公司内文件共享（category=SHARED）。

    文件实体存磁盘 data/uploads/，这里只记录元数据。
    """
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255))       # 原始文件名
    stored_name: Mapped[str] = mapped_column(String(64), unique=True)  # 磁盘上的 uuid 文件名
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    category: Mapped[str] = mapped_column(String(16), default="SHARED", index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("work_orders.id"), nullable=True, index=True)
    uploader_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    uploader: Mapped[Optional[User]] = relationship()


class SystemConfig(Base):
    """系统 KV 配置：孪生回调地址 / API Key 等，管理页面可直接修改，无需重启。"""
    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ChatMessage(Base):
    """在线沟通（全员群）消息：纯文字 + @提及。"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    mentions: Mapped[str] = mapped_column(Text, default="")  # 被@的用户ID，逗号分隔
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    sender: Mapped[Optional["User"]] = relationship()


class ChatRead(Base):
    """在线沟通已读水位：每人读到的最大消息ID。"""
    __tablename__ = "chat_reads"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    last_read_msg_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class TwinSyncLog(Base):
    """数字孪生对接日志：IN=孪生调用OA接口，OUT=OA回调孪生。"""
    __tablename__ = "twin_sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    direction: Mapped[str] = mapped_column(String(8), index=True)   # IN / OUT
    action: Mapped[str] = mapped_column(String(48))                 # 下发工单/拉取列表/状态回调/设备同步...
    detail: Mapped[str] = mapped_column(Text, default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
