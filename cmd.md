## ​​🌍 Base URLs

### Production

```
https://api.robogenic.site/blob
```

### Local (development)

```
http://127.0.0.1:5000
```

---

## ✅ 1. Upload File (Direct API Upload)

### 🔹 Linux / macOS (bash)

```bash
curl -X POST https://api.robogenic.site/blob/upload   -F "user_id=USER123"   -F "file=@ToDo.md"
```

### 🔹 Windows PowerShell

```powershell
curl.exe -X POST https://api.robogenic.site/blob/upload `  -F "user_id=USER123" `  -F "file=@ToDo.md"
```

### ✅ Response

```json
{  "key": "USER123/xxxxxxxx_ToDo.md",  "fileUrl": "http://coolify.navrobotec.online:8333/uploads/USER123/xxxxxxxx_ToDo.md"}
```

📌 File is immediately visible in:

-   SeaweedFS Filer UI
-   S3
-   `/files` API

---

## ✅ 2. List User Files

### 🔹 Linux / macOS

```bash
curl "https://api.robogenic.site/blob/files?user_id=USER123"
```

### 🔹 Windows PowerShell

```powershell
curl.exe "https://api.robogenic.site/blob/files?user_id=USER123"
```

### ✅ Response

```json
{  "count": 1,  "files": [    {      "key": "USER123/xxxxxxxx_ToDo.md",      "fileUrl": "http://coolify.navrobotec.online:8333/uploads/USER123/xxxxxxxx_ToDo.md",      "size": 181,      "last_modified": "2026-01-11T09:37:22Z"    }  ]}
```

📌 Listing is **always accurate**, even if files were uploaded:

-   via Filer UI
-   via presigned URL
-   via S3 client

---

## ✅ 3. Download File (Presigned URL)

### 🔹 Linux / macOS

```bash
curl -X POST http://127.0.0.1:5000/download   -H "Content-Type: application/json"   -d '{"key":"USER123/xxxxxxxx_ToDo.md"}'
```

### 🔹 Windows PowerShell (correct way)

```powershell
$body = @{  key = "USER123/xxxxxxxx_ToDo.md"} | ConvertTo-Jsoncurl.exe -X POST http://127.0.0.1:5000/download `  -H "Content-Type: application/json" `  -d $body
```

### ✅ Response

```json
{  "downloadUrl": "http://coolify.navrobotec.online:8333/uploads/USER123/xxxxxxxx_ToDo.md?X-Amz-Algorithm=AWS4-HMAC-SHA256&..."}
```

➡ Open this URL in **any browser** (valid until expiry).

---

## ✅ 4. Delete File

### 🔹 Linux / macOS

```bash
curl -X POST http://127.0.0.1:5000/delete   -H "Content-Type: application/json"   -d '{"key":"USER123/xxxxxxxx_ToDo.md"}'
```

### 🔹 Windows PowerShell

```powershell
$body = @{  key = "USER123/xxxxxxxx_ToDo.md"} | ConvertTo-Jsoncurl.exe -X POST http://127.0.0.1:5000/delete `  -H "Content-Type: application/json" `  -d $body
```

### ✅ Response

```json
{  "message": "Deleted"}
```

📌 File is removed from:

-   SeaweedFS
-   S3
-   Filer UI
-   future listings

---

## ✅ 5. Presigned Upload (Large Files – Recommended)

### 1️⃣ Generate Presigned URL

#### Linux / macOS

```bash
curl -X POST http://127.0.0.1:5000/presign-upload   -H "Content-Type: application/json"   -d '{    "user_id": "USER123",    "filename": "video.mp4",    "content_type": "video/mp4"  }'
```

#### Windows PowerShell

```powershell
$body = @{  user_id      = "USER123"  filename     = "video.mp4"  content_type = "video/mp4"} | ConvertTo-Jsoncurl.exe -X POST http://127.0.0.1:5000/presign-upload `  -H "Content-Type: application/json" `  -d $body
```

### ✅ Response

```json
{  "uploadUrl": "http://coolify.navrobotec.online:8333/uploads/USER123/xxxxxxxx_video.mp4?...",  "key": "USER123/xxxxxxxx_video.mp4",  "fileUrl": "http://coolify.navrobotec.online:8333/uploads/USER123/xxxxxxxx_video.mp4"}
```

---

### 2️⃣ Upload File Directly to SeaweedFS

```bash
curl -X PUT "<uploadUrl>"   -H "Content-Type: video/mp4"   --upload-file video.mp4
```

📌 **No register step**📌 File is instantly available

---

## 🧱 Folder = Schema

```
uploads/  USER123/    <uuid>_file.ext
```