#################################################################################
# Industry Core Hub - MCP Addon
#
# Copyright (c) 2026 Capgemini
#
#################################################################################

# Single declaration of each MCP tool.
# Implemented incrementally across Steps 1–8.
#
# Each entry declares: tool name, description, input schema, output schema,
# write flag (routes through confirmation layer when true), and the adapter
# method to invoke.
#
# Step 9 will also generate FastAPI routes from these declarations for the
# OpenAPI mirror at /addons/mcp-kit/rest/v1/<tool_name>.
