"""Auth routes: login, current user, change password."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from webui.api.auth import create_access_token, is_authless_mode, verify_password
from webui.api.deps import get_current_user, get_user_store
from webui.api.models import (
    AuthBootstrapResponse,
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    UserInfo,
)
from webui.api.users import UserStore

router = APIRouter()


@router.get("/bootstrap", response_model=AuthBootstrapResponse)
async def bootstrap() -> AuthBootstrapResponse:
    from webui.api.auth import get_authless_user, is_authless_mode

    # 始终返回 auth_disabled=True，跳过登录页
    # if not is_authless_mode():
    #     return AuthBootstrapResponse(auth_disabled=False, user=None)

    user = get_authless_user()
    return AuthBootstrapResponse(
        auth_disabled=True,
        user=UserInfo(
            id=user["id"],
            username=user["username"],
            role=user["role"],
            created_at=user["created_at"],
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    user_store: Annotated[UserStore, Depends(get_user_store)],
) -> TokenResponse:
    user = user_store.get_by_username(body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    token = create_access_token(user["id"], user["username"], user["role"])
    return TokenResponse(
        access_token=token,
        user=UserInfo(
            id=user["id"],
            username=user["username"],
            role=user["role"],
            created_at=user["created_at"],
        ),
    )


@router.get("/me", response_model=UserInfo)
async def me(current_user: Annotated[dict, Depends(get_current_user)]) -> UserInfo:
    return UserInfo(
        id=current_user["id"],
        username=current_user["username"],
        role=current_user["role"],
        created_at=current_user["created_at"],
    )


@router.put("/password", status_code=204, response_model=None, response_class=Response)
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    user_store: Annotated[UserStore, Depends(get_user_store)],
) -> None:
    if is_authless_mode():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Password changes are disabled while WEBUI_AUTH_DISABLED is enabled",
        )
    user_store.update_password(current_user["id"], body.new_password)
