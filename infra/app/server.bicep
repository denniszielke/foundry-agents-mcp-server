// Container App for the Foundry Agents MCP Server
param name string
param location string
param tags object = {}

param containerAppsEnvironmentId string
param containerRegistryName string
param managedIdentityId string
param managedIdentityClientId string
param exists bool = false

// Runtime configuration
param applicationInsightsConnectionString string = ''
param azureAiProjectEndpoint string = ''
param azureAiSearchEndpoint string = ''
param azureAiSearchIndexName string = 'project-log-index'
param azureOpenAiEndpoint string = ''
param azureOpenAiEmbeddingModel string = 'text-embedding-3-small'
param azureOpenAiEmbeddingDimensions string = '1536'
param azureOpenAiCompletionModel string = ''

// ── Placeholder image used on first deploy before azd builds the real one ─────
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var containerImage = exists ? '${containerRegistryName}.azurecr.io/foundry-agents-mcp-server:latest' : placeholderImage

// ── Container App ─────────────────────────────────────────────────────────────

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerAppsEnvironmentId
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: '${containerRegistryName}.azurecr.io'
          identity: managedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp-server'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'RUNNING_IN_PRODUCTION',              value: 'true' }
            { name: 'AZURE_CLIENT_ID',                    value: managedIdentityClientId }
            { name: 'TRANSPORT',                          value: 'http' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: applicationInsightsConnectionString }
            { name: 'AZURE_AI_PROJECT_ENDPOINT',          value: azureAiProjectEndpoint }
            { name: 'AZURE_AI_SEARCH_ENDPOINT',           value: azureAiSearchEndpoint }
            { name: 'AZURE_AI_SEARCH_INDEX_NAME',         value: azureAiSearchIndexName }
            { name: 'AZURE_OPENAI_ENDPOINT',              value: azureOpenAiEndpoint }
            { name: 'AZURE_OPENAI_EMBEDDING_MODEL',       value: azureOpenAiEmbeddingModel }
            { name: 'AZURE_OPENAI_EMBEDDING_DIMENSIONS',  value: azureOpenAiEmbeddingDimensions }
            { name: 'AZURE_OPENAI_COMPLETION_MODEL_NAME', value: azureOpenAiCompletionModel }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────

output fqdn string = app.properties.configuration.ingress.fqdn
output name string = app.name
