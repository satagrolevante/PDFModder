"""One private print reader, pinned to the exact immutable history bytes."""
from dataclasses import dataclass, field


@dataclass
class PrintContextV318:
    revision: str
    document: object
    prepared_pages: set = field(default_factory=set)

    def close(self):
        self.document.close()
        self.prepared_pages.clear()


def close_print_context_v318(session):
    context = getattr(session, '_print_context_v318', None)
    session._print_context_v318 = None
    if context is not None:
        context.close()


def print_context_v318(session, data, revision):
    context = getattr(session, '_print_context_v318', None)
    if context is None or context.revision != revision or context.document.is_closed:
        close_print_context_v318(session)
        context = PrintContextV318(revision, session._open(data))
        session._print_context_v318 = context
    return context
