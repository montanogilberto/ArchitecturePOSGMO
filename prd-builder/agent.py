"""
PRD Builder — standalone entry point for `adk web`

Usage:
    cd /Users/apple12/Agent_POSGMO/ArchitecturePOSGMO/prd-builder
    adk web
"""

import sys
sys.path.insert(0, "/Users/apple12/Agent_POSGMO/ArchitecturePOSGMO/posgmo-factory")

from dotenv import load_dotenv
load_dotenv("/Users/apple12/Agent_POSGMO/ArchitecturePOSGMO/posgmo-factory/.env")

from agents.prd_builder_agent import prd_builder_agent

root_agent = prd_builder_agent
