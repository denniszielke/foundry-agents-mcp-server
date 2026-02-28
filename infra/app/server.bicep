param name string
param location string = resourceGroup().location
param tags object = {}

param foundryName string
param foundryEndpoint string
param foundryProjectEndpoint string

param searchName string
param searchEndpoint string
param searchIndexName string

param completionDeploymentModelName string
param embeddingDeploymentModelName string
param foundryApiVersion string

param identityName string
param applicationInsightsName string
param containerAppsEnvironmentName string
param containerRegistryName string
param serviceName string = 'server'
param imageName string
param usePrivateIngress bool = false

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

module app '../core/host/container-app-upsert.bicep' = {
  name: '${serviceName}-container-app'
  params: {
    name: name
    location: location
    imageName: imageName
    tags: union(tags, { 'azd-service-name': serviceName })
    identityName: identityName
    foundryName: foundryName
    containerAppsEnvironmentName: containerAppsEnvironmentName
    containerRegistryName: containerRegistryName
    searchName: searchName
    external: !usePrivateIngress
    targetPort: 8000
    env: [
      {
        name: 'RUNNING_IN_PRODUCTION'
        value: 'true'
      }
      {
        name: 'AZURE_CLIENT_ID'
        value: apiIdentity.properties.clientId
      }
      {
        name: 'TRANSPORT'
        value: 'http'
      }
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: applicationInsights.properties.ConnectionString
      }
      {
        name: 'AZURE_AI_PROJECT_ENDPOINT'
        value: foundryProjectEndpoint
      }
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: foundryEndpoint
      }
      {
        name: 'AZURE_OPENAI_COMPLETION_MODEL_NAME'
        value: completionDeploymentModelName
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_MODEL'
        value: embeddingDeploymentModelName
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_DIMENSIONS'
        value: '1536'
      }
      {
        name: 'AZURE_OPENAI_API_VERSION'
        value: foundryApiVersion
      }
      {
        name: 'AZURE_AI_SEARCH_ENDPOINT'
        value: searchEndpoint
      }
      {
        name: 'AZURE_AI_SEARCH_INDEX_NAME'
        value: searchIndexName
      }
    ]
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

output SERVICE_SERVER_IDENTITY_PRINCIPAL_ID string = apiIdentity.properties.principalId
output SERVICE_SERVER_NAME string = app.outputs.name
output SERVICE_SERVER_URI string = app.outputs.uri
output SERVICE_SERVER_IMAGE_NAME string = app.outputs.imageName
