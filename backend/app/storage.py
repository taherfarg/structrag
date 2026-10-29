"""Private Supabase Storage bucket, reached only with the server-side secret key."""

from supabase import AsyncClient, AsyncClientOptions, acreate_client

from .config import Settings


class Storage:
    def __init__(self, client: AsyncClient, bucket: str):
        self.bucket = client.storage.from_(bucket)

    @classmethod
    async def connect(cls, s: Settings) -> "Storage":
        client = await acreate_client(
            s.supabase_url, s.supabase_secret_key.get_secret_value(),
            AsyncClientOptions(auto_refresh_token=False, persist_session=False, storage_client_timeout=120),
        )
        return cls(client, s.storage_bucket)

    async def put(self, path: str, data: bytes, mime: str) -> None:
        await self.bucket.upload(path, data, {"content-type": mime, "upsert": "true"})

    async def get(self, path: str) -> bytes:
        return await self.bucket.download(path)

    async def delete(self, path: str) -> None:
        await self.bucket.remove([path])
