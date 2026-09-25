param([switch]$Help)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

if ($Help) {
    Write-Output @'
Build and push the sandbox-agent image using Azure Container Registry.
Usage: pwsh -File sandbox-agent/build.ps1
Environment overrides: SUBSCRIPTION_ID, RESOURCE_GROUP, ACR_NAME
Missing settings are read with azd env get-value.
Optional environment: IMAGE_TAG (default: latest)
Saves SANDBOX_AGENT_IMAGE when an azd environment is selected.
Requires Azure CLI authentication. Prints the image reference to stdout.
'@
    exit 0
}
if ($args.Count -ne 0) {
    throw 'Unexpected arguments. Use -Help for usage.'
}

function Get-BuildSetting([string]$Variable, [string]$AzdVariable) {
    $value = [Environment]::GetEnvironmentVariable($Variable)
    if (-not $value) {
        if (-not (Get-Command azd -ErrorAction SilentlyContinue)) {
            throw "Set $Variable or install azd to read deployment settings."
        }
        $value = azd env get-value $AzdVariable
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to read $AzdVariable from azd."
        }
    }
    if (-not $value) { throw "Set $Variable or run azd up first." }
    return $value
}

$subscriptionId = Get-BuildSetting 'SUBSCRIPTION_ID' 'AZURE_SUBSCRIPTION_ID'
$resourceGroup = Get-BuildSetting 'RESOURCE_GROUP' 'AZURE_RESOURCE_GROUP'
$acrName = Get-BuildSetting 'ACR_NAME' 'acrName'
$imageTag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { 'latest' }

$acrEndpoint = az acr show --subscription $subscriptionId --resource-group $resourceGroup `
    --name $acrName --query loginServer --output tsv
if ($LASTEXITCODE -ne 0) { throw "Registry lookup failed with exit code $LASTEXITCODE." }
if (-not $acrEndpoint) { throw 'The registry did not return a login server.' }

az acr build --subscription $subscriptionId --resource-group $resourceGroup `
    --registry $acrName --image "sandbox-agent:$imageTag" --platform linux/amd64 `
    --no-logs $PSScriptRoot | ForEach-Object { [Console]::Error.WriteLine($_) }
if ($LASTEXITCODE -ne 0) { throw "az acr build failed with exit code $LASTEXITCODE." }

$imageRef = "$acrEndpoint/sandbox-agent:$imageTag"
$hasEnvironment = $false
if (Get-Command azd -ErrorAction SilentlyContinue) {
    azd env get-value AZURE_ENV_NAME *> $null
    $hasEnvironment = $LASTEXITCODE -eq 0
}
if ($hasEnvironment) {
    azd env set SANDBOX_AGENT_IMAGE $imageRef | ForEach-Object { [Console]::Error.WriteLine($_) }
    if ($LASTEXITCODE -ne 0) { throw "Saving SANDBOX_AGENT_IMAGE failed with exit code $LASTEXITCODE." }
} else {
    [Console]::Error.WriteLine('No selected azd environment; use the printed image reference with --image.')
}

Write-Output $imageRef