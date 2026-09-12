"""ticker-digest: an event-driven watchlist digest agent.

No event, no message: the agent only writes a digest when a rule fires,
survives frequency caps and de-duplication, and passes the output contract.
"""

__version__ = "0.1.0"
