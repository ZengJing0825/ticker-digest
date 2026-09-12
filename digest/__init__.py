"""ticker-digest: an event-driven watchlist / opinion / portfolio digest engine.

No event, no message: a digest is written only when a rule fires, survives
the slice's caps and the escalation-aware dedupe, and passes the output
contract. Signals -> slices -> ranking -> rendering -> delivery -> audit.
"""

__version__ = "0.2.0"
