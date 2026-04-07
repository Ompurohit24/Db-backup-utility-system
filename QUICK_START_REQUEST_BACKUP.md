# 🚀 Quick Start - Request Incremental Backup

## Simplest Way: Single API Call

### 1️⃣ Get Your JWT Token

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

💾 **Save the `access_token` value**

---

### 2️⃣ Find Your Database Configuration ID

```bash
curl -X GET http://localhost:8000/databases \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

**Response:**
```json
{
  "databases": [
    {
      "$id": "db_config_123",
      "database_type": "mysql",
      "host": "192.168.1.100",
      "port": 3306,
      "database_name": "my_app_db",
      "created_at": "2026-03-28T10:00:00Z"
    }
  ]
}
```

💾 **Save the `$id` value** (e.g., `db_config_123`)

---

### 3️⃣ Request First Backup (FULL)

```bash
curl -X POST http://localhost:8000/databases/db_config_123/backup \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"
```

**Response (First Backup - FULL):**
```json
{
  "backup_id": "file_abc123",
  "success": true,
  "message": "Backup completed.",
  "database_type": "mysql",
  "database_name": "my_app_db",
  "file_name": "backup_2026_04_01_full.gz.enc",
  "file_size": 5234,
  "compression": "gzip",
  "original_file_name": "backup_2026_04_01_full",
  "original_file_size": 50000,
  "status": "success",
  "created_at": "2026-04-01T13:00:00Z"
}
```

✅ **First backup created successfully!**

---

### 4️⃣ Request Second Backup (INCREMENTAL)

Use the **exact same API call:**

```bash
curl -X POST http://localhost:8000/databases/db_config_123/backup \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"
```

**Response (Second Backup - INCREMENTAL):**
```json
{
  "backup_id": "file_def456",
  "success": true,
  "message": "Backup completed.",
  "database_type": "mysql",
  "database_name": "my_app_db",
  "file_name": "backup_2026_04_01_incremental.gz.enc",
  "file_size": 234,
  "compression": "gzip",
  "original_file_name": "backup_2026_04_01_incremental",
  "original_file_size": 2000,
  "status": "success",
  "created_at": "2026-04-01T14:00:00Z"
}
```

✅ **Second backup (incremental) created successfully!**

📊 **Notice:**
- File size: **5234 → 234 bytes** (96% smaller!)
- Only changes backed up (50 records instead of 1000)
- Much faster operation

---

## 📝 Complete Example Workflow

### Terminal / Command Line

```bash
# Save token to variable
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}' \
  | jq -r '.access_token')

echo "Token: $TOKEN"

# Save db_config_id to variable
DB_ID=$(curl -s -X GET http://localhost:8000/databases \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.databases[0]."$id"')

echo "Database ID: $DB_ID"

# Request backup (first time - FULL)
echo "Requesting FIRST backup..."
curl -X POST http://localhost:8000/databases/$DB_ID/backup \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  | jq '.'

# Wait a bit
sleep 2

# Request backup (second time - INCREMENTAL)
echo "Requesting SECOND backup..."
curl -X POST http://localhost:8000/databases/$DB_ID/backup \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  | jq '.'

# View backup history
echo "Viewing backup history..."
curl -X GET http://localhost:8000/databases/$DB_ID/backups \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.'
```

---

## 🐍 Python Example

```python
import requests
import json
import time

BASE_URL = "http://localhost:8000"

# Login
print("🔐 Logging in...")
auth_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={"email": "user@example.com", "password": "password123"}
)
token = auth_response.json()["access_token"]
print(f"✓ Got token: {token[:20]}...")

headers = {"Authorization": f"Bearer {token}"}

# Get databases
print("\n📋 Getting database configurations...")
db_response = requests.get(f"{BASE_URL}/databases", headers=headers)
db_id = db_response.json()["databases"][0]["$id"]
print(f"✓ Found database: {db_id}")

# First backup
print("\n💾 Requesting FIRST backup (FULL)...")
backup1 = requests.post(
    f"{BASE_URL}/databases/{db_id}/backup",
    headers=headers
).json()
print(f"✓ Backup 1:")
print(f"  ID: {backup1['backup_id']}")
print(f"  Type: {backup1['file_name'].split('_')[-1].split('.')[0]}")
print(f"  Size: {backup1['file_size']} bytes")

# Wait
time.sleep(2)

# Second backup
print("\n💾 Requesting SECOND backup (INCREMENTAL)...")
backup2 = requests.post(
    f"{BASE_URL}/databases/{db_id}/backup",
    headers=headers
).json()
print(f"✓ Backup 2:")
print(f"  ID: {backup2['backup_id']}")
print(f"  Type: {backup2['file_name'].split('_')[-1].split('.')[0]}")
print(f"  Size: {backup2['file_size']} bytes")

# Show savings
savings = ((backup1['file_size'] - backup2['file_size']) / backup1['file_size']) * 100
print(f"\n💰 Storage saved: {savings:.1f}%")
```

---

## 📊 What Happens Behind the Scenes

### First Request

```
POST /databases/db_config_123/backup
    ↓
Check metadata file
    ↓
NOT FOUND → First backup!
    ↓
Type: FULL
    ↓
Fetch all 1000 records from database
    ↓
Create backup JSON (50 MB)
    ↓
Compress with gzip (50 MB → 5 MB)
    ↓
Encrypt with Fernet (5 MB)
    ↓
Upload to Appwrite Storage
    ↓
Save metadata:
{
  "last_backup_time": "2026-04-01T13:00:00Z",
  "backup_type": "full",
  "file_id": "file_abc123"
}
    ↓
Return response with backup details
```

### Second Request

```
POST /databases/db_config_123/backup
    ↓
Check metadata file
    ↓
FOUND → Subsequent backup!
    ↓
Read last_backup_time
    ↓
Type: INCREMENTAL
    ↓
Fetch all 1000 records from database
    ↓
Compare timestamps:
  - Records with created_at > last_backup_time = NEW (30)
  - Records with updated_at > last_backup_time = UPDATED (20)
  - Records with deleted_at > last_backup_time = DELETED (5)
    ↓
Create incremental backup JSON (1 MB)
    ↓
Check if empty → NO, has 50 changes
    ↓
Compress with gzip (1 MB → 0.1 MB)
    ↓
Encrypt with Fernet (0.1 MB)
    ↓
Upload to Appwrite Storage
    ↓
Update metadata:
{
  "last_backup_time": "2026-04-01T14:00:00Z",
  "backup_type": "incremental",
  "file_id": "file_def456"
}
    ↓
Return response with backup details
```

---

## ✨ Key Points

| Question | Answer |
|----------|--------|
| **Do I need to specify "full" or "incremental"?** | ❌ NO - It's automatic! |
| **Same endpoint for both types?** | ✅ YES - Always use `/databases/{id}/backup` |
| **How does it decide?** | Checks if `backup_meta.json` exists |
| **What if file doesn't exist?** | Creates it automatically (first backup) |
| **Can I force a full backup?** | Delete `backup_meta.json` to reset |
| **What if no changes?** | Upload skipped (optimization) |
| **Where's the file stored?** | Appwrite Storage (encrypted) |
| **How to restore?** | Use `/restore` endpoint with backup IDs |

---

## 🔄 Typical Workflow

```
Monday 2 AM:
POST /databases/db_config_123/backup
→ Creates FULL backup (50 MB → 5 MB)

Tuesday 2 AM:
POST /databases/db_config_123/backup
→ Creates INCREMENTAL backup (1 MB → 0.1 MB)
→ 95% smaller! ✅

Wednesday 2 AM:
POST /databases/db_config_123/backup
→ Creates INCREMENTAL backup (0.8 MB → 0.08 MB)

Thursday 2 AM:
POST /databases/db_config_123/backup
→ No changes detected
→ Upload skipped
→ Logs: "No changes to backup"

Total storage used: ~5.2 MB
(vs 200 MB for 4 full backups!) 💰
```

---

## ❓ Frequently Asked Questions

**Q: How do I know if a backup is full or incremental?**
A: Check the response filename - `full` vs `incremental` in the name, or check the `file_size` (incremental is much smaller)

**Q: Can I request backups frequently?**
A: Yes! Empty incrementals are skipped, so no wasted storage

**Q: What if metadata gets corrupted?**
A: Delete `backup_meta.json` and next backup will be full again

**Q: Can I request backup from my frontend?**
A: Yes! Make a POST request from JavaScript/React with the JWT token

**Q: How long does a backup take?**
A: First (full) ~5 sec, Incremental ~0.5 sec, Empty <0.1 sec

---

## 🚀 Frontend Example (React)

```jsx
import React, { useState } from 'react';

function BackupButton({ token, dbConfigId }) {
  const [loading, setLoading] = useState(false);
  const [backup, setBackup] = useState(null);

  const handleBackup = async () => {
    setLoading(true);
    try {
      const response = await fetch(
        `http://localhost:8000/databases/${dbConfigId}/backup`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        }
      );
      
      const data = await response.json();
      setBackup(data);
      console.log('✓ Backup created:', data);
    } catch (error) {
      console.error('✗ Backup failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button onClick={handleBackup} disabled={loading}>
        {loading ? '⏳ Creating backup...' : '💾 Create Backup'}
      </button>
      
      {backup && (
        <div style={{ marginTop: '20px', padding: '10px', border: '1px solid green' }}>
          <h4>✓ Backup Created!</h4>
          <p><strong>Type:</strong> {backup.file_name.includes('full') ? 'FULL' : 'INCREMENTAL'}</p>
          <p><strong>Size:</strong> {(backup.file_size / 1024).toFixed(2)} KB</p>
          <p><strong>Created:</strong> {backup.created_at}</p>
        </div>
      )}
    </div>
  );
}

export default BackupButton;
```

---

**That's it! Just POST to `/databases/{db_config_id}/backup` and the system handles everything automatically! 🎉**

