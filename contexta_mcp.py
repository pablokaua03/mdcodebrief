"""
Contexta MCP Server — entry point.

Usage:
    python contexta_mcp.py
    mcp run contexta_mcp.py
"""

from contexta_app.mcp_server import mcp

if __name__ == "__main__":
    mcp.run()
