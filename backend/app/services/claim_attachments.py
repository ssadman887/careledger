"""Supporting documents for claims and appeals (stored in the database; demo-sized)."""

import re

from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.models.insurance import ClaimAttachment
from app.repositories import insurance as repo
from app.services import audit
from app.services.audit import Actor
from app.services.claims import _event, get_claim

MAX_BYTES = 5 * 1024 * 1024
ALLOWED_TYPES = {
    "application/pdf": (b"%PDF",),
    "image/png": (b"\x89PNG",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "text/plain": (),
}


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    return (name.strip(" .") or "attachment")[:200]


def add_attachment(
    session: Session,
    actor: Actor,
    claim_id: int,
    *,
    filename: str,
    content_type: str,
    data: bytes,
) -> ClaimAttachment:
    claim = get_claim(session, claim_id)
    if content_type not in ALLOWED_TYPES:
        raise ValidationFailed(
            "Only PDF, PNG, JPEG or plain-text files are accepted", code="unsupported_file_type"
        )
    if not data or len(data) > MAX_BYTES:
        raise ValidationFailed("Files must be between 1 byte and 5 MB", code="invalid_file_size")
    signatures = ALLOWED_TYPES[content_type]
    if signatures and not any(data.startswith(sig) for sig in signatures):
        raise ValidationFailed("File content does not match its type", code="file_type_mismatch")
    attachment = ClaimAttachment(
        claim_id=claim.id,
        filename=_safe_name(filename),
        content_type=content_type,
        size_bytes=len(data),
        data=data,
        uploaded_by_id=actor.id,
    )
    session.add(attachment)
    session.flush()
    _event(session, actor, claim, "attachment", note=attachment.filename)
    audit.record(
        session,
        actor,
        entity_type="claim_attachment",
        entity_id=attachment.id,
        action="create",
        after={
            "claim_id": claim.id,
            "filename": attachment.filename,
            "size_bytes": attachment.size_bytes,
        },
    )
    return attachment


def get_attachment(session: Session, claim_id: int, attachment_id: int) -> ClaimAttachment:
    attachment = repo.get_attachment(session, attachment_id)
    if attachment is None or attachment.claim_id != claim_id:
        raise NotFound("Attachment not found")
    return attachment
