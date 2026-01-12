param (
    [Parameter(Mandatory=$true)]
    [string]$UserId,

    [Parameter(Mandatory=$true)]
    [string]$FilePath
)

$ApiBase = "https://s3-server.navrobotec.online"
# $ApiBase = "http://127.0.0.1:5000"
$ContentType = "application/octet-stream"
$FileName = [System.IO.Path]::GetFileName($FilePath)

Write-Host "▶ Presigning upload..."

# 1️⃣ Presign
$presignBody = @{
    user_id      = $UserId
    filename     = $FileName
    content_type = $ContentType
} | ConvertTo-Json

$presign = curl.exe -s -X POST "$ApiBase/presign-upload" `
    -H "Content-Type: application/json" `
    -d $presignBody | ConvertFrom-Json

if (-not $presign.uploadUrl) {
    Write-Error "Presign failed"
    exit 1
}

Write-Host "✔ Presigned"

# 2️⃣ Upload directly to SeaweedFS
Write-Host "▶ Uploading file to SeaweedFS (direct)..."

curl.exe -s -X PUT $presign.uploadUrl `
    -H "Content-Type: $ContentType" `
    --upload-file "$FilePath"

Write-Host "✔ Upload complete"

Write-Host "✅ DONE"
Write-Host "File URL:"
Write-Host $presign.fileUrl
