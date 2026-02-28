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
# Install and run in one command (reads env vars from the shell)
uvx foundry-agents-mcp-server
```

Or with an explicit environment file:

```bash
uvx --env-file .env foundry-agents-mcp-server
```

---

## Configuration

Set the following environment variables (e.g. in a `.env` file):

| Variable | Required | Description |
|---|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | For agent tools | Azure AI Foundry project endpoint URL |
| `AZURE_AI_SEARCH_ENDPOINT` | For search/index tools | Azure AI Search service endpoint URL |
| `AZURE_AI_SEARCH_INDEX_NAME` | No | Name of the search index (default: `project-log-index`) |
| `AZURE_OPENAI_ENDPOINT` | For search/index tools | Azure OpenAI service endpoint URL |
| `AZURE_OPENAI_EMBEDDING_MODEL` | No | Embedding model deployment name (default: `text-embedding-3-small`) |
| `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | No | Embedding vector dimensions (default: `1536`) |
| `AZURE_OPENAI_COMPLETION_MODEL_NAME` | No | Chat completion model deployment name |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | Application Insights connection string for telemetry |

Example `.env` file:

```env
AZURE_AI_PROJECT_ENDPOINT=https://<hub>.api.azureml.ms/agents/v1.0/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<project>
AZURE_AI_SEARCH_ENDPOINT=https://<search-service>.search.windows.net
AZURE_AI_SEARCH_INDEX_NAME=project-log-index
AZURE_OPENAI_ENDPOINT=https://<openai-resource>.openai.azure.com
AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
AZURE_OPENAI_COMPLETION_MODEL_NAME=gpt-4o
```

---

## Claude Desktop configuration

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "foundry-agents": {
      "command": "uvx",
      "args": ["foundry-agents-mcp-server"],
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
| Azure Container Apps (Environment + App) | Hosts the MCP server over HTTPS |
| Azure Container Registry | Stores the Docker image |
| Log Analytics + Application Insights | Telemetry and traces |
| User-assigned Managed Identity | Passwordless auth to all Azure services |
| Role assignments | AI Developer · Cognitive Services User · Search Index Data Contributor |

### Quick deploy

```bash
# 1. Login
azd auth login

# 2. Create an azd environment and deploy
azd env new foundry-mcp
azd up
```

`azd up` will:
1. Build the Docker image (Alpine-based, multi-stage)
2. Push it to the provisioned Container Registry
3. Deploy the Container App with the `/health` liveness/readiness probe
4. Write `MCP_SERVER_URL` and `APPLICATIONINSIGHTS_CONNECTION_STRING` to `.env`

### Configure Azure service endpoints

After provisioning, set the Azure service endpoints in your azd environment
(they are passed as environment variables to the Container App):

```bash
azd env set AZURE_AI_PROJECT_ENDPOINT   "https://<hub>.services.ai.azure.com/api/projects/<project>"
azd env set AZURE_AI_SEARCH_ENDPOINT    "https://<search>.search.windows.net"
azd env set AZURE_OPENAI_ENDPOINT       "https://<openai>.openai.azure.com"
azd env set AZURE_OPENAI_COMPLETION_MODEL_NAME "gpt-4o"
azd deploy   # redeploy to pick up the new env vars
```

### Connect VS Code Copilot to the deployed server

1. After `azd up` completes, find `MCP_SERVER_URL` in `.env`.
2. In VS Code, open Command Palette → **MCP: Add Server** → **HTTP**.
3. Enter the URL (e.g. `https://<app-fqdn>/mcp`).
4. The 10 Foundry Agent tools are now available in Copilot Chat.

### Run locally with HTTP transport

```bash
# Start the HTTP server (same code, same image)
uvicorn foundry_agents_mcp.server:http_app --host 0.0.0.0 --port 8000

# In another terminal, test the health probe
curl http://localhost:8000/health
# → {"status":"healthy","service":"foundry-agents-mcp-server"}
```

### Monitoring

```bash
# Open the Application Insights / Log Analytics dashboard
azd monitor
```

OpenTelemetry tracing is enabled automatically when
`APPLICATIONINSIGHTS_CONNECTION_STRING` is set. Every MCP tool call and Starlette
request is instrumented.

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

# Run locally
python -m foundry_agents_mcp
```

## License

MIT
