"""unist-blackboard-mcp — MCP server for UNIST Blackboard (Learn Ultra).

Auth model: session-cookie harvest (no Blackboard developer app key required).
A user logs into blackboard.unist.ac.kr via the normal Azure AD SSO + MFA flow in a
real browser; we capture the resulting session cookies and reuse them against the
Blackboard public REST API (/learn/api/public) on the user's behalf.
"""

__version__ = "0.1.4"
