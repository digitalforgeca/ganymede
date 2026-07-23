import json
import base64
import hmac
import hashlib
import time
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi_sso.sso.google import GoogleSSO
from starlette.requests import Request, HTTPConnection
from starlette.exceptions import HTTPException
from ganymede.config import AppConfig

router = APIRouter(prefix="/auth")

def sign_cookie(email: str, secret: str) -> str:
    payload = json.dumps({"email": email, "exp": int(time.time()) + 86400 * 7}) # 7 days
    b64_payload = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), b64_payload.encode(), hashlib.sha256).digest()
    b64_sig = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{b64_payload}.{b64_sig}"

def verify_cookie(cookie: str, secret: str) -> str | None:
    try:
        parts = cookie.split(".")
        if len(parts) != 2:
            return None
        b64_payload, b64_sig = parts
        sig = base64.urlsafe_b64decode(b64_sig + "==")
        expected_sig = hmac.new(secret.encode(), b64_payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        
        payload = json.loads(base64.urlsafe_b64decode(b64_payload + "==").decode())
        if payload.get("exp", 0) < time.time():
            return None
            
        return payload.get("email")
    except Exception:
        return None

def get_google_sso(request: Request) -> GoogleSSO | None:
    config: AppConfig = request.app.state.server.config
    if not config.auth.enabled:
        return None
        
    return GoogleSSO(
        client_id=config.auth.google_client_id,
        client_secret=config.auth.google_client_secret,
        redirect_uri="http://localhost:8180/auth/callback",
        allow_insecure_http=True
    )

@router.get("/login")
async def login(request: Request):
    sso = get_google_sso(request)
    if not sso:
        return JSONResponse({"error": "Auth is disabled"}, status_code=400)
    
    with sso:
        return await sso.get_login_redirect()

@router.get("/callback")
async def callback(request: Request):
    config: AppConfig = request.app.state.server.config
    sso = get_google_sso(request)
    if not sso:
        return JSONResponse({"error": "Auth is disabled"}, status_code=400)
        
    try:
        with sso:
            user = await sso.verify_and_process(request)
    except Exception as e:
        return JSONResponse({"error": f"Failed to authenticate: {str(e)}"}, status_code=400)
        
    if not user or not user.email:
        return JSONResponse({"error": "No email provided by Google"}, status_code=400)
        
    allowed = config.auth.allowed_emails
    if allowed and user.email not in allowed:
        return JSONResponse({"error": f"Unauthorized. Email {user.email} is not whitelisted."}, status_code=403)
        
    secret = config.auth.google_client_secret or "fallback_secret"
    cookie_value = sign_cookie(user.email, secret)
    
    response = RedirectResponse(url="/")
    response.set_cookie(
        key="ganymede_session", 
        value=cookie_value, 
        httponly=True, 
        secure=False,
        samesite="lax",
        max_age=86400 * 7
    )
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("ganymede_session")
    return response

@router.get("/me")
async def get_me(request: Request):
    config: AppConfig = request.app.state.server.config
    if not config.auth.enabled:
        return JSONResponse({"email": "anonymous (auth disabled)"})
        
    cookie = request.cookies.get("ganymede_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    secret = config.auth.google_client_secret or "fallback_secret"
    email = verify_cookie(cookie, secret)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid session")
        
    return JSONResponse({"email": email})

def require_auth(conn: HTTPConnection):
    """Dependency to inject into other routers to require auth"""
    config: AppConfig = conn.app.state.server.config
    if not config.auth.enabled:
        return "anonymous"
        
    cookie = conn.cookies.get("ganymede_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    secret = config.auth.google_client_secret or "fallback_secret"
    email = verify_cookie(cookie, secret)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid session")
        
    return email
