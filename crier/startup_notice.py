"""Once-per-launch startup update banner decisions, without I/O or timers."""
import re


class StartupNotice:
    """Coordinate UI-thread startup callbacks independently of manual updates.

    The UI may retain the returned banner while hidden and render it when the
    window opens. This coordinator never opens a window or changes update state.
    """

    def __init__(self):
        self._started = False
        self._pending = False
        self._dismissed = False
        self._closed = False

    def begin(self):
        """Claim the single startup check after the caller checks its executor."""
        if self._started or self._closed:
            return False
        self._started = True
        self._pending = True
        return True

    def complete(self, state):
        """Consume one startup completion; return safe banner text if available."""
        if not self._pending:
            return None
        self._pending = False
        if self._closed or self._dismissed or type(state) is not dict:
            return None
        if state.get('status') != 'available':
            return None
        version = state.get('version')
        notes = state.get('notes')
        if type(version) is not str or len(version) > 40 or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
            return None
        if type(notes) is not str or len(notes) > 4000:
            return None
        return {'version': version, 'notes': notes}

    def dismiss(self):
        """Suppress this launch's banner without altering manual availability."""
        self._dismissed = True

    def close(self):
        """Invalidate callbacks on application shutdown."""
        self._closed = True
        self._pending = False

    def cancel(self):
        """Invalidate startup callbacks without cancelling a manual update."""
        self.close()
