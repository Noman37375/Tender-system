from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.errors import ApiError
from app.repositories.users import UserRepository
from app.schemas.api import (
    AccessTokenResponse,
    AuthResponse,
    LoginRequest,
    MeResponse,
    OrganisationOut,
    RefreshRequest,
    RegisterRequest,
    UserOut,
)
from app.services.auth_service import AuthService, IssuedTokens

router = APIRouter(tags=["auth"])


def _auth_response(tokens: IssuedTokens) -> AuthResponse:
    return AuthResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        user=UserOut.model_validate(tokens.user),
    )


@router.post("/auth/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, session: SessionDep) -> AuthResponse:
    tokens = await AuthService(session).register(
        body.org_name, body.name, body.email, body.password
    )
    return _auth_response(tokens)


@router.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest, session: SessionDep) -> AuthResponse:
    return _auth_response(await AuthService(session).login(body.email, body.password))


@router.post("/auth/refresh", response_model=AccessTokenResponse)
async def refresh(body: RefreshRequest, session: SessionDep) -> AccessTokenResponse:
    return AccessTokenResponse(access_token=await AuthService(session).refresh(body.refresh_token))


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, session: SessionDep) -> MeResponse:
    org = await UserRepository(session).get_organisation(user.organisation_id)
    if org is None:  # FK makes this unreachable; guard keeps types honest
        raise ApiError(404, "NOT_FOUND", "Organisation not found")
    return MeResponse(
        user=UserOut.model_validate(user), organisation=OrganisationOut.model_validate(org)
    )
