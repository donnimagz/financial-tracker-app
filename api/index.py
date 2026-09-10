import os
import sys

# Ensure project root is on sys.path for server and ai_engine imports
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server import FinanceAPIHandler

# Vercel looks for 'handler' inheriting from BaseHTTPRequestHandler
class handler(FinanceAPIHandler):
    pass
