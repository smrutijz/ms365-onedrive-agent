from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List

from src.clients.mailHelper import MailClient
from src.api.deps import get_mail_client

router = APIRouter(prefix="/mail")


# ── Request bodies ─────────────────────────────────────────────────────────────

class SendMailBody(BaseModel):
    to: List[str]
    subject: str
    body: str
    body_type: str = "HTML"   # HTML | Text
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None

class ReplyBody(BaseModel):
    comment: str = ""

class ForwardBody(BaseModel):
    to: List[str]
    comment: str = ""

class MoveMessageBody(BaseModel):
    destination_folder_id: str

class UpdateMessageBody(BaseModel):
    is_read: Optional[bool] = None


# ── Folders ────────────────────────────────────────────────────────────────────

@router.get("/folders", tags=["Mail Folders"])
def list_mail_folders(client: MailClient = Depends(get_mail_client)):
    """List the user's mail folders (Inbox, Sent Items, Drafts, etc.)."""
    return client.list_mail_folders()


@router.get("/folders/{folder_id}/messages", tags=["Mail Folders"])
def list_folder_messages(
    folder_id: str, top: int = 25, client: MailClient = Depends(get_mail_client)
):
    """List messages in a specific mail folder."""
    return client.list_folder_messages(folder_id, top)


# ── Messages ───────────────────────────────────────────────────────────────────

@router.get("/messages", tags=["Mail Messages"])
def list_messages(top: int = 25, client: MailClient = Depends(get_mail_client)):
    """List messages across the mailbox, most recent first."""
    return client.list_messages(top)


@router.get("/messages/{message_id}", tags=["Mail Messages"])
def get_message(message_id: str, client: MailClient = Depends(get_mail_client)):
    """Get full metadata and body for a message by its ID."""
    return client.get_message(message_id)


@router.patch("/messages/{message_id}", tags=["Mail Messages"])
def update_message(
    message_id: str, body: UpdateMessageBody, client: MailClient = Depends(get_mail_client)
):
    """Update message properties — currently supports marking read/unread."""
    fields = {}
    if body.is_read is not None:
        fields["isRead"] = body.is_read
    result = client.update_message(message_id, fields)
    if result is None:
        raise HTTPException(status_code=500, detail="Message update failed")
    return result


@router.delete("/messages/{message_id}", tags=["Mail Messages"])
def delete_message(message_id: str, client: MailClient = Depends(get_mail_client)):
    """Permanently delete a message."""
    ok = client.delete_message(message_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"deleted": message_id}


@router.patch("/messages/{message_id}/move", tags=["Mail Messages"])
def move_message(
    message_id: str, body: MoveMessageBody, client: MailClient = Depends(get_mail_client)
):
    """Move a message to a different mail folder."""
    result = client.move_message(message_id, body.destination_folder_id)
    if result is None:
        raise HTTPException(status_code=500, detail="Move failed")
    return result


# ── Search ─────────────────────────────────────────────────────────────────────

@router.get("/search", tags=["Mail Search"])
def search_messages(q: str, top: int = 25, client: MailClient = Depends(get_mail_client)):
    """Search messages across the mailbox matching the query string."""
    return client.search_messages(q, top)


# ── Send / Reply / Forward ─────────────────────────────────────────────────────

@router.post("/send", tags=["Mail Send"])
def send_mail(body: SendMailBody, client: MailClient = Depends(get_mail_client)):
    """Compose and send a new email."""
    ok = client.send_mail(body.to, body.subject, body.body, body.body_type, body.cc, body.bcc)
    if not ok:
        raise HTTPException(status_code=500, detail="Send failed")
    return {"sent": True}


@router.post("/messages/{message_id}/reply", tags=["Mail Send"])
def reply_to_message(
    message_id: str, body: ReplyBody, client: MailClient = Depends(get_mail_client)
):
    """Reply to the sender of a message."""
    ok = client.reply_to_message(message_id, body.comment)
    if not ok:
        raise HTTPException(status_code=500, detail="Reply failed")
    return {"replied": message_id}


@router.post("/messages/{message_id}/reply-all", tags=["Mail Send"])
def reply_all_to_message(
    message_id: str, body: ReplyBody, client: MailClient = Depends(get_mail_client)
):
    """Reply to all recipients of a message."""
    ok = client.reply_all_to_message(message_id, body.comment)
    if not ok:
        raise HTTPException(status_code=500, detail="Reply-all failed")
    return {"replied_all": message_id}


@router.post("/messages/{message_id}/forward", tags=["Mail Send"])
def forward_message(
    message_id: str, body: ForwardBody, client: MailClient = Depends(get_mail_client)
):
    """Forward a message to new recipients."""
    ok = client.forward_message(message_id, body.to, body.comment)
    if not ok:
        raise HTTPException(status_code=500, detail="Forward failed")
    return {"forwarded": message_id}


# ── Attachments ────────────────────────────────────────────────────────────────

@router.get("/messages/{message_id}/attachments", tags=["Mail Attachments"])
def list_attachments(message_id: str, client: MailClient = Depends(get_mail_client)):
    """List attachments on a message."""
    return client.list_attachments(message_id)


@router.get("/messages/{message_id}/attachments/{attachment_id}", tags=["Mail Attachments"])
def get_attachment(
    message_id: str, attachment_id: str, client: MailClient = Depends(get_mail_client)
):
    """Get a single attachment, including base64 contentBytes for files."""
    return client.get_attachment(message_id, attachment_id)
