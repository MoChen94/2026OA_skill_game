"""通用审批流：申请 → 按配置的审批链逐级审批（通过/驳回）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_module
from ..schemas import ApprovalActIn, ApprovalIn
from ..services import audit, notify_users

router = APIRouter(prefix="/approvals", tags=["审批中心"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)


def gen_no(db: Session) -> str:
    date = datetime.now().strftime("%Y%m%d")
    prefix = f"AP{date}-"
    count = db.query(models.Approval).filter(models.Approval.no.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


def _to_dict(db: Session, ap: models.Approval) -> dict:
    return {
        "id": ap.id,
        "no": ap.no,
        "type": ap.type,
        "type_label": models.APPROVAL_TYPES.get(ap.type, {}).get("label", ap.type),
        "title": ap.title,
        "content": ap.content,
        "applicant_name": ap.applicant.real_name,
        "applicant_title": ap.applicant.title,
        "status": ap.status,
        "status_label": models.AP_STATUS_LABELS.get(ap.status, ap.status),
        "current_step": ap.current_step,
        "steps": [
            {
                "step_index": s.step_index,
                "role": s.role,
                "role_label": models.ROLE_LABELS.get(s.role, s.role),
                "approver_name": s.approver.real_name if s.approver else None,
                "status": s.status,
                "status_label": models.AP_STATUS_LABELS.get(s.status, s.status),
                "comment": s.comment,
                "acted_at": s.acted_at.isoformat(timespec="minutes") if s.acted_at else None,
            }
            for s in ap.steps
        ],
        "created_at": ap.created_at.isoformat(timespec="minutes"),
    }


@router.post("")
def create_approval(
    payload: ApprovalIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("approvals")),
):
    if payload.type not in models.APPROVAL_TYPES:
        raise HTTPException(400, "审批类型不存在")
    ap = models.Approval(
        no=gen_no(db), type=payload.type, title=payload.title,
        content=payload.content, applicant_id=user.id,
    )
    for idx, role in enumerate(models.APPROVAL_TYPES[payload.type]["steps"]):
        ap.steps.append(models.ApprovalStep(step_index=idx, role=role))
    db.add(ap)
    audit(db, user, "APPROVAL_CREATE", f"提交{models.APPROVAL_TYPES[payload.type]['label']} {ap.no}：{ap.title}")
    db.commit()
    db.refresh(ap)
    first_role = models.APPROVAL_TYPES[payload.type]["steps"][0]
    notify_users(
        db, "approval_created",
        f"{user.real_name} 提交了{models.APPROVAL_TYPES[payload.type]['label']} {ap.no}，待审批",
        target_roles=(first_role,),
        extra={"approvalNo": ap.no},
    )
    return _to_dict(db, ap)


@router.get("")
def list_approvals(
    tab: str = Query(default="mine"),  # mine=我的申请 / todo=待我审批 / all=全部(管理)
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("approvals")),
):
    q = db.query(models.Approval)
    if tab == "mine":
        q = q.filter(models.Approval.applicant_id == user.id)
    elif tab == "todo":
        if user.role not in _MANAGERS:
            return {"total": 0, "items": []}
        # 当前环节角色匹配本人（管理员可代审任意环节）
        ids = (
            db.query(models.ApprovalStep.approval_id)
            .join(models.Approval, models.ApprovalStep.approval_id == models.Approval.id)
            .filter(
                models.Approval.status == models.AP_PENDING,
                models.ApprovalStep.step_index == models.Approval.current_step,
                models.ApprovalStep.status == models.AP_PENDING,
                (
                    (models.ApprovalStep.role == user.role)
                    if user.role != models.ROLE_ADMIN
                    else True
                ),
            )
            .distinct()
            .all()
        )
        q = q.filter(models.Approval.id.in_([i[0] for i in ids]))
    elif tab == "all":
        if user.role not in _MANAGERS:
            raise HTTPException(403, "无权限查看全部审批")
    else:
        raise HTTPException(400, "tab 参数不合法")

    total = q.count()
    items = (
        q.order_by(models.Approval.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": [_to_dict(db, ap) for ap in items]}


@router.get("/{apid}")
def get_approval(
    apid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("approvals")),
):
    ap = db.get(models.Approval, apid)
    if ap is None:
        raise HTTPException(404, "审批单不存在")
    if user.role not in _MANAGERS and ap.applicant_id != user.id:
        raise HTTPException(403, "无权查看该审批单")
    return _to_dict(db, ap)


@router.post("/{apid}/approve")
def approve(
    apid: int,
    payload: ApprovalActIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("approvals")),
):
    ap = db.get(models.Approval, apid)
    if ap is None:
        raise HTTPException(404, "审批单不存在")
    if ap.status != models.AP_PENDING:
        raise HTTPException(400, "该审批单已结束")
    step = next((s for s in ap.steps if s.step_index == ap.current_step), None)
    if step is None:
        raise HTTPException(400, "审批链配置异常")
    if user.role != step.role and user.role != models.ROLE_ADMIN:
        raise HTTPException(403, "当前环节不属于你的审批权限")

    step.status = models.AP_APPROVED
    step.approver_id = user.id
    step.comment = payload.comment
    step.acted_at = datetime.now()
    ap.current_step += 1

    if ap.current_step >= len(ap.steps):
        ap.status = models.AP_APPROVED
        message = f"你的{models.APPROVAL_TYPES[ap.type]['label']} {ap.no} 已全部审批通过"
    else:
        next_role = ap.steps[ap.current_step].role
        notify_users(
            db, "approval_step",
            f"{models.APPROVAL_TYPES[ap.type]['label']} {ap.no} 流转到下一环节，待审批",
            target_roles=(next_role,),
            extra={"approvalNo": ap.no},
        )
        message = None
    audit(db, user, "APPROVAL_APPROVE", f"{ap.no} 第 {step.step_index + 1} 级审批通过：{payload.comment}")
    db.commit()
    if message:
        notify_users(
            db, "approval_approved",
            message,
            target_ids={ap.applicant_id},
            extra={"approvalNo": ap.no},
        )
    return _to_dict(db, ap)


@router.post("/{apid}/reject")
def reject(
    apid: int,
    payload: ApprovalActIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("approvals")),
):
    ap = db.get(models.Approval, apid)
    if ap is None:
        raise HTTPException(404, "审批单不存在")
    if ap.status != models.AP_PENDING:
        raise HTTPException(400, "该审批单已结束")
    step = next((s for s in ap.steps if s.step_index == ap.current_step), None)
    if step is None:
        raise HTTPException(400, "审批链配置异常")
    if user.role != step.role and user.role != models.ROLE_ADMIN:
        raise HTTPException(403, "当前环节不属于你的审批权限")

    step.status = models.AP_REJECTED
    step.approver_id = user.id
    step.comment = payload.comment
    step.acted_at = datetime.now()
    ap.status = models.AP_REJECTED
    audit(db, user, "APPROVAL_REJECT", f"{ap.no} 驳回：{payload.comment}")
    db.commit()
    notify_users(
        db, "approval_rejected",
        f"你的{models.APPROVAL_TYPES[ap.type]['label']} {ap.no} 被驳回：{payload.comment or '未说明原因'}",
        target_ids={ap.applicant_id},
        extra={"approvalNo": ap.no},
    )
    return _to_dict(db, ap)
