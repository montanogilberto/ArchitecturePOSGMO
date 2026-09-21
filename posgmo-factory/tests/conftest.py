"""
Load .env once for the whole test session. Several tests (Gemini embedding
calls in test_factory_experience.py's live tests, real LLM calls in
test_debate_v2_rewards_e2e.py) need real API keys. Before this file existed,
that only worked by accident — whichever test module happened to import
orchestrator.py first triggered orchestrator's own module-level
load_dotenv() as a side effect, so running the full suite worked but running
a single affected file in isolation (e.g. pytest tests/test_factory_experience.py)
silently failed with KeyError on GEMINI_API_KEY depending on collection order.
"""
from dotenv import load_dotenv

load_dotenv()
