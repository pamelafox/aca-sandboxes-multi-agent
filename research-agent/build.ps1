$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$vals = azd env get-values
if ($LASTEXITCODE -ne 0) { throw "azd env get-values failed with exit code $LASTEXITCODE" }
$acrName = $vals | Select-String '^acrName="(.*)"' | ForEach-Object { $_.Matches.Groups[1].Value }
$rg = $vals | Select-String '^AZURE_RESOURCE_GROUP="(.*)"' | ForEach-Object { $_.Matches.Groups[1].Value }
if (-not $acrName) { throw "acrName not found in azd env. Did 'azd provision' succeed?" }

$acrArgs = @('acr', 'build', '--registry', $acrName, '--image', 'research-agent:latest', '--no-logs')
if ($rg) { $acrArgs += @('--resource-group', $rg) }
Write-Host "Building research-agent image into $acrName (rg=$rg)..."
az @acrArgs $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw "az acr build failed with exit code $LASTEXITCODE" }
Write-Host 'research-agent image built successfully.'