from google.adk.agents import SequentialAgent

from agents.prd_parser_agent import prd_parser_agent
from agents.architect_agent import architect_agent
from agents.database_agent import database_agent
from agents.backend_agent import backend_agent
from agents.frontend_agent import frontend_agent
from agents.reviewer_agent import reviewer_agent
from agents.pr_agent import pr_agent

root_agent = SequentialAgent(
    name="posgmo_factory",
    description="POS GMO Software Factory",
    sub_agents=[
        prd_parser_agent,   # populates session state: module, plural, Module, GitHub vars
        architect_agent,
        database_agent,
        backend_agent,
        frontend_agent,
        reviewer_agent,
        pr_agent,
    ],
)