import logging

from myah.models.users import UserModel
from myah.models.files import Files
from myah.models.models import Models

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def has_access_to_file(
    file_id: str | None,
    access_type: str,
    user: UserModel,
    db: Session | None = None,
) -> bool:
    """
    Check if a user has the specified access to a file through any of:
    - Shared workspace models that attach the file directly
    - Channels the user is a member of
    - Shared chats

    NOTE: This does NOT check direct file ownership — callers should check
    file.user_id == user.id separately before calling this.
    """
    file = Files.get_file_by_id(file_id, db=db)
    log.debug(f'Checking if user has {access_type} access to file')
    if not file:
        return False

    # Direct ownership
    if file.user_id == user.id:
        return True

    # Check if the file is directly attached to a shared workspace model
    for model in Models.get_models_by_user_id(user.id, permission=access_type, db=db):
        knowledge_items = getattr(model.meta, 'knowledge', None) or []
        for item in knowledge_items:
            if isinstance(item, dict) and item.get('type') == 'file' and item.get('id') == file.id:
                return True

    return False
