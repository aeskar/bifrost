# Team overflow MCP server

Run the stdio server on the gateway with Python 3.9 or later. Set a private persistent SQLite path and pass the seat identifier as a server argument. Configure one client for the authenticated operator. A shared client binds every caller to the same seat, so restrict access to that operator before exposing the endpoint. Keep tool injection and automatic execution disabled.

The server stores GitHub issue references and current utilization percentages with reset times. A human offers an issue, selects their own signed-in native coding client, claims the issue, performs the work and marks it finished. Releasing a claim returns it to the queue. A repeated call does not claim a second copy of the same issue. When an upstream provider omits usage information, the quota is unknown. A sample older than 15 minutes is stale. The provider's enforcement remains authoritative.

Service API overflow uses Bifrost's chat request `fallbacks` array and approved service providers. An issue offer never invokes inference, signs in to an account or starts a coding agent.
