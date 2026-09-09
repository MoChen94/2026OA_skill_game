"""文件共享与工单附件接口。

- 共享文件（category=SHARED）：所有登录用户可上传/列表/下载，删除仅限上传者或管理员；
- 工单附件（category=ORDER）：绑定工单，上传/查看需要该工单的可见权限
  （管理员/调度员，或工单的创建人/被指派工程师）。

文件实体存磁盘 data/uploads/（uuid 文件名），数据库只保存元数据。
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config, models
from ..database import get_db
from ..deps import require_module, require_roles
from ..services import audit

router = APIRouter(prefix="/files", tags=["文件共享"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)
_MAX_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024


def _file_dir() -> Path:
    d = Path(config.UPLOAD_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _to_dict(f: models.FileRecord) -> dict:
    return {
        "id": f.id,
        "name": f.original_name,
        "size": f.size,
        "content_type": f.content_type,
        "category": f.category,
        "category_label": {"ORDER": "工单附件", "DRAFT": "待提交附件"}.get(f.category, "共享文件"),
        "order_id": f.order_id,
        "uploader_id": f.uploader_id,
        "uploader_name": f.uploader.real_name if f.uploader else "系统",
        "created_at": f.created_at.isoformat(timespec="minutes"),
        "is_image": (f.content_type or "").startswith("image/"),
    }


def _get_file(db: Session, fid: int) -> models.FileRecord:
    f = db.get(models.FileRecord, fid)
    if f is None:
        raise HTTPException(404, "文件不存在")
    return f


def _can_view_file(db: Session, user: models.User, f: models.FileRecord) -> bool:
    """共享文件全员可见；草稿附件仅本人/管理员；工单附件要求该工单的可见权限。"""
    if f.category == "DRAFT":
        return user.role == models.ROLE_ADMIN or f.uploader_id == user.id
    if f.category != "ORDER":
        return True
    order = db.get(models.WorkOrder, f.order_id) if f.order_id else None
    if order is None:
        return False
    if user.role in _MANAGERS:
        return True
    return user.id in (order.creator_id, order.assignee_id)


@router.post("")
async def upload_file(
    file: UploadFile,
    order_id: int | None = Form(default=None),
    draft: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("files")),
):
    """上传文件。带 order_id=工单附件；draft=1=新建工单前的草稿附件；否则=共享文件库。"""
    order = None
    if order_id is not None:
        order = db.get(models.WorkOrder, order_id)
        if order is None:
            raise HTTPException(404, "工单不存在")
        if not (user.role in _MANAGERS or user.id in (order.creator_id, order.assignee_id)):
            raise HTTPException(403, "无权向该工单上传附件")

    original = Path(file.filename or "").name.strip()  # 去掉路径成分，防路径穿越
    if not original:
        raise HTTPException(400, "文件名为空")
    ext = Path(original).suffix[:16]

    stored = uuid.uuid4().hex + ext
    dest = _file_dir() / stored
    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_BYTES:
                    raise HTTPException(413, f"文件超过 {config.MAX_UPLOAD_MB}MB 大小限制")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, "保存文件失败")
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "不能上传空文件")

    rec = models.FileRecord(
        original_name=original,
        stored_name=stored,
        size=size,
        content_type=file.content_type or "application/octet-stream",
        category="ORDER" if order_id is not None else ("DRAFT" if draft else "SHARED"),
        order_id=order_id,
        uploader_id=user.id,
    )
    db.add(rec)
    audit(db, user, "FILE_UPLOAD",
          f"上传文件 {original}（{size} 字节）" + (f"，绑定工单 {order.order_no}" if order else ""))
    db.commit()
    db.refresh(rec)
    return _to_dict(rec)


@router.get("")
def list_files(
    order_id: int | None = Query(default=None),
    draft: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("files")),
):
    """文件列表：order_id=工单附件；draft=1=我的草稿附件；否则=共享文件库。"""
    q = db.query(models.FileRecord)
    if draft:
        q = q.filter(models.FileRecord.category == "DRAFT",
                     models.FileRecord.uploader_id == user.id)
    elif order_id is not None:
        order = db.get(models.WorkOrder, order_id)
        if order is None:
            raise HTTPException(404, "工单不存在")
        if not (user.role in _MANAGERS or user.id in (order.creator_id, order.assignee_id)):
            raise HTTPException(403, "无权查看该工单附件")
        q = q.filter(models.FileRecord.order_id == order_id)
    else:
        q = q.filter(models.FileRecord.category == "SHARED")
    total = q.count()
    items = (
        q.order_by(models.FileRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": [_to_dict(f) for f in items]}


@router.delete("/all")
def clear_all(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    """清空全部文件（共享文件 + 工单附件）：删除磁盘文件与记录，仅管理员。"""
    files = db.query(models.FileRecord).all()
    for f in files:
        (_file_dir() / f.stored_name).unlink(missing_ok=True)
        db.delete(f)
    audit(db, user, "FILE_CLEAR_ALL", f"清空全部文件（{len(files)} 个）")
    db.commit()
    return {"ok": True, "deleted": len(files)}


@router.get("/{fid}/download")
def download(
    fid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("files")),
):
    """下载文件（以原始文件名保存）。"""
    f = _get_file(db, fid)
    if not _can_view_file(db, user, f):
        raise HTTPException(403, "无权下载该文件")
    path = _file_dir() / f.stored_name
    if not path.exists():
        raise HTTPException(404, "文件已丢失")
    return FileResponse(path, filename=f.original_name, media_type=f.content_type)


@router.get("/{fid}/content")
def content(
    fid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("files")),
):
    """在线预览（浏览器内直接打开图片等）。"""
    f = _get_file(db, fid)
    if not _can_view_file(db, user, f):
        raise HTTPException(403, "无权预览该文件")
    path = _file_dir() / f.stored_name
    if not path.exists():
        raise HTTPException(404, "文件已丢失")
    return FileResponse(path, media_type=f.content_type or "application/octet-stream")


@router.delete("/{fid}")
def delete(
    fid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("files")),
):
    """删除文件：仅上传者本人或管理员。"""
    f = _get_file(db, fid)
    if user.role != models.ROLE_ADMIN and f.uploader_id != user.id:
        raise HTTPException(403, "只能删除自己上传的文件")
    path = _file_dir() / f.stored_name
    path.unlink(missing_ok=True)
    audit(db, user, "FILE_DELETE", f"删除文件 {f.original_name}")
    db.delete(f)
    db.commit()
    return {"ok": True}
