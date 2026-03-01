#!/bin/bash
set -e

AZURE_ENV_NAME="$1"
if [ "$AZURE_ENV_NAME" == "" ]; then
    echo "No environment name provided - aborting"
    exit 0;
fi

RESOURCE_GROUP="rg-$AZURE_ENV_NAME"

if [ $(az group exists --name $RESOURCE_GROUP) = false ]; then
    echo "resource group $RESOURCE_GROUP does not exist - run 'azd up' first"
    exit 1
else
    echo "resource group $RESOURCE_GROUP already exists"
    LOCATION=$(az group show -n $RESOURCE_GROUP --query location -o tsv)
fi

APPINSIGHTS_NAME=$(az resource list -g $RESOURCE_GROUP --resource-type "Microsoft.Insights/components" --query "[0].name" -o tsv)
AZURE_CONTAINER_REGISTRY_NAME=$(az resource list -g $RESOURCE_GROUP --resource-type "Microsoft.ContainerRegistry/registries" --query "[0].name" -o tsv)
FOUNDRY_NAME=$(az resource list -g $RESOURCE_GROUP --resource-type "Microsoft.CognitiveServices/accounts" --query "[0].name" -o tsv)
ENVIRONMENT_NAME=$(az resource list -g $RESOURCE_GROUP --resource-type "Microsoft.App/managedEnvironments" --query "[0].name" -o tsv)
IDENTITY_NAME=$(az resource list -g $RESOURCE_GROUP --resource-type "Microsoft.ManagedIdentity/userAssignedIdentities" --query "[0].name" -o tsv)
SEARCH_NAME=$(az resource list -g $RESOURCE_GROUP --resource-type "Microsoft.Search/searchServices" --query "[0].name" -o tsv)
ENVIRONMENT_ID=$(az resource list -g $RESOURCE_GROUP --resource-type "Microsoft.App/managedEnvironments" --query "[0].id" -o tsv)

AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv)

DEFAULT_DOMAIN=$(az rest --method get \
    --url "https://management.azure.com/$ENVIRONMENT_ID?api-version=2024-03-01" \
    --query "properties.defaultDomain" -o tsv)

FOUNDRY_ENDPOINT="https://$FOUNDRY_NAME.openai.azure.com"
FOUNDRY_PROJECT_ENDPOINT="https://$FOUNDRY_NAME.services.ai.azure.com/api/projects/$FOUNDRY_NAME"
SEARCH_ENDPOINT="https://$SEARCH_NAME.search.windows.net"

AZURE_AI_SEARCH_INDEX_NAME="project-log-index"
COMPLETION_DEPLOYMENT_MODEL_NAME="gpt-5-nano"
EMBEDDING_DEPLOYMENT_MODEL_NAME="text-embedding-3-small"
FOUNDRY_API_VERSION="2024-10-21"

SERVICE_NAME="mcp-server"
IMAGE_TAG=$(date +%Y%m%d%H%M%S)

echo "container registry name: $AZURE_CONTAINER_REGISTRY_NAME"
echo "application insights name: $APPINSIGHTS_NAME"
echo "foundry name: $FOUNDRY_NAME"
echo "environment name: $ENVIRONMENT_NAME"
echo "identity name: $IDENTITY_NAME"
echo "search name: $SEARCH_NAME"
echo "default domain: $DEFAULT_DOMAIN"

echo "building image $SERVICE_NAME:$IMAGE_TAG in ACR $AZURE_CONTAINER_REGISTRY_NAME"

az acr build --registry ${AZURE_CONTAINER_REGISTRY_NAME} \
    --image $SERVICE_NAME:$IMAGE_TAG \
    --file ./Dockerfile .

IMAGE_NAME="${AZURE_CONTAINER_REGISTRY_NAME}.azurecr.io/$SERVICE_NAME:$IMAGE_TAG"

echo "deploying image: $IMAGE_NAME"

az deployment group create -g $RESOURCE_GROUP -f ./infra/app/server.bicep \
    -p name=$SERVICE_NAME \
    -p location=$LOCATION \
    -p containerAppsEnvironmentName=$ENVIRONMENT_NAME \
    -p containerRegistryName=$AZURE_CONTAINER_REGISTRY_NAME \
    -p applicationInsightsName=$APPINSIGHTS_NAME \
    -p foundryName=$FOUNDRY_NAME \
    -p foundryEndpoint=$FOUNDRY_ENDPOINT \
    -p foundryProjectEndpoint=$FOUNDRY_PROJECT_ENDPOINT \
    -p searchName=$SEARCH_NAME \
    -p searchEndpoint=$SEARCH_ENDPOINT \
    -p searchIndexName=$AZURE_AI_SEARCH_INDEX_NAME \
    -p completionDeploymentModelName=$COMPLETION_DEPLOYMENT_MODEL_NAME \
    -p embeddingDeploymentModelName=$EMBEDDING_DEPLOYMENT_MODEL_NAME \
    -p foundryApiVersion=$FOUNDRY_API_VERSION \
    -p identityName=$IDENTITY_NAME \
    -p imageName=$IMAGE_NAME \
    --query properties.outputs

echo ""
echo "deployment complete"
echo "MCP server URL: https://$SERVICE_NAME.$DEFAULT_DOMAIN/mcp"
