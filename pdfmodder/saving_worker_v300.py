"""Apply a persisted draft with the same validation as an on-page edit."""
from copy import deepcopy

from .model import EditError, EditRequest


def apply_stored_draft_v300(session):
    """Used by Save all when a recovered draft belongs to an inactive tab.

    The draft is retained until commit succeeds.  Reading or copying its JSON
    never changes the snapshot, recovery record, or saved revision.
    """
    draft = deepcopy(session.recovered_draft or session.history.metadata.get('draft'))
    if not draft:
        if session.pending is not None:
            return session.commit()
        return {'state': session.state()}
    if draft.get('kind') == 'rich':
        # A recovered checkpoint can contain both a preview and a newer
        # draft. Validate the draft itself instead of assuming the preview
        # already represents its text and formatting.
        previous_pending, previous_report = session.pending, session.pending_report
        previous_revision = session.history.revision
        session.pending = session.pending_report = None
        try:
            prepared = session.rich_preview(draft['payload'], prepare=True)
            return session.rich_commit(prepared['token'])
        except Exception:
            if session.history.revision == previous_revision:
                session.pending, session.pending_report = previous_pending, previous_report
                session._clear_cache()
                session._checkpoint()
            raise
    if draft.get('kind') == 'legacy':
        if draft.get('request') is not None:
            request = EditRequest(**draft['request'])
        else:
            request = EditRequest(page=draft['page'], ids=draft['ids'],
                                  revision=draft['revision'], text=draft.get('text', ''))
        session.preview(request)
        return session.commit()
    raise EditError('El borrador guardado no contiene una edición compatible. Abre su pestaña para revisarlo.')
