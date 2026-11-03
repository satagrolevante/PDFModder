"""Keep exact checked source evidence available during complete worker writes.

Only explicit transaction entry points opt in. Reading, page display and tool
discovery must not acquire a source analysis or make deferred preparation eager.
The existing tagged pin owns revision identity, retention bounds and fallback;
every candidate still receives its own independent structural validation.
"""
from contextlib import contextmanager
from functools import wraps


@contextmanager
def session_source_analysis_v318(session):
    # Reject a reading-only session before hashing or parsing its PDF. This
    # scope must be inside the worker's analysis/validation evidence scopes.
    session._require_editing()
    if session.issues:
        from .model import EditError
        raise EditError('\n'.join(session.issues))
    from .tagged import pin_source_analysis
    with pin_source_analysis(session.history.current):
        # A commit can change history.current before this scope exits. Retain
        # its original revision so close also releases the pre-commit pin.
        session._analysis_source_revision_v305 = session.history.revision
        yield


def pinned_source_write_v318(function):
    """Pin through composition, exact-candidate checks and state publication."""
    @wraps(function)
    def write(session, *args, **kwargs):
        with session_source_analysis_v318(session):
            return function(session, *args, **kwargs)
    return write
