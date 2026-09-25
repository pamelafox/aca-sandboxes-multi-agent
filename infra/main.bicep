// ============================================================================
// ACA Sandboxes — Research Agent Swarm Infrastructure
// ============================================================================
// Deploys: Azure OpenAI, ACR, ACA Environment + Orchestrator app,
//          and a Microsoft.App/sandboxGroups resource for the research swarm.
//
// Sandboxes themselves are dynamic: the orchestrator creates them at runtime
// against the sandbox group via the data plane (management.azuredevcompute.io).
//
// NOTE on disk images: Disk images live behind the *data plane* of the sandbox
// group, not ARM, so they cannot be pre-created in Bicep. The orchestrator
// pre-warms a disk image in its FastAPI lifespan startup hook (see
// `orchestrator.py`) so the first user request doesn't pay the ~25 s build
// cost. The disk image is then cached by ACR manifest digest across runs and
// only rebuilt when a new image is pushed (or via the UI's Re-create button).
// ============================================================================

targetScope = 'resourceGroup'

// ── Parameters ──────────────────────────────────────────────────────────────

@description('Base name prefix for all resources')
param prefix string = 'aca-sandboxes-agents'

@description('Azure region for deployment')
param location string = resourceGroup().location

@description('Azure region for the Azure OpenAI account. Defaults to westus3 because gpt-5.6-luna is not available in every region.')
param openAiLocation string = 'westus'

@description('gpt-5.6-luna model version.')
param openAiModelVersion string = '2026-07-09'

@description('gpt-5.6-luna deployment capacity. Must fit the available quota for the model, SKU, and region.')
@minValue(1)
param openAiModelCapacity int = 750

@description('Container image for the orchestrator. Pass empty on first deploy; update after pushing the image. AZD/setup.sh sets this automatically.')
param orchestratorImage string = ''

@description('Container image for the research agent (used at runtime by sandboxes). Pass empty on first deploy.')
param researchAgentImage string = ''

@description('Tag value used by `azd` to associate this resource with the deployed service. Leave default unless you customize azure.yaml.')
param azdServiceName string = 'orchestrator'

@description('Tag value used by `azd` to identify the environment.')
param azdEnvName string = ''

@description('Microsoft Entra object ID supplied by azd. Grants the data-plane roles needed to run the orchestrator locally.')
param principalId string = ''

@description('ACR SKU')
@allowed(['Basic', 'Standard', 'Premium'])
param acrSku string = 'Basic'

// ── Variables ───────────────────────────────────────────────────────────────

var uniqueSuffix        = uniqueString(resourceGroup().id)
var acrName             = replace('${prefix}acr${uniqueSuffix}', '-', '')
var openAiName          = '${prefix}-openai-${uniqueSuffix}'
var aiProjectName       = '${prefix}-proj'
var logAnalyticsName    = '${prefix}-logs-${uniqueSuffix}'
var appInsightsName     = '${prefix}-appi-${uniqueSuffix}'
var acaEnvName          = '${prefix}-env'
var orchestratorAppName = '${prefix}-orch'
var sandboxGroupName    = '${prefix}-sg-${location}'
var orchestratorUamiName = '${prefix}-orch-uami'
var sandboxGroupUamiName = '${prefix}-sg-uami'

// Built-in role definition IDs
var acrPullRoleId                 = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var cognitiveServicesOpenAIUserId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
// Azure AI User (a.k.a. Foundry User): data-plane role for using Foundry
// projects and their hosted tools (e.g. hosted web search / grounding).
var foundryUserRoleId             = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
// Custom role: Dev Compute SandboxGroup Data Owner
var sandboxGroupDataOwnerRoleId   = 'c24cf47c-5077-412d-a19c-45202126392c'

// Resource IDs computed as strings (force runtime resolution; works around Bicep
// symbolic-name codegen that strips `identity` from preview-API resources).
var orchestratorAppResourceId = resourceId('Microsoft.App/containerApps', orchestratorAppName)
var sandboxGroupResourceId    = resourceId('Microsoft.App/sandboxGroups', sandboxGroupName)

// ── User-Assigned Managed Identities ────────────────────────────────────────
// UAMIs expose principalId reliably at template-eval time, independent of the
// host resource's API version (avoids preview-API identity-resolution issues).

resource orchestratorUami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: orchestratorUamiName
  location: location
}

resource sandboxGroupUami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: sandboxGroupUamiName
  location: location
}

// Placeholder image used on first deploy (so the app provisions even before the user pushes an orchestrator image)
var quickstartImage = 'mcr.microsoft.com/k8se/quickstart:latest'

// ── Log Analytics Workspace ─────────────────────────────────────────────────

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Application Insights (workspace-based) ──────────────────────────────────
// Backs the orchestrator's OpenTelemetry traces/metrics/logs so agent runs,
// tool calls, and sandbox lifecycle spans are queryable end-to-end.
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
  }
}

// ── Azure Container Registry ────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: { name: acrSku }
  properties: {
    adminUserEnabled: true
  }
}

// ── Azure AI Foundry account + project ──────────────────────────────────────
// AIServices-kind account with project management enabled. Serves the OpenAI
// data plane (used by the orchestrator + the researcher's AOAI fallback) AND
// hosts a Foundry project whose hosted web-search tool the researcher uses for
// grounding. NOTE: changing an existing account's `kind` is not an in-place
// update; on a resource group that previously deployed a `kind: OpenAI`
// account under this name, delete the old account before redeploying.

resource openAi 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: openAiName
  location: openAiLocation
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
    allowProjectManagement: true
  }
}

resource openaiModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: 'gpt-5.6-luna'
  sku: {
    name: 'GlobalStandard'
    capacity: openAiModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.6-luna'
      version: openAiModelVersion
    }
  }
}

// Foundry project (child of the AIServices account). The project endpoint is
// what the researcher's FoundryChatClient targets for hosted web search.
resource aiProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: openAi
  name: aiProjectName
  location: openAiLocation
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

// Foundry project data-plane endpoint (form: <account>.services.ai.azure.com/api/projects/<project>).
var foundryProjectEndpoint = 'https://${openAiName}.services.ai.azure.com/api/projects/${aiProjectName}'

// ── ACA Environment ─────────────────────────────────────────────────────────

resource acaEnvironment 'Microsoft.App/managedEnvironments@2026-03-02-preview' = {
  name: acaEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ── Sandbox Group (the official ACA Sandboxes resource) ─────────────────────
// Sandboxes are created dynamically by the orchestrator at runtime against
// this group via Microsoft.Adc.Arm.Client (data plane).

resource sandboxGroup 'Microsoft.App/sandboxGroups@2026-02-01-preview' = {
  name: sandboxGroupName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${sandboxGroupUami.id}': {}
    }
  }
  properties: {
    imageRegistryCredentials: [
      {
        server: acr.properties.loginServer
        identity: sandboxGroupUami.id
      }
    ]
  }
}

// ── ACA Orchestrator Container App ──────────────────────────────────────────

resource orchestratorApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: orchestratorAppName
  location: location
  // Tags consumed by `azd` to wire `azd deploy <service>` to this resource.
  tags: union(
    { 'azd-service-name': azdServiceName },
    empty(azdEnvName) ? {} : { 'azd-env-name': azdEnvName }
  )
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${orchestratorUami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnvironment.id
    configuration: {
      secrets: [
        // ACR admin credentials for disk-image pulls. The sandbox compute plane
        // cannot yet authenticate ACR pulls with a managed identity, so the
        // disk-image create call passes registry credentials explicitly. This is
        // scoped to the orchestrator's internal bootstrap; sandbox egress stays
        // keyless and default-deny.
        { name: 'acr-username', value: acr.listCredentials().username }
        { name: 'acr-password', value: acr.listCredentials().passwords[0].value }
      ]
      ingress: {
        external: true
        targetPort: 5000
        transport: 'http'
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'orchestrator'
          image: !empty(orchestratorImage) ? orchestratorImage : quickstartImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            // Keyless AOAI auth: the orchestrator MI has 'Cognitive Services
            // OpenAI User' (granted below) and acquires bearer tokens at runtime.
            { name: 'AZURE_CLIENT_ID',         value: orchestratorUami.properties.clientId }
            { name: 'AZURE_OPENAI_ENDPOINT',   value: openAi.properties.endpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: openaiModelDeployment.name }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'SUBSCRIPTION_ID',         value: subscription().subscriptionId }
            { name: 'RESOURCE_GROUP',          value: resourceGroup().name }
            { name: 'SANDBOX_GROUP',           value: sandboxGroupName }
            { name: 'SANDBOX_GROUP_UAMI_RESOURCE_ID', value: sandboxGroupUami.id }
            { name: 'SANDBOX_GROUP_UAMI_CLIENT_ID', value: sandboxGroupUami.properties.clientId }
            { name: 'DEFAULT_REGION',          value: location }
            { name: 'ACR_LOGIN_SERVER',        value: acr.properties.loginServer }
            { name: 'ACR_USERNAME',            secretRef: 'acr-username' }
            { name: 'ACR_PASSWORD',            secretRef: 'acr-password' }
            { name: 'DISK_IMAGE_ID',           value: !empty(researchAgentImage) ? researchAgentImage : '${acr.properties.loginServer}/research-agent:latest' }
            // OpenTelemetry → Application Insights. Drives agent-run / tool-call /
            // sandbox spans. The same connection string is forwarded into each
            // sandbox so the in-sandbox research agent reports to the same trace.
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'OTEL_SERVICE_NAME', value: 'orchestrator' }
            { name: 'ENABLE_INSTRUMENTATION', value: 'true' }
            { name: 'ENABLE_SENSITIVE_DATA',  value: 'true' }
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

// ── Role Assignments ────────────────────────────────────────────────────────

// Orchestrator → AcrPull on ACR (so ACA can pull the orchestrator image)
resource orchestratorAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, orchestratorUami.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: orchestratorUami.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

// Orchestrator → Cognitive Services OpenAI User on the AOAI account
resource orchestratorOpenAiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAi.id, orchestratorUami.id, cognitiveServicesOpenAIUserId)
  scope: openAi
  properties: {
    principalId: orchestratorUami.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserId)
    principalType: 'ServicePrincipal'
  }
}

// Orchestrator → Foundry User (Azure AI User) on the AOAI/Foundry account
// REQUIRED so the orchestrator can mint an ai.azure.com-scoped token that the
// researcher uses (via FoundryChatClient) to call the project's hosted web search.
resource orchestratorFoundryUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAi.id, orchestratorUami.id, foundryUserRoleId)
  scope: openAi
  properties: {
    principalId: orchestratorUami.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

// Orchestrator → Dev Compute SandboxGroup Data Owner on the sandbox group
// REQUIRED for the orchestrator to call the data plane (create disk images, sandboxes, etc.)
resource orchestratorSandboxDataOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sandboxGroupResourceId, orchestratorUami.id, sandboxGroupDataOwnerRoleId)
  scope: sandboxGroup
  properties: {
    principalId: orchestratorUami.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sandboxGroupDataOwnerRoleId)
    principalType: 'ServicePrincipal'
  }
}

// Sandbox Group's user-assigned identity → AcrPull on ACR
// REQUIRED so the sandbox group can pull the research-agent image from ACR
resource sandboxGroupAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, sandboxGroupUami.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: sandboxGroupUami.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

// Optional local developer access. Keep the parameter empty for deployments
// that do not need to run the orchestrator outside Azure Container Apps.
resource localDeveloperAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(acr.id, principalId, acrPullRoleId)
  scope: acr
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

resource localDeveloperOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(openAi.id, principalId, cognitiveServicesOpenAIUserId)
  scope: openAi
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserId)
  }
}

resource localDeveloperFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(openAi.id, principalId, foundryUserRoleId)
  scope: openAi
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
  }
}

resource localDeveloperSandboxDataOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(sandboxGroupResourceId, principalId, sandboxGroupDataOwnerRoleId)
  scope: sandboxGroup
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sandboxGroupDataOwnerRoleId)
  }
}

// ── Outputs ─────────────────────────────────────────────────────────────────

output acrLoginServer                  string = acr.properties.loginServer
output acrName                         string = acr.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.properties.loginServer
output openAiEndpoint          string = openAi.properties.endpoint
output openAiDeployment        string = openaiModelDeployment.name
output foundryProjectEndpoint  string = foundryProjectEndpoint
output acaEnvironmentName      string = acaEnvironment.name
output orchestratorAppName     string = orchestratorApp.name
output orchestratorFqdn        string = orchestratorApp.properties.configuration.ingress.fqdn
output orchestratorUrl         string = 'https://${orchestratorApp.properties.configuration.ingress.fqdn}'
output orchestratorPrincipalId string = orchestratorUami.properties.principalId
output sandboxGroupName        string = sandboxGroup.name
output sandboxGroupId          string = sandboxGroup.id
output SANDBOX_GROUP_UAMI_RESOURCE_ID string = sandboxGroupUami.id
output SANDBOX_GROUP_UAMI_CLIENT_ID string = sandboxGroupUami.properties.clientId
output resourceGroupName       string = resourceGroup().name
output subscriptionId          string = subscription().subscriptionId
output applicationInsightsName string = appInsights.name
output applicationInsightsConnectionString string = appInsights.properties.ConnectionString
