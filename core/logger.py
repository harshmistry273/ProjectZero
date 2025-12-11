import logging

# File to manage logging (console level)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(lineno)d - %(message)s"))

logger.addHandler(console_handler)