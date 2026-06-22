param (
    [string]$Version = "2.0.0"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Starting local deployment process (Version: $Version) ===" -ForegroundColor Cyan

Write-Host "Step 1/5: Checking if Docker is running..." -ForegroundColor Yellow
try {
    $dockerCheck = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker is not running or not accessible. Please start Docker Desktop."
        exit 1
    }
} catch {
    Write-Error "Docker command not found. Please install Docker."
    exit 1
}

Write-Host "Step 1.5: Updating version to $Version in main.py..." -ForegroundColor Yellow
$mainPath = "main.py"
if (Test-Path $mainPath) {
    $mainContent = Get-Content -Raw -Path $mainPath
    $updatedContent = $mainContent -replace '\bversion\s*=\s*"[^"]*"', "version=`"$Version`""
    Set-Content -Path $mainPath -Value $updatedContent
    Write-Host "Updated version successfully in $mainPath" -ForegroundColor Green
} else {
    Write-Warning "main.py not found at $mainPath. Skipping version update in code."
}

Write-Host "Step 2/5: Building Docker image..." -ForegroundColor Yellow
docker build -t ai-corrector-demo:latest .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed."
    exit 1
}

Write-Host "Step 3/5: Tagging Docker image..." -ForegroundColor Yellow
$imageTag = "lmsaicorrectorregistry.azurecr.io/ai-corrector-demo:$Version"
docker tag ai-corrector-demo:latest $imageTag
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker tag failed."
    exit 1
}

Write-Host "Step 4/5: Logging in to Azure Container Registry (ACR) and pushing..." -ForegroundColor Yellow
az acr login --name lmsaicorrectorregistry
if ($LASTEXITCODE -ne 0) {
    Write-Error "Azure ACR login failed. Please ensure you are logged into Azure via 'az login'."
    exit 1
}
docker push $imageTag
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker push to ACR failed."
    exit 1
}

Write-Host "Step 5/5: Updating Azure Container App..." -ForegroundColor Yellow
az containerapp update --name ai-corrector-app --resource-group LMS-AI-CORRECTOR --image $imageTag
if ($LASTEXITCODE -ne 0) {
    Write-Error "Azure Container App update failed."
    exit 1
}

Write-Host "=== Deployment successful! ===" -ForegroundColor Green
