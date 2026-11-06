import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.db.models import Conversation, Message, Run
from life_agent.modules.runs.service import create_run
from life_agent.modules.wiki import service

router = APIRouter(prefix="/wiki")


@router.post("/documents", dependencies=[Depends(require_trusted_origin)])
async def upload_document(
    conversation_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    db: Database,
    current_user: CurrentUser,
):
    try:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.owner_id != current_user.id:
            raise HTTPException(404, detail="对话不存在。")
        item = service.upload(db, current_user.id, file.filename or "upload.txt", await file.read())
        run = None
        if item.status != "ready":
            message = db.scalar(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.client_message_id == f"wiki:{item.id}",
                )
            )
            if message is None:
                message = Message(
                    conversation_id=conversation_id,
                    client_message_id=f"wiki:{item.id}",
                    role="user",
                    content=f"上传资料：{item.filename}",
                )
                db.add(message)
                db.flush()
                run = create_run(
                    db,
                    current_user.id,
                    None,
                    None,
                    f"wiki:{item.id}",
                    "wiki_index",
                    input_message_id=message.id,
                    decision={"kind": "wiki_index", "capability_ids": [], "wiki_document_id": str(item.id)},
                    commit=False,
                )
                message.run_id = run.id
                db.commit()
                db.refresh(run)
            else:
                run = db.scalar(select(Run).where(Run.id == message.run_id))
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"id": item.id, "filename": item.filename, "status": item.status, "run": {"id": run.id, "status": run.status} if run else None}
@router.get("/documents")
def documents(db: Database, current_user: CurrentUser): return [{"id": x.id,"filename":x.filename,"status":x.status,"created_at":x.created_at} for x in service.list_documents(db,current_user.id)]
@router.get("/pages")
def pages(db: Database, current_user: CurrentUser): return service.list_pages(db, current_user.id)
@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_trusted_origin)])
def remove(document_id: uuid.UUID, db: Database, current_user: CurrentUser):
    try: service.delete(db,current_user.id,document_id)
    except LookupError as exc: raise HTTPException(404, detail="资料不存在。") from exc
