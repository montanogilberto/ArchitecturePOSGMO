"""PR Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.pr.prompt import INSTRUCTION
from agents.pr.rules import (
    save_sql_locally,
    github_create_branch,
    github_push_file,
    patch_main_py,
    patch_app_tsx,
    patch_ui_feature_type,
    patch_role_ui,
    patch_setting_tsx,
    github_create_pr,
)

pr_agent = Agent(
    name="pr_agent",
    description=(
        "Pushes all generated module files to GitHub branches and opens "
        "Pull Requests on the frontend and backend repos."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    tools=[
        FunctionTool(func=save_sql_locally),
        FunctionTool(func=github_create_branch),
        FunctionTool(func=github_push_file),
        FunctionTool(func=patch_main_py),
        FunctionTool(func=patch_app_tsx),
        FunctionTool(func=patch_ui_feature_type),
        FunctionTool(func=patch_role_ui),
        FunctionTool(func=patch_setting_tsx),
        FunctionTool(func=github_create_pr),
    ],
    output_key="pr_result",
)