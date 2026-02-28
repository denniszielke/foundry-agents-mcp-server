param foundryName string
param principalId string

// Azure AI Developer – access to Azure AI Foundry project: agents, inference, model deployments
var azureAiDeveloperRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '64702f94-c441-49e6-a78b-ef80e0188fee')

// Cognitive Services OpenAI User – call OpenAI-compatible endpoints (embeddings, completions)
var cognitiveServicesOpenAiUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')

resource aiDeveloper 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(subscription().id, resourceGroup().id, principalId, azureAiDeveloperRole)
  properties: {
    roleDefinitionId: azureAiDeveloperRole
    principalType: 'ServicePrincipal'
    principalId: principalId
  }
}

resource cogServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(subscription().id, resourceGroup().id, principalId, cognitiveServicesOpenAiUserRole)
  properties: {
    roleDefinitionId: cognitiveServicesOpenAiUserRole
    principalType: 'ServicePrincipal'
    principalId: principalId
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: foundryName
}
