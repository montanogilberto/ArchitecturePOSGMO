"""
Commercial core of the GMO Ecosystem website: visit counter, AI token
allowance per visitor, lead capture (mini registration + contact form) and
lead follow-up for the GMO team.

Interim home: this lives in the same service the website already calls
(business_intake_api.py) with a small SQLite database, until the Factory
builds the designed `leadCapture` module (tests/prd_leadCapture.json) into
the GMO backend. Lead fields use that design's names so the data can move
there unchanged.
"""
