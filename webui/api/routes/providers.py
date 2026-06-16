"""Providers routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from webui.api.deps import get_services, require_admin
from webui.api.gateway import ServiceContainer
from webui.api.models import ProviderInfo, UpdateProviderRequest, CreateProviderRequest
# [AI:START] tool=copilot date=2026-03-12 author=chenweikang
from webui.api import provider_meta
# [AI:END]
from webui.utils import webui_config

router = APIRouter()

# Derive provider names directly from the ProvidersConfig schema so
# new providers added upstream are automatically included.
_builtin_provider_names_cache: set[str] | None = None


def _builtin_names() -> set[str]:
    global _builtin_provider_names_cache
    if _builtin_provider_names_cache is None:
        _builtin_provider_names_cache = set(_get_builtin_provider_names())
    return _builtin_provider_names_cache


def _get_builtin_provider_names() -> list[str]:
    """Return all field names from ProvidersConfig that map to a ProviderConfig."""
    from nanobot.config.schema import ProvidersConfig, ProviderConfig
    import pydantic

    return [
        name
        for name, field_info in ProvidersConfig.model_fields.items()
        if field_info.annotation is ProviderConfig
        or (
            hasattr(field_info.annotation, "__origin__") is False
            and isinstance(field_info.default_factory, type)  # type: ignore[arg-type]
        )
        # Check that the field type resolves to ProviderConfig
        or _is_provider_config_field(field_info)
    ]


def _is_provider_config_field(field_info) -> bool:
    """Return True if the field's default_factory produces a ProviderConfig."""
    from nanobot.config.schema import ProviderConfig
    factory = field_info.default_factory
    if factory is None:
        return False
    try:
        return isinstance(factory(), ProviderConfig)
    except Exception:
        return False


def _mask(value: str) -> str:
    if not value:
        return ""
    return f"••••{value[-4:]}" if len(value) > 4 else "••••"


@router.get("", response_model=list[ProviderInfo])
async def list_providers(
    _admin: Annotated[dict, Depends(require_admin)],
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[ProviderInfo]:
    result = []
    
    # 1. Built-in providers from nanobot core (registry-driven)
    for name in _get_builtin_provider_names():
        p = getattr(svc.config.providers, name, None)
        if p is None:
            continue
        result.append(
            ProviderInfo(
                name=name,
                api_key_masked=_mask(p.api_key),
                api_base=p.api_base,
                extra_headers=p.extra_headers,
                has_key=bool(p.api_key),
                models=provider_meta.get_provider_models(name),
                is_custom=False,
            )
        )
        
    # 2. Custom providers from webui_config
    custom_providers = webui_config.get_custom_providers()
    for name, p_data in custom_providers.items():
        api_key = p_data.get("api_key", "")
        result.append(
            ProviderInfo(
                name=name,
                api_key_masked=_mask(api_key),
                api_base=p_data.get("api_base"),
                extra_headers=p_data.get("extra_headers"),
                has_key=bool(api_key),
                models=provider_meta.get_provider_models(name),
                is_custom=True,
            )
        )
        
    return result


@router.post("", response_model=ProviderInfo)
async def create_custom_provider(
    body: CreateProviderRequest,
    _admin: Annotated[dict, Depends(require_admin)],
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> ProviderInfo:
    if body.name in _builtin_names():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Provider '{body.name}' is a built-in provider name")
        
    custom_providers = webui_config.get_custom_providers()
    if body.name in custom_providers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Provider '{body.name}' already exists")
        
    p_data = {
        "api_key": body.api_key or "",
        "api_base": body.api_base or "",
        "extra_headers": body.extra_headers,
    }
    webui_config.set_custom_provider(body.name, p_data)
    
    if body.models is not None:
        provider_meta.set_provider_models(body.name, body.models)
        
    svc.reload_provider()
    
    return ProviderInfo(
        name=body.name,
        api_key_masked=_mask(p_data["api_key"]),
        api_base=p_data["api_base"],
        extra_headers=p_data["extra_headers"],
        has_key=bool(p_data["api_key"]),
        models=provider_meta.get_provider_models(body.name),
        is_custom=True,
    )


@router.patch("/{name}", response_model=ProviderInfo)
async def update_provider(
    name: str,
    body: UpdateProviderRequest,
    _admin: Annotated[dict, Depends(require_admin)],
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> ProviderInfo:
    from nanobot.config.loader import save_config

    is_custom = False
    
    if name in _builtin_names():
        p = getattr(svc.config.providers, name, None)
        if p is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Provider '{name}' not found")
            
        if body.api_key is not None:
            p.api_key = body.api_key
        if body.api_base is not None:
            p.api_base = body.api_base or None
        if "extra_headers" in body.model_fields_set:
            p.extra_headers = body.extra_headers or None
            
        save_config(svc.config)
        api_key_masked = _mask(p.api_key)
        api_base = p.api_base
        extra_headers = p.extra_headers
        has_key = bool(p.api_key)
    else:
        custom_providers = webui_config.get_custom_providers()
        if name not in custom_providers:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Provider '{name}' not found")
            
        p_data = custom_providers[name]
        if body.api_key is not None:
            p_data["api_key"] = body.api_key
        if body.api_base is not None:
            p_data["api_base"] = body.api_base or ""
        if "extra_headers" in body.model_fields_set:
            p_data["extra_headers"] = body.extra_headers or None
            
        webui_config.set_custom_provider(name, p_data)
        
        api_key_masked = _mask(p_data.get("api_key", ""))
        api_base = p_data.get("api_base")
        extra_headers = p_data.get("extra_headers")
        has_key = bool(p_data.get("api_key"))
        is_custom = True

    # [AI:START] tool=copilot date=2026-03-12 author=chenweikang
    if body.models is not None:
        provider_meta.set_provider_models(name, body.models)
    # [AI:END]

    svc.reload_provider()
    return ProviderInfo(
        name=name,
        api_key_masked=api_key_masked,
        api_base=api_base,
        extra_headers=extra_headers,
        has_key=has_key,
        models=provider_meta.get_provider_models(name),
        is_custom=is_custom,
    )


@router.delete("/{name}")
async def delete_custom_provider(
    name: str,
    _admin: Annotated[dict, Depends(require_admin)],
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> dict:
    if name in _builtin_names():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Cannot delete built-in provider '{name}'")
        
    if not webui_config.delete_custom_provider(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Custom provider '{name}' not found")
        
    # Also clean up models meta
    provider_meta.set_provider_models(name, [])
    
    # If the active agent was using this provider, we might need to clear it or fallback to auto
    # (Here we just reload, nanobot will fallback or error gracefully on next chat)
    svc.reload_provider()
    
    return {"status": "success"}


def _get_model_name(svc: ServiceContainer) -> str:
    """Return the configured model name (stripped of provider prefix)."""
    model = getattr(svc.config.agents.defaults, "model", "") or ""
    # Strip provider prefix like "dashscope/qwen3.5-flash" → "qwen3.5-flash"
    if "/" in model:
        model = model.split("/", 1)[1]
    return model or "qwen3.5-flash"


@router.get("/comtrade-config")
async def get_comtrade_config(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> dict:
    """Return provider config for comtrade-web embedded app (no auth required)."""
    # comtrade-web uses OpenAI-compatible /chat/completions endpoint.
    # Map provider names and URL patterns to OpenAI-compatible base URLs.
    _openai_compatible_urls = {
        "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    }
    _url_pattern_map = {
        "dashscope.aliyuncs.com": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "open.bigmodel.cn": "https://open.bigmodel.cn/api/paas/v4",
        "api.deepseek.com": "https://api.deepseek.com/v1",
        "api.openai.com": "https://api.openai.com/v1",
    }
    # Find first provider with an API key
    for name in _get_builtin_provider_names():
        p = getattr(svc.config.providers, name, None)
        if p and p.api_key:
            # Try known provider name first, then URL pattern matching
            base_url = _openai_compatible_urls.get(name, "")
            if not base_url and p.api_base:
                for pattern, url in _url_pattern_map.items():
                    if pattern in p.api_base:
                        base_url = url
                        break
            if not base_url:
                base_url = p.api_base or ""
            return {
                "api_key": p.api_key,
                "base_url": base_url,
                "model": _get_model_name(svc),
            }
    # Check custom providers
    custom_providers = webui_config.get_custom_providers()
    for name, p_data in custom_providers.items():
        api_key = p_data.get("api_key", "")
        if api_key:
            return {
                "api_key": api_key,
                "base_url": p_data.get("api_base", ""),
                "model": _get_model_name(svc),
            }
    return {"api_key": "", "base_url": "", "model": ""}
