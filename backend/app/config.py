from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 기반 애플리케이션 설정.

    자격 증명(AWS 키, DB 비밀번호)은 코드에 하드코딩하지 않고
    로컬 `.env` 또는 EC2 IAM Role/환경변수를 통해 주입합니다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""
    aws_region: str = "us-east-1"
    aws_profile: str | None = None

    bedrock_fast_model_id: str = "amazon.nova-lite-v1:0"
    bedrock_smart_model_id: str = "amazon.nova-pro-v1:0"
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dim: int = 1024


settings = Settings()
