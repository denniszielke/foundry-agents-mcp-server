param searchName string
param principalId string

// Search Index Data Contributor
var searchIndexDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')

resource searchAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(subscription().id, resourceGroup().id, principalId, searchIndexDataContributorRole)
  properties: {
    roleDefinitionId: searchIndexDataContributorRole
    principalType: 'ServicePrincipal'
    principalId: principalId
  }
}

resource search 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: searchName
}
