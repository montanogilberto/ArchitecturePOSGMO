"""Business Intake — turns a spoken or written business need into an
evidence-grounded Factory analysis (reuse / extend / create). Read-only:
it never writes a PRD, runs construction, or touches any database."""
from agents.business_intake.runner import analyze_business_need

__all__ = ["analyze_business_need"]
