from pydantic import BaseModel


class AdminDatabaseRecord(BaseModel):
    document_id: str
    user_id: str
    database_type: str
    host: str
    port: int
    database_name: str
    username: str
    status: str
    created_at: str = ""
    updated_at: str = ""


class AdminBackupRecord(BaseModel):
    backup_id: str
    db_config_id: str
    user_id: str
    database_type: str
    database_name: str
    file_name: str
    file_size: int
    status: str
    compression: str = "none"
    encryption: str = "none"
    created_at: str = ""


class AdminRestoreRecord(BaseModel):
    restore_id: str
    user_id: str
    db_config_id: str
    backup_id: str = ""
    file_name: str = ""
    source: str = ""
    status: str = ""
    message: str = ""
    created_at: str = ""

