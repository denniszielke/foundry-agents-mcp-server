targetScope = 'subscription'

// ── Parameters ────────────────────────────────────────────────────────────────

@minLength(1)
@maxLength(64)
@description('Name used to generate a unique token for all resources')
param name string

@minLength(1)
@description('Primary Azure region for all resources')
param location string

@description('Object ID of the deploying user or service principal (used for role assignments)')
param principalId string = ''

@description('Set by azd after the container image has been built once')
param serverExists bool = false

// ── Variables ─────────────────────────────────────────────────────────────────

var resourceToken = toLower(uniqueString(subscription().id, name, location))
var tags = { 'azd-env-name': name }
var prefix = '${name}-${resourceToken}'

// ── Resource group ─────────────────────────────────────────────────────────────

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: '${name}-rg'
  location: location
  tags: tags
}

// ── Log Analytics + Application Insights ──────────────────────────────────────

module logAnalytics 'br/public:avm/res/operational-insights/workspace:0.7.0' = {
  name: 'loganalytics'
  scope: rg
  params: {
    name: '${prefix}-logs'
    location: location
    tags: tags
    skuName: 'PerGB2018'
    dataRetention: 30
  }
}

module appInsights 'br/public:avm/res/insights/component:0.4.2' = {
  name: 'appinsights'
  scope: rg
  params: {
    name: '${prefix}-appinsights'
    location: location
    tags: tags
    workspaceResourceId: logAnalytics.outputs.resourceId
    kind: 'web'
    applicationType: 'web'
  }
}

// ── Container Registry ────────────────────────────────────────────────────────

module acr 'br/public:avm/res/container-registry/registry:0.6.0' = {
  name: 'acr'
  scope: rg
  params: {
    name: '${resourceToken}acr'
    location: location
    tags: tags
    acrSku: 'Basic'
    adminUserEnabled: false
  }
}

// ── Container Apps Environment ────────────────────────────────────────────────

module containerAppsEnv 'br/public:avm/res/app/managed-environment:0.8.0' = {
  name: 'containerAppsEnv'
  scope: rg
  params: {
    name: '${prefix}-env'
    location: location
    tags: tags
    logAnalyticsWorkspaceResourceId: logAnalytics.outputs.resourceId
  }
}

// ── User-assigned managed identity ────────────────────────────────────────────

module managedIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.0' = {
  name: 'managedIdentity'
  scope: rg
  params: {
    name: '${prefix}-identity'
    location: location
    tags: tags
  }
}

// ── Role assignments ───────────────────────────────────────────────────────────
// All Azure services authenticated through DefaultAzureCredential / managed identity

// ACR pull – let the Container App pull its own image
module acrPullRole 'core/security/role.bicep' = {
  name: 'acrPullRole'
  scope: rg
  params: {
    principalId: managedIdentity.outputs.principalId
    roleDefinitionId: '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull
    principalType: 'ServicePrincipal'
  }
}

// Azure AI Developer – access to AI Foundry project (agents, inference)
module aiProjectRole 'core/security/role.bicep' = {
  name: 'aiProjectRole'
  scope: rg
  params: {
    principalId: managedIdentity.outputs.principalId
    roleDefinitionId: '64702f94-c441-49e6-a78b-ef80e0188fee' // Azure AI Developer
    principalType: 'ServicePrincipal'
  }
}

// Cognitive Services User – Azure OpenAI embeddings & chat completions
module cogServicesRole 'core/security/role.bicep' = {
  name: 'cogServicesRole'
  scope: rg
  params: {
    principalId: managedIdentity.outputs.principalId
    roleDefinitionId: 'a97b65f3-24c7-4388-baec-2e87135dc908' // Cognitive Services User
    principalType: 'ServicePrincipal'
  }
}

// Search Index Data Contributor – read/write to Azure AI Search
module searchContribRole 'core/security/role.bicep' = {
  name: 'searchContribRole'
  scope: rg
  params: {
    principalId: managedIdentity.outputs.principalId
    roleDefinitionId: '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // Search Index Data Contributor
    principalType: 'ServicePrincipal'
  }
}

// Optionally give the deploying user the same access for local development
module devAiProjectRole 'core/security/role.bicep' = if (!empty(principalId)) {
  name: 'devAiProjectRole'
  scope: rg
  params: {
    principalId: principalId
    roleDefinitionId: '64702f94-c441-49e6-a78b-ef80e0188fee' // Azure AI Developer
    principalType: 'User'
  }
}

module devSearchRole 'core/security/role.bicep' = if (!empty(principalId)) {
  name: 'devSearchRole'
  scope: rg
  params: {
    principalId: principalId
    roleDefinitionId: '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // Search Index Data Contributor
    principalType: 'User'
  }
}

// ── Container App ─────────────────────────────────────────────────────────────

module serverApp 'app/server.bicep' = {
  name: 'serverApp'
  scope: rg
  params: {
    name: '${prefix}-server'
    location: location
    tags: union(tags, { 'azd-service-name': 'server' })
    containerAppsEnvironmentId: containerAppsEnv.outputs.resourceId
    containerRegistryName: acr.outputs.name
    managedIdentityId: managedIdentity.outputs.resourceId
    managedIdentityClientId: managedIdentity.outputs.clientId
    exists: serverExists
    applicationInsightsConnectionString: appInsights.outputs.connectionString
    // External Azure service endpoints – supply via azd env vars
    azureAiProjectEndpoint: ''   // Set AZURE_AI_PROJECT_ENDPOINT in azd env
    azureAiSearchEndpoint: ''    // Set AZURE_AI_SEARCH_ENDPOINT in azd env
    azureOpenAiEndpoint: ''      // Set AZURE_OPENAI_ENDPOINT in azd env
    azureOpenAiEmbeddingModel: 'text-embedding-3-small'
    azureOpenAiCompletionModel: ''  // Set AZURE_OPENAI_COMPLETION_MODEL_NAME in azd env
  }
}

// ── Outputs ────────────────────────────────────────────────────────────────────

@description('URL of the deployed MCP server (HTTP transport)')
output MCP_SERVER_URL string = 'https://${serverApp.outputs.fqdn}/mcp'

@description('Resource group name')
output RESOURCE_GROUP string = rg.name

@description('Container registry name')
output AZURE_CONTAINER_REGISTRY_NAME string = acr.outputs.name

@description('Container Apps environment name')
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = containerAppsEnv.outputs.name

@description('Application Insights connection string')
output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.outputs.connectionString
