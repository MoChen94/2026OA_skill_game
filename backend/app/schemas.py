"""接口请求/响应参数模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class UserCreateIn(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    real_name: str
    role: str = "ENGINEER"
    title: str = ""
    phone: str = ""
    dept_id: Optional[int] = None
    permissions: Optional[list[str]] = None  # 不传则按角色给默认模块


class UserUpdateIn(BaseModel):
    """管理员修改用户：角色 / 岗位 / 模块权限 / 启用状态。"""
    real_name: str = ""
    title: str = ""
    role: str = "ENGINEER"
    phone: str = ""
    enabled: bool = True
    permissions: Optional[list[str]] = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=64)


class DeviceIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    location: str = ""
    twin_id: str = ""
    status: str = "RUNNING"
    owner_id: Optional[int] = None
    description: str = ""
    model: str = ""
    manufacturer: str = ""
    purchase_date: Optional[datetime] = None
    warranty_months: Optional[int] = None


class WorkOrderCreateIn(BaseModel):
    """登录用户手动创建工单。"""
    title: str = Field(min_length=1, max_length=128)
    order_type: str = "TASK"
    device_id: Optional[int] = None
    description: str = ""
    priority: str = "P3"
    assignee_id: Optional[int] = None  # 指定工程师时创建后直接派单
    draft_file_ids: Optional[list[int]] = None  # 新建表单里预上传的草稿附件，创建后自动绑定


class WorkOrderExternalIn(BaseModel):
    """数字孪生系统下发工单（免鉴权白名单模式）。字段与 OA 网页新建工单对齐。"""
    deviceCode: str
    alarmLevel: int = Field(default=3, ge=1, le=4)
    title: str = ""
    description: str = ""
    location: str = ""
    sensorSnapshot: Optional[dict] = None
    # 对接增强：孪生端可像 OA 调度员一样指派与自定义工单属性
    assigneeUsername: str = ""                    # 指派工程师账号（如 engineer2）；指定后直接生成工单并派单（视为已审核）
    priority: str = ""                            # 优先级 P1~P4，不传按 alarmLevel 映射（1→P1 ... 4→P4）
    orderType: str = ""                           # 工单类型 FAULT/INSPECTION/MAINTENANCE/TASK，默认 FAULT


class DispatchIn(BaseModel):
    assignee_id: int


class CompleteIn(BaseModel):
    result: str = ""


class VerifyIn(BaseModel):
    passed: bool
    comment: str = ""


class CancelIn(BaseModel):
    reason: str = ""


class RepairRequestIn(BaseModel):
    """工程师报修。"""
    title: str = Field(min_length=1, max_length=128)
    device_id: Optional[int] = None
    description: str = ""
    priority: str = "P3"


class RepairApproveIn(BaseModel):
    """调度员审核立项：生成正式工单。"""
    priority: str = "P3"
    order_type: str = "FAULT"
    assignee_id: Optional[int] = None  # 指定工程师则立项后直接派单
    review_comment: str = ""


class RepairRejectIn(BaseModel):
    review_comment: str = ""


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    content: str = ""
    is_top: bool = False


class ApprovalIn(BaseModel):
    type: str
    title: str = Field(min_length=1, max_length=128)
    content: str = ""


class ApprovalActIn(BaseModel):
    comment: str = ""


class MaintenancePlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    device_id: int
    cycle_days: int = Field(default=30, ge=1, le=3650)
    next_due_date: Optional[datetime] = None  # 不传则按周期顺延（新建时默认今天）
    owner_id: Optional[int] = None
    enabled: bool = True
    description: str = ""


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class DeviceStatusSyncIn(BaseModel):
    """数字孪生推送设备状态（X-API-Key 鉴权）。"""
    deviceCode: str
    status: str
