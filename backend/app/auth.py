"""Supabase Auth JWT verification. Asymmetric keys via JWKS; HS256 only if a legacy secret is set."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class User:
    id: UUID
    email: str | None


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{get_settings().supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
                           cache_keys=True, lifespan=600)


def verify_token(token: str) -> User:
    s = get_settings()
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256":
            if s.supabase_jwt_secret is None:
                raise jwt.InvalidTokenError("HS256 tokens are not accepted")
            key = s.supabase_jwt_secret.get_secret_value()
        else:
            key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["ES256", "RS256", "HS256"], audience="authenticated")
        return User(id=UUID(claims["sub"]), email=claims.get("email"))
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e


def current_user(cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    return verify_token(cred.credentials)


CurrentUser = Annotated[User, Depends(current_user)]
