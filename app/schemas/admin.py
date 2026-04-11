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

