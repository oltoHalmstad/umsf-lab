"""UMSF incident AI agent.

Evidence-aware decision support for post-impact incidents at critical
infrastructure sites: rescue logistics (personnel accounting and team-task
assignment) and consequence-liquidation logistics (service continuity and
recovery scheduling).

Design boundary (Torstensson et al., 2026, Sec. 3.3.8, 3.9): all arithmetic,
eligibility, alerts and plans are deterministic. An optional language model may
only summarise minimised aggregates and explain plans. Every plan is a proposal
that requires authorisation by the role named in Table 9. Nothing in this package
actuates equipment.
"""

__version__ = "1.0.0"
AGENT_NAME = "umsf-incident-ai-agent"
RULE_VERSION = "umsf-rules-1.0"
