# Foundry Agents MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that
exposes Azure AI Foundry agents, workflows, and AI Search vector-database
capabilities as MCP tools.

Supports two transports:
- **stdio** – for local use with `uvx` or VS Code Copilot
- **HTTP** – for deployment to **Azure Container Apps** via `azd up`

## Repository layout

```
src/
  foundry_agents_mcp/     ← MCP server (10 tools across 4 namespaces)
  foundry_agents/         ← Standalone agent & workflow implementations
    definitions/          ← Declarative YAML agent & workflow definitions
    case_study_agent.py   ← deploy-case-study-agent CLI command
    architecture_agent.py ← deploy-architecture-agent CLI command
    project_log_workflow.py ← run-project-log-workflow CLI command
infra/
  main.bicep              ← Container Apps + managed identity + role assignments
  app/server.bicep        ← Container App definition with health probes
  core/security/role.bicep
azure.yaml                ← azd service definition
Dockerfile                ← Multi-stage Alpine build
entrypoint.sh             ← Selects stdio or HTTP transport at startup
.env.sample               ← Template for local environment configuration
```

## MCP tool namespaces

| Namespace | Tools |
|-----------|-------|
| `agents_*` | List agents · Invoke agent · Check status · Get result |
| `search_*` | Semantic vector search · Add document to vector DB |
| `index_*`  | Create project-log index · Ingest project log entry |
| `workflows_*` | List sample workflows · Run project-log pipeline |

---

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) installed
- An **Azure AI Foundry** project (for agent tools)
- An **Azure AI Search** resource with a vector-capable tier (for search/index tools)
- An **Azure OpenAI** resource with a text-embedding model deployed

---

## Quick start with uvx

```bash
# Install and run directly from GitHub (no PyPI package required)
uvx --from git+https://github.com/denniszielke/foundry-agents-mcp-server@main foundry-agents-mcp-server
```

Or with an explicit environment file:

```bash
uvx --from git+https://github.com/denniszielke/foundry-agents-mcp-server@main --env-file .env foundry-agents-mcp-server
```

---

## Configuration

All configuration is driven by environment variables. Copy `.env.sample` to `.env`
and fill in your values.

| Variable | Required | Description |
|---|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | For agent tools | AI Foundry project endpoint – `https://<account>.services.ai.azure.com/api/projects/<project>` |
| `AZURE_OPENAI_ENDPOINT` | No | OpenAI-compatible endpoint (falls back to `AZURE_AI_PROJECT_ENDPOINT`) |
| `AZURE_OPENAI_COMPLETION_MODEL_NAME` | For workflow tools | Completion model deployment name in the Foundry account |
| `AZURE_OPENAI_EMBEDDING_MODEL` | For search/index tools | Embedding model deployment name (default: `text-embedding-3-small`) |
| `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | No | Embedding vector size (default: `1536`) |
| `AZURE_AI_SEARCH_ENDPOINT` | For search/index tools | Azure AI Search service endpoint URL |
| `AZURE_AI_SEARCH_INDEX_NAME` | No | Search index name (default: `project-log-index`) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | Application Insights connection string for telemetry |

> **Note** – When deploying via `azd up`, all these values are written to `.env`
> automatically by `infra/write_env.sh`. For local development run `az login` and
> use `DefaultAzureCredential`; no API keys are needed.

---

## Claude Desktop configuration

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "foundry-agents": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/denniszielke/foundry-agents-mcp-server@main", "foundry-agents-mcp-server"],
      "env": {
        "AZURE_AI_PROJECT_ENDPOINT": "https://...",
        "AZURE_AI_SEARCH_ENDPOINT": "https://...",
        "AZURE_OPENAI_ENDPOINT": "https://..."
      }
    }
  }
}
```

---

## Tool reference and example prompts

### agents namespace

#### `agents_list_agents`

List all agents and workflows available in the Foundry project, including their
IDs, models, descriptions, and tool capabilities.

**Example prompts**
- *"What agents are available in the project?"*
- *"List all AI workflows I can invoke"*
- *"Show me the agents and their capabilities in this Foundry project"*

---

#### `agents_invoke_agent`

Invoke an agent or workflow asynchronously. Returns an **invocation ID** to
track progress.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | string | Agent ID from `agents_list_agents` |
| `task` | string | Task description or question |
| `file_context` | string (optional) | Additional text or file content as context |

**Example prompts**
- *"Ask agent `<agent_id>` to summarize the latest Azure AI announcements"*
- *"Invoke the research workflow with task: analyze competitive landscape for AI services"*
- *"Send this document to the analysis agent and include the file text as context: `<text>`"*

---

#### `agents_get_invocation_status`

Check whether an agent invocation is still running or has completed.

| Parameter | Type | Description |
|---|---|---|
| `invocation_id` | string | Invocation ID from `agents_invoke_agent` |

**Possible statuses**: `queued`, `in_progress`, `requires_action`, `cancelling`,
`cancelled`, `failed`, `completed`, `expired`

**Example prompts**
- *"Check the status of invocation `<invocation_id>`"*
- *"Has my agent task finished? ID: `<invocation_id>`"*
- *"Is the workflow still running for invocation `<invocation_id>`?"*

---

#### `agents_get_invocation_result`

Retrieve the text (and file reference) output from a completed invocation.

| Parameter | Type | Description |
|---|---|---|
| `invocation_id` | string | Invocation ID from `agents_invoke_agent` |

**Example prompts**
- *"Get the results from invocation `<invocation_id>`"*
- *"What did the agent return for ID `<invocation_id>`?"*
- *"Show me the output of the completed workflow: `<invocation_id>`"*

---

### search namespace

#### `search_vector_db`

Perform a semantic (vector) search over the project-log index.

| Parameter | Type | Description |
|---|---|---|
| `query` | string | Natural language search query |
| `top_k` | integer (optional) | Number of results (default: 5) |

**Example prompts**
- *"Find project logs related to Azure Kubernetes Service"*
- *"Search for workshop summaries about machine learning"*
- *"What meetings discussed security architecture?"*
- *"Find blog posts about microservices, return top 10 results"*

---

#### `search_add_to_vector_db`

Add a document to the project-log vector index. The content is automatically
embedded and stored alongside the metadata.

| Parameter | Type | Description |
|---|---|---|
| `title` | string | Document title |
| `content` | string | Main text to embed and index |
| `entry_type` | string (optional) | `workshop`, `meeting`, `blog`, or `repo` (default: `meeting`) |
| `customer_name` | string (optional) | Customer or organization name |
| `short_summary` | string (optional) | Brief summary |
| `project_name` | string (optional) | Associated project name |
| `tags` | string (optional) | Comma-separated tags (e.g. `"azure,kubernetes"`) |
| `reference_url` | string (optional) | Source URL |
| `architecture` | string (optional) | Architecture diagram as JSON or XML |

**Example prompts**
- *"Add this meeting summary to the vector database: title='Azure Workshop', content='...'"*
- *"Store a new project log entry about our Kubernetes migration discussion"*
- *"Index this blog post with tags: azure, containers, devops"*

---

### index namespace

#### `index_create_project_log_index`

Create the project-log Azure AI Search index with the correct schema and HNSW
vector configuration. Safe to call when the index already exists.

**Schema fields**

| Field | Type | Notes |
|---|---|---|
| `id` | String (key) | Auto-generated UUID |
| `title` | String | Searchable, filterable, sortable |
| `type` | String | Filterable, facetable (`workshop`, `meeting`, `blog`, `repo`) |
| `customer_name` | String | Filterable, facetable |
| `short_summary` | String | Searchable |
| `context` | String | Searchable (full body text) |
| `context_vector` | Collection(Single) | HNSW vector search field |
| `project_name` | String | Filterable, facetable |
| `tags` | Collection(String) | Filterable, facetable |
| `reference_url` | String | Searchable |
| `architecture` | String | Searchable |
| `creation_date` | DateTimeOffset | Filterable, sortable |
| `modified_date` | DateTimeOffset | Filterable, sortable |

**Example prompts**
- *"Set up the project log search index"*
- *"Create the Azure AI Search index for storing project summaries"*
- *"Initialize the vector database schema for project logs"*

---

#### `index_ingest_project_log`

Ingest a single project log entry into the index. The index is created
automatically if it does not exist.

| Parameter | Type | Description |
|---|---|---|
| `title` | string | Log entry title |
| `entry_type` | string | `workshop`, `meeting`, `blog`, or `repo` |
| `customer_name` | string | Customer or organization name |
| `short_summary` | string | Brief summary (1–2 sentences) |
| `context` | string | Full context text (will be embedded) |
| `project_name` | string (optional) | Project name |
| `tags` | string (optional) | Comma-separated tags |
| `reference_url` | string (optional) | Source URL |
| `architecture` | string (optional) | Architecture diagram as JSON or XML |

**Example prompts**
- *"Add a workshop log: title='Azure AI Day', entry_type='workshop', customer_name='Contoso', context='...'"*
- *"Index a new meeting summary about the cloud migration project"*
- *"Store this repo documentation with tags: python, mcp, azure"*

---

## Sample agents and workflow

The `foundry_agents` package provides two sample agents and a pipeline workflow
that work independently of the MCP server.

### Deploy agents to Azure AI Foundry

Register the sample agents in your Foundry project (they then appear in
`agents_list_agents` and can be invoked with `agents_invoke_agent`):

```bash
deploy-case-study-agent      # registers CaseStudyAgent
deploy-architecture-agent    # registers ArchitectureAgent
```

### Run the project-log workflow

Fetch a Microsoft customer story, extract metadata, generate an architecture
diagram, and store everything in the vector index – all in one command:

```bash
run-project-log-workflow \
  --url "https://www.microsoft.com/en/customers/story/25676-commerzbank-ag-azure-ai-foundry-agent-service" \
  --project "Commerzbank AI Platform"
```

Or trigger the same pipeline from the MCP server:
```
Run the project log workflow for https://www.microsoft.com/en/customers/story/...
```

The workflow **automatically uses deployed Foundry agents** when available and
falls back to direct Azure OpenAI inference otherwise.

---

## Deploy to Azure Container Apps

The server can be deployed to **Azure Container Apps** with a single command
using the [Azure Developer CLI (azd)](https://aka.ms/install-azd).

### What gets provisioned

| Resource | Purpose |
|----------|---------|
| Virtual Network | Container Apps environment runs VNet-integrated (always) |
| Container Apps Environment | Hosts the MCP server; set `USE_PRIVATE_INGRESS=true` for internal-only access |
| Azure Container Registry | Stores the Docker image |
| Log Analytics + Application Insights | Telemetry and distributed traces |
| Azure AI Foundry (AIServices + project) | Agents API + model deployments (completion + embedding) |
| Azure AI Search | Vector search index for the project log |
| User-assigned Managed Identity | Passwordless auth – assigned Azure AI Developer, Cognitive Services OpenAI User, Search Index Data Contributor, and AcrPull roles |

### Infra folder structure

```
infra/
  abbreviations.json          ← Azure resource name prefixes
  main.bicep                  ← Subscription-scoped orchestrator
  main.parameters.json        ← azd parameter file
  ai/
    foundry.bicep             ← AIServices account + Foundry project + model deployments
    search.bicep              ← Azure AI Search
  app/
    server.bicep              ← MCP server Container App + identity
  core/
    host/
      vnet.bicep              ← VNet with aca-apps subnet (always deployed)
      container-apps.bicep    ← Environment + registry orchestration
      container-apps-environment.bicep  ← Managed environment (usePrivateIngress flag)
      container-app.bicep     ← Container App with health probes + role assignments
      container-app-upsert.bicep
      container-registry.bicep
    monitor/
      monitoring.bicep        ← Log Analytics + Application Insights
      loganalytics.bicep
      applicationinsights.bicep
    security/
      foundry-access.bicep    ← Azure AI Developer + Cognitive Services OpenAI User
      registry-access.bicep   ← AcrPull
      search-access.bicep     ← Search Index Data Contributor
```

### Quick deploy

```bash
# 1. Login
azd auth login

# 2. Create an azd environment
azd env new foundry-mcp
azd env set AZURE_LOCATION swedencentral   # or eastus2, westus3, northcentralus

# 3. (Optional) private ingress – accessible only from within the VNet
azd env set USE_PRIVATE_INGRESS true

# 4. Provision infrastructure (no local Docker required)
azd up
```

`azd up` will:
1. Provision all resources (VNet, Container Apps, Foundry, Search, monitoring)
2. Run `infra/write_env.sh` to populate `.env` with all endpoint values

### Build and deploy the container

The container image is built remotely using Azure Container Registry (ACR) –
**no local Docker installation is required**. After `azd up` has provisioned the
infrastructure, run:

```bash
# Build in ACR and deploy the Container App
./azd-hooks/deploy.sh foundry-mcp   # pass your azd environment name
```

The script will:
1. Build the Docker image remotely in ACR via `az acr build`
2. Deploy the Container App via a Bicep deployment (`infra/app/server.bicep`)
3. Print the MCP server URL

### Private ingress

When `USE_PRIVATE_INGRESS=true` the Container Apps environment is configured as
`internal: true` and the Container App ingress is set to `external: false`.  The
MCP server is then only reachable from within the VNet (e.g. via a jump host,
VPN, or another Container App in the same environment).

### Connect VS Code Copilot to the deployed server

```bash
# Find the URL
cat .env | grep MCP_SERVER_URL
```

1. Open Command Palette in VS Code → **MCP: Add Server** → **HTTP**.
2. Enter the URL from `.env` (e.g. `https://<app-fqdn>/mcp`).
3. All 10 Foundry Agent tools are now available in Copilot Chat.

### Run locally with HTTP transport

```bash
# Start the HTTP server (same code, same image)
uvicorn foundry_agents_mcp.server:http_app --host 0.0.0.0 --port 8000

# Test the health probe
curl http://localhost:8000/health
# → {"status":"healthy","service":"foundry-agents-mcp-server"}
```

### Monitoring

OpenTelemetry tracing is enabled automatically when
`APPLICATIONINSIGHTS_CONNECTION_STRING` is set. Every MCP tool call and HTTP
request is traced via `azure-monitor-opentelemetry`.

```bash
azd monitor   # open the Application Insights dashboard in the portal
```

### Tear down

```bash
azd down
```

---

## Development

```bash
# Clone and install in editable mode
git clone https://github.com/denniszielke/foundry-agents-mcp-server
cd foundry-agents-mcp-server
pip install -e ".[dev]"

# Run locally (stdio)
python -m foundry_agents_mcp
```

## License

MIT
