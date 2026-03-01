targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the the environment which is used to generate a short unique hash used in all resources.')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
@allowed(['northcentralus', 'swedencentral', 'eastus2', 'westus3'])
param location string

param resourceGroupName string = ''
param containerAppsEnvironmentName string = ''
param containerRegistryName string = ''
param foundryName string = ''
param applicationInsightsDashboardName string = ''
param applicationInsightsName string = ''
param logAnalyticsName string = ''
param aiSearchName string = ''
param aiSearchIndexName string = 'project-log-index'

@description('Deploy the MCP server with private (VNet-internal) ingress only')
param usePrivateIngress bool = false

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

// Model deployment configuration
param completionDeploymentModelName string = 'gpt-5-nano'
param completionModelName string = 'gpt-5-nano'
param completionModelVersion string = '2025-08-07'

param embeddingDeploymentModelName string = 'text-embedding-3-small'
param embeddingModelName string = 'text-embedding-3-small'

param foundryApiVersion string = '2024-10-21'
param foundryCapacity int = 30

param modelDeployments array = [
  {
    name: completionDeploymentModelName
    sku: 'GlobalStandard'
    model: {
      format: 'OpenAI'
      name: completionModelName
      version: completionModelVersion
    }
  }
  {
    name: embeddingDeploymentModelName
    sku: 'GlobalStandard'
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: '1'
    }
  }
]

// Organize resources in a resource group
resource resourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: !empty(resourceGroupName) ? resourceGroupName : '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// Virtual network (always deployed – Container Apps environment is VNet-integrated)
module vnet './core/host/vnet.bicep' = {
  name: 'vnet'
  scope: resourceGroup
  params: {
    location: location
  }
}

// Container Apps environment + Container Registry
module containerApps './core/host/container-apps.bicep' = {
  name: 'container-apps'
  scope: resourceGroup
  params: {
    name: 'app'
    containerAppsEnvironmentName: !empty(containerAppsEnvironmentName) ? containerAppsEnvironmentName : '${abbrs.appManagedEnvironments}${resourceToken}'
    containerRegistryName: !empty(containerRegistryName) ? containerRegistryName : '${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    logAnalyticsWorkspaceName: monitoring.outputs.logAnalyticsWorkspaceName
    usePrivateIngress: usePrivateIngress
  }
}

// Azure AI Foundry (AIServices account + project + model deployments)
module foundry './ai/foundry.bicep' = {
  name: 'foundry'
  scope: resourceGroup
  params: {
    location: location
    tags: tags
    customDomainName: !empty(foundryName) ? foundryName : '${abbrs.cognitiveServicesAccounts}${resourceToken}'
    name: !empty(foundryName) ? foundryName : '${abbrs.cognitiveServicesAccounts}${resourceToken}'
    deployments: modelDeployments
    capacity: foundryCapacity
  }
}

// Azure AI Search
module search './ai/search.bicep' = {
  name: 'search'
  scope: resourceGroup
  params: {
    location: location
    tags: tags
    name: !empty(aiSearchName) ? aiSearchName : '${abbrs.searchSearchServices}${resourceToken}'
  }
}

// Monitor application with Azure Monitor
module monitoring './core/monitor/monitoring.bicep' = {
  name: 'monitoring'
  scope: resourceGroup
  params: {
    location: location
    tags: tags
    logAnalyticsName: !empty(logAnalyticsName) ? logAnalyticsName : '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    applicationInsightsName: !empty(applicationInsightsName) ? applicationInsightsName : '${abbrs.insightsComponents}${resourceToken}'
    applicationInsightsDashboardName: !empty(applicationInsightsDashboardName) ? applicationInsightsDashboardName : '${abbrs.portalDashboards}${resourceToken}'
  }
}

// MCP Server Container App
module mcpServer './app/server.bicep' = {
  name: 'mcp-server'
  scope: resourceGroup
  params: {
    name: '${abbrs.appContainerApps}mcp-server-${resourceToken}'
    location: location
    tags: tags
    identityName: '${abbrs.managedIdentityUserAssignedIdentities}mcp-server-${resourceToken}'
    foundryName: foundry.outputs.foundryName
    foundryEndpoint: foundry.outputs.openaiEndpoint
    foundryProjectEndpoint: foundry.outputs.foundryProjectEndpoint
    searchName: search.outputs.searchName
    searchEndpoint: search.outputs.searchEndpoint
    searchIndexName: aiSearchIndexName
    completionDeploymentModelName: completionDeploymentModelName
    embeddingDeploymentModelName: embeddingDeploymentModelName
    foundryApiVersion: foundryApiVersion
    applicationInsightsName: monitoring.outputs.applicationInsightsName
    containerAppsEnvironmentName: containerApps.outputs.environmentName
    containerRegistryName: containerApps.outputs.registryName
    imageName: ''
    usePrivateIngress: usePrivateIngress
  }
}

// ── Outputs ────────────────────────────────────────────────────────────────────

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = resourceGroup.name

output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.applicationInsightsConnectionString
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.applicationInsightsName

output AZURE_CONTAINER_ENVIRONMENT_NAME string = containerApps.outputs.environmentName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerApps.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = containerApps.outputs.registryName

output AZURE_AI_FOUNDRY_ENDPOINT string = foundry.outputs.openaiEndpoint
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.foundryProjectEndpoint
output AZURE_OPENAI_ENDPOINT string = foundry.outputs.openaiEndpoint
output AZURE_OPENAI_COMPLETION_MODEL_NAME string = completionDeploymentModelName
output AZURE_OPENAI_EMBEDDING_MODEL string = embeddingModelName
output AZURE_OPENAI_EMBEDDING_DIMENSIONS string = '1536'
output AZURE_OPENAI_API_VERSION string = foundryApiVersion

output AZURE_AI_SEARCH_NAME string = search.outputs.searchName
output AZURE_AI_SEARCH_ENDPOINT string = search.outputs.searchEndpoint
output AZURE_AI_SEARCH_INDEX_NAME string = aiSearchIndexName

output DEFAULT_DOMAIN string = containerApps.outputs.defaultDomain
output MCP_SERVER_URL string = '${mcpServer.outputs.SERVICE_SERVER_URI}/mcp'

