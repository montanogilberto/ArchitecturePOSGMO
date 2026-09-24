"""
PRD Builder — standalone entry point for `adk web`

Usage:
    cd /Users/apple12/Agent_POSGMO/prd-builder
    adk web
"""

import sys
sys.path.insert(0, "/Users/apple12/Agent_POSGMO/posgmo-factory")

from dotenv import load_dotenv
load_dotenv("/Users/apple12/Agent_POSGMO/posgmo-factory/.env")

from agents.prd_builder import prd_builder_agent

root_agent = prd_builder_agent
