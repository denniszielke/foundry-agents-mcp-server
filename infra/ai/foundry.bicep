param name string
param location string = resourceGroup().location
param tags object = {}
param capacity int = 30

param publicNetworkAccess string = 'Enabled'
param sku object = {
  name: 'S0'
}

param customDomainName string
param deployments array

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: sku
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: customDomainName
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
    publicNetworkAccess: publicNetworkAccess
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    description: name
    displayName: name
  }
}

@batchSize(1)
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [for dep in deployments: {
  parent: account
  name: dep.name
  sku: {
    name: dep.sku
    capacity: capacity
  }
  properties: {
    model: dep.model
  }
}]

// OpenAI-compatible endpoint (for AzureOpenAI client – embeddings, chat completions)
output openaiEndpoint string = account.properties.endpoint
// AI Foundry project endpoint (for AIProjectClient – agents API)
output foundryProjectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output foundryName string = account.name
