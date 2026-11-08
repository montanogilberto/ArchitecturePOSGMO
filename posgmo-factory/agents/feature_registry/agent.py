"""feature_registry_agent — pure Python stage, zero LLM calls (see rules.py)."""
from agents.deterministic_stage import DeterministicToolStage
from agents.feature_registry.rules import run_feature_registry

feature_registry_agent = DeterministicToolStage(
    name="feature_registry_agent",
    description=(
        "Deterministic: emits EXEC sp_uiFeatures_register for the new module into "
        "database_artifacts.feature_registration so it appears in /setting and GET /roles."
    ),
    fn=run_feature_registry,
)
