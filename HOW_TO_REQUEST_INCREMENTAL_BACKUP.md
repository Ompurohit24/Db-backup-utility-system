"""
HOW TO REQUEST AN INCREMENTAL BACKUP

This guide shows all the methods to trigger incremental backups
in your FastAPI application.
"""

# ════════════════════════════════════════════════════════════════════════════
# METHOD 1: VIA REST API ENDPOINT (EASIEST FOR USERS)
# ════════════════════════════════════════════════════════════════════════════

"""
Existing API Endpoint:
POST /databases/{database_config_id}/backup

This endpoint automatically:
1. Checks if it's the first backup → FULL backup
2. Checks if metadata exists → INCREMENTAL backup
3. Prepares appropriate backup type
4. Uploads with compression & encryption
5. Updates metadata

Example Request:
```
curl -X POST http://localhost:8000/databases/db_config_123/backup \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json"
```

Response (First Backup - FULL):
```json
{
  "backup_id": "file_abc123",
  "success": true,
  "message": "Backup completed.",
  "database_type": "mysql",
  "database_name": "my_database",
  "file_name": "backup_2026_04_01_full.gz.enc",
  "file_size": 5234,
  "compression": "gzip",
  "original_file_name": "backup_2026_04_01_full",
  "original_file_size": 50000,
  "status": "success",
  "created_at": "2026-04-01T13:00:00Z"
}
```

Response (Second Backup - INCREMENTAL):
```json
{
  "backup_id": "file_def456",
  "success": true,
  "message": "Backup completed.",
  "database_type": "mysql",
  "database_name": "my_database",
  "file_name": "backup_2026_04_01_incremental.gz.enc",
  "file_size": 234,  // Much smaller!
  "compression": "gzip",
  "original_file_name": "backup_2026_04_01_incremental",
  "original_file_size": 2000,  // Only changes
  "status": "success",
  "created_at": "2026-04-01T14:00:00Z"
}
```
"""

# ════════════════════════════════════════════════════════════════════════════
# METHOD 2: VIA PYTHON (DIRECT SERVICE CALL)
# ════════════════════════════════════════════════════════════════════════════

"""
If calling from within your application:
"""

import asyncio
import json
from app.services.backup_service import trigger_backup
from app.services.incremental_backup_service import IncrementalBackupService
from app.services.metadata_service import get_backup_type_async
from app.services.storage_service import StorageService

async def request_incremental_backup(db_config_id: str, user_id: str):
    """
    Request a backup (automatic full/incremental).
    """
    try:
        # This is the high-level function
        result = await trigger_backup(
            db_config_id=db_config_id,
            user_id=user_id,
            role="user",
            ip_address="192.168.1.1",
            device_info="Browser",
        )
        
        print(f"✓ Backup created: {result['$id']}")
        print(f"  Type: {result.get('backup_type', 'unknown')}")
        print(f"  Size: {result.get('file_size', 0)} bytes")
        return result
    
    except Exception as e:
        print(f"✗ Backup failed: {e}")
        raise

# Usage
# asyncio.run(request_incremental_backup("db_config_123", "user_456"))
"""

# ════════════════════════════════════════════════════════════════════════════
# METHOD 3: LOW-LEVEL CONTROL (ADVANCED)
# ════════════════════════════════════════════════════════════════════════════

"""
If you want explicit control over each step:
"""

async def request_backup_with_explicit_control(db_config_id: str, records: list):
    """
    Explicit control over backup process.
    """
    from app.services.metadata_service import get_backup_type_async, update_metadata_async
    from app.services.incremental_backup_service import IncrementalBackupService
    from app.services.storage_service import StorageService
    from app.utils.incremental_backup_engine import is_empty_incremental
    
    # Step 1: Check backup type
    backup_type = await get_backup_type_async(db_config_id)
    print(f"Backup type: {backup_type}")
    
    # Step 2: Prepare backup
    backup_data = await IncrementalBackupService.prepare_backup_for_external_db(
        records=records,
        db_config_id=db_config_id,
    )
    print(f"Backup prepared: {backup_data['type']}")
    
    # Step 3: Check if empty (optimization)
    if is_empty_incremental(backup_data):
        print("No changes, skipping upload")
        return {"status": "skipped", "reason": "no_changes"}
    
    # Step 4: Upload
    json_content = json.dumps(backup_data)
    file_id, file_name, file_size = await StorageService.upload_backup_file(
        file_content=json_content,
        file_name=f"backup_{backup_type}",
        compress=True,
        encrypt=True,
    )
    print(f"✓ Uploaded: {file_name} ({file_size} bytes)")
    
    # Step 5: Update metadata
    await update_metadata_async(
        db_config_id=db_config_id,
        backup_type=backup_type,
        file_id=file_id,
        file_name=file_name,
        status="success",
    )
    print(f"✓ Metadata updated")
    
    return {
        "status": "success",
        "backup_type": backup_type,
        "file_id": file_id,
        "file_size": file_size,
    }

# Usage
# result = asyncio.run(request_backup_with_explicit_control("db_config_123", records))
"""

# ════════════════════════════════════════════════════════════════════════════
# METHOD 4: SCHEDULED BACKUP (CRON)
# ════════════════════════════════════════════════════════════════════════════

"""
For automated/scheduled backups (already exists in your system):

In app/routes/schedule.py or app/services/schedule_service.py:

from apscheduler.schedulers.background import BackgroundScheduler
from app.services.backup_service import trigger_backup

scheduler = BackgroundScheduler()

async def scheduled_backup_job(db_config_id: str, user_id: str):
    '''Job that runs on a schedule.'''
    try:
        result = await trigger_backup(
            db_config_id=db_config_id,
            user_id=user_id,
            role="system",  # Mark as system-triggered
            device_info="scheduler",
        )
        print(f"✓ Scheduled backup completed: {result['$id']}")
    except Exception as e:
        print(f"✗ Scheduled backup failed: {e}")

# Schedule daily backup at 2 AM
scheduler.add_job(
    func=scheduled_backup_job,
    trigger="cron",
    hour=2,
    minute=0,
    args=["db_config_123", "user_456"],
    id="daily_backup_db_123",
)

scheduler.start()
"""

# ════════════════════════════════════════════════════════════════════════════
# COMPARISON: FIRST BACKUP vs SUBSEQUENT BACKUPS
# ════════════════════════════════════════════════════════════════════════════

"""
Same API endpoint - Different behavior:

FIRST REQUEST (Automatic FULL Backup):
POST /databases/db_123/backup
↓
- Metadata file doesn't exist
- System detects: FULL backup needed
- Fetches ALL records (1000)
- Size: 50 MB → 5 MB (compressed)
- Time: 5 seconds
- Creates: backup_meta.json with last_backup_time

SECOND REQUEST (Automatic INCREMENTAL Backup):
POST /databases/db_123/backup
↓
- Metadata file exists
- System detects: INCREMENTAL backup needed
- Reads last_backup_time from metadata
- Fetches changes since last_backup_time (50 records)
- Size: 1 MB → 0.1 MB (compressed)
- Time: 0.5 seconds
- Updates: backup_meta.json with new last_backup_time

THIRD REQUEST (Another INCREMENTAL):
POST /databases/db_123/backup
↓
- Metadata file exists
- System detects: INCREMENTAL backup needed
- Reads last_backup_time (from second backup)
- Fetches changes since last_backup_time (30 records)
- Size: 0.8 MB → 0.08 MB (compressed)
- Time: 0.3 seconds
- Updates: backup_meta.json again

NO CHANGES REQUEST:
POST /databases/db_123/backup
↓
- Metadata file exists
- System detects: INCREMENTAL backup needed
- Reads last_backup_time
- Fetches changes: ZERO changes detected
- System skips upload (optimization!)
- Time: <0.1 seconds
- Returns: "No changes to backup"
"""

# ════════════════════════════════════════════════════════════════════════════
# STEP-BY-STEP: HOW TO TRIGGER A BACKUP
# ════════════════════════════════════════════════════════════════════════════

"""
STEP 1: Get JWT Token
━━━━━━━━━━━━━━━━━━━━

curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'

Response:
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}

Copy the access_token.


STEP 2: Get Database Configuration ID
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

List your saved databases:

curl -X GET http://localhost:8000/databases \
  -H "Authorization: Bearer YOUR_TOKEN"

Response:
{
  "databases": [
    {
      "$id": "db_config_123",
      "database_type": "mysql",
      "host": "localhost",
      "database_name": "my_database",
      ...
    }
  ]
}

Copy the $id (e.g., db_config_123).


STEP 3: Request Backup (FIRST TIME - FULL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

curl -X POST http://localhost:8000/databases/db_config_123/backup \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json"

Response:
{
  "backup_id": "file_abc123",
  "success": true,
  "message": "Backup completed.",
  "file_name": "backup_2026_04_01_full.gz.enc",
  "file_size": 5234,
  "compression": "gzip",
  "status": "success"
}

✓ First backup (FULL) complete!


STEP 4: Request Backup (SECOND TIME - INCREMENTAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Make same request:

curl -X POST http://localhost:8000/databases/db_config_123/backup \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json"

Response:
{
  "backup_id": "file_def456",
  "success": true,
  "message": "Backup completed.",
  "file_name": "backup_2026_04_01_incremental.gz.enc",
  "file_size": 234,
  "compression": "gzip",
  "status": "success"
}

✓ Second backup (INCREMENTAL) complete!
Notice: Much smaller file (234 bytes vs 5234 bytes)!
"""

# ════════════════════════════════════════════════════════════════════════════
# EXAMPLE: PYTHON SCRIPT TO REQUEST BACKUP
# ════════════════════════════════════════════════════════════════════════════

"""
Save as: request_backup.py

Run: python request_backup.py
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"
EMAIL = "user@example.com"
PASSWORD = "password123"
DB_CONFIG_ID = "db_config_123"

def request_backup():
    # Step 1: Login and get token
    print("Step 1: Logging in...")
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": EMAIL, "password": PASSWORD}
    )
    token = login_response.json()["access_token"]
    print(f"✓ Got token: {token[:20]}...")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Step 2: Request backup
    print("\nStep 2: Requesting backup...")
    backup_response = requests.post(
        f"{BASE_URL}/databases/{DB_CONFIG_ID}/backup",
        headers=headers
    )
    
    if backup_response.status_code == 200:
        backup = backup_response.json()
        print(f"✓ Backup successful!")
        print(f"  Backup ID: {backup['backup_id']}")
        print(f"  Type: {backup.get('file_name', 'unknown').split('_')[-1].split('.')[0]}")
        print(f"  Size: {backup['file_size']} bytes")
        print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return backup
    else:
        print(f"✗ Backup failed: {backup_response.text}")
        return None

if __name__ == "__main__":
    request_backup()

# Output:
# Step 1: Logging in...
# ✓ Got token: eyJhbGciOiJIUzI1NiIsInR5cCI6...
#
# Step 2: Requesting backup...
# ✓ Backup successful!
#   Backup ID: file_abc123
#   Type: full
#   Size: 5234 bytes
#   Time: 2026-04-01 13:00:00
"""

# ════════════════════════════════════════════════════════════════════════════
# EXAMPLE: BASH SCRIPT TO REQUEST BACKUP
# ════════════════════════════════════════════════════════════════════════════

"""
Save as: request_backup.sh

Run: chmod +x request_backup.sh && ./request_backup.sh
"""

#!/bin/bash

BASE_URL="http://localhost:8000"
EMAIL="user@example.com"
PASSWORD="password123"
DB_CONFIG_ID="db_config_123"

# Step 1: Login
echo "Step 1: Logging in..."
TOKEN=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}" \
  | jq -r '.access_token')

echo "✓ Got token"

# Step 2: Request backup
echo ""
echo "Step 2: Requesting backup..."
curl -X POST "$BASE_URL/databases/$DB_CONFIG_ID/backup" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  | jq '.'

# Output:
# {
#   "backup_id": "file_abc123",
#   "success": true,
#   "message": "Backup completed.",
#   "file_name": "backup_2026_04_01_full.gz.enc",
#   "file_size": 5234,
#   ...
# }
"""

# ════════════════════════════════════════════════════════════════════════════
# CHECK BACKUP STATUS & HISTORY
# ════════════════════════════════════════════════════════════════════════════

"""
GET BACKUP HISTORY:

curl -X GET http://localhost:8000/databases/db_config_123/backups \
  -H "Authorization: Bearer YOUR_TOKEN" \
  | jq '.'

Response:
[
  {
    "$id": "file_def456",
    "backup_type": "incremental",
    "file_name": "backup_2026_04_01_incremental.gz.enc",
    "file_size": 234,
    "created_at": "2026-04-01T14:00:00Z"
  },
  {
    "$id": "file_abc123",
    "backup_type": "full",
    "file_name": "backup_2026_04_01_full.gz.enc",
    "file_size": 5234,
    "created_at": "2026-04-01T13:00:00Z"
  }
]


CHECK NEXT BACKUP TYPE:

curl -X GET http://localhost:8000/api/backups/type/db_config_123 \
  -H "Authorization: Bearer YOUR_TOKEN" \
  | jq '.'

Response:
{
  "db_config_id": "db_config_123",
  "backup_type": "incremental",
  "next_backup_is": "incremental",
  "last_backup_time": "2026-04-01T14:00:00Z"
}
"""

# ════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════════

"""
TO REQUEST AN INCREMENTAL BACKUP:

✅ SIMPLEST:
   POST /databases/{db_config_id}/backup
   (Automatically handles full/incremental)

✅ FIRST REQUEST:
   → Full backup created
   → All records backed up
   → Metadata file created

✅ SUBSEQUENT REQUESTS:
   → Incremental backup created
   → Only changes backed up
   → Much faster & smaller

✅ NO CHANGES:
   → Upload skipped (optimization)
   → Logged as "no changes"

✅ SAME ENDPOINT FOR EVERYTHING:
   → No need to specify backup type
   → System auto-detects
   → Handles all scenarios

JUST CALL THE SAME ENDPOINT MULTIPLE TIMES!
First time → FULL
Second time → INCREMENTAL
Third time → INCREMENTAL
...and so on
"""

