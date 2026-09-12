import logging

# Sources and the LLM adapter log their graceful fallbacks; keep test output clean.
logging.disable(logging.CRITICAL)
