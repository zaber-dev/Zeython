"""SAML 2.0 SSO login: "Sign in with Okta/Azure AD/ADFS/your enterprise
IdP", for the identity providers (and enterprise customers) that
specifically require SAML rather than OAuth2/OIDC.

Built on `python3-saml <https://github.com/SAML-Toolkits/python3-saml>`_
(``pip install zeython[saml]``), which does the part worth not
reimplementing: building the AuthnRequest, and parsing + validating the
IdP's signed Response (XML signature verification, replay/expiry/audience/
recipient checks). Zeython wraps it in an async, container-bound
:class:`SamlManager` with the same "hands you a normalized identity, not
an opinion about your ``User`` model" shape as :mod:`zeython.oauth`, so
both flows can sit side by side in one app and share the same
find-or-create-a-user callback.

Service-provider-initiated flow: your app redirects the user to the IdP
(:meth:`SamlManager.login_url`), and the IdP posts a signed assertion back
to your Assertion Consumer Service (ACS) URL
(:meth:`SamlManager.handle_acs`). An IdP-initiated login (the IdP sends an
unsolicited assertion -- common from an admin console's "test connection"
button) lands at the same ACS endpoint and validates the same way, since
python3-saml doesn't require a matching ``InResponseTo`` when none was
ever sent.

There's no universal attribute-naming standard the way OIDC's userinfo
claims are -- an IdP's admin configures which attribute names it sends,
often a URN (``http://schemas.xmlsoap.org/ws/2005/05/identity/claims/
emailaddress``) or a short name (``email``), and it varies by IdP and by
how that IdP's admin set it up. :class:`SamlUser` recognizes a handful of
common ones for ``email``/``name`` automatically; set
``email_attribute=``/``name_attribute=`` on :class:`SamlProvider` when
yours isn't one of them, and use :meth:`SamlUser.attribute` for anything
else your app needs from the assertion.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from zeython.cache import Cache, InMemoryCache
from zeython.exceptions import BadRequestException, ForbiddenException, NotFoundException
from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from zeython.application import Application

DEFAULT_REPLAY_WINDOW = 300.0  # 5 minutes -- comfortably covers a typical assertion's NotOnOrAfter.

_EMAIL_ATTRIBUTE_CANDIDATES = (
    "email",
    "emailAddress",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "urn:oid:0.9.2342.19200300.100.1.3",
)
_NAME_ATTRIBUTE_CANDIDATES = (
    "name",
    "displayName",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    "urn:oid:2.16.840.1.113730.3.1.241",
)


def _first_present(attributes: dict[str, list[str]], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        values = attributes.get(candidate)
        if values:
            return values[0]
    return None


@dataclass(frozen=True)
class SamlUser:
    """The identity :meth:`SamlManager.handle_acs` hands back.

    ``attributes`` is exactly what the IdP's assertion included, keyed
    however the IdP named them -- see the module docstring on why there's
    no universal naming standard here. Use :meth:`attribute` for anything
    beyond ``email``/``name``.
    """

    name_id: str
    email: str | None
    name: str | None
    attributes: dict[str, list[str]] = field(default_factory=dict)
    session_index: str | None = None

    def attribute(self, name: str) -> str | None:
        """The first value of attribute ``name``, or ``None`` if the
        assertion didn't include it."""
        values = self.attributes.get(name)
        return values[0] if values else None


@dataclass(frozen=True)
class SamlProvider:
    """One configured IdP connection -- built by :func:`saml_provider`
    rather than constructed directly in ordinary use. ``acs_url`` (your
    app's Assertion Consumer Service) must exactly match what's registered
    at the IdP.
    """

    name: str
    idp_entity_id: str
    idp_sso_url: str
    idp_x509_cert: str
    sp_entity_id: str
    acs_url: str
    sp_x509_cert: str | None = None
    sp_private_key: str | None = None
    email_attribute: str | None = None
    name_attribute: str | None = None

    def to_settings(self) -> dict[str, Any]:
        """The ``dict`` shape ``python3-saml``'s ``OneLogin_Saml2_Settings`` expects."""
        return {
            "strict": True,
            "sp": {
                "entityId": self.sp_entity_id,
                "assertionConsumerService": {
                    "url": self.acs_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
                "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
                "x509cert": self.sp_x509_cert or "",
                "privateKey": self.sp_private_key or "",
            },
            "idp": {
                "entityId": self.idp_entity_id,
                "singleSignOnService": {
                    "url": self.idp_sso_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "x509cert": self.idp_x509_cert,
            },
            "security": {
                "authnRequestsSigned": bool(self.sp_private_key and self.sp_x509_cert),
            },
        }


def saml_provider(
    *,
    name: str,
    idp_entity_id: str,
    idp_sso_url: str,
    idp_x509_cert: str,
    sp_entity_id: str,
    acs_url: str,
    sp_x509_cert: str | None = None,
    sp_private_key: str | None = None,
    email_attribute: str | None = None,
    name_attribute: str | None = None,
) -> SamlProvider:
    """Configure one IdP connection -- everything here comes from your
    IdP admin's console (entity ID, SSO URL, signing certificate) plus the
    ACS URL you register there in return. ``sp_x509_cert``/``sp_private_key``
    are optional -- set both to have Zeython sign outgoing AuthnRequests
    (some IdPs require it); without them, the request goes unsigned, which
    most IdPs accept for SP-initiated login since the security-critical
    direction is the IdP's signed *response*, always required.
    """
    return SamlProvider(
        name=name,
        idp_entity_id=idp_entity_id,
        idp_sso_url=idp_sso_url,
        idp_x509_cert=idp_x509_cert,
        sp_entity_id=sp_entity_id,
        acs_url=acs_url,
        sp_x509_cert=sp_x509_cert,
        sp_private_key=sp_private_key,
        email_attribute=email_attribute,
        name_attribute=name_attribute,
    )


def _request_data(request: Request, *, post_data: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.url.hostname or "",
        "server_port": request.url.port,
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": post_data or {},
    }


def _import_onelogin() -> Any:
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
    except ImportError as exc:
        raise ImportError(
            "zeython.saml requires python3-saml -- install it with `pip install zeython[saml]`."
        ) from exc
    return OneLogin_Saml2_Auth


class SamlManager:
    """Builds the login redirect, validates the ACS callback, and generates
    SP metadata for every provider registered with it. Bound in the
    container by :class:`SamlServiceProvider`.

    Tracks every assertion ID it accepts in ``replay_cache`` (a fresh
    :class:`~zeython.cache.InMemoryCache` by default) for ``replay_window``
    seconds, and rejects a second callback presenting the same ID --
    without this, a signed SAMLResponse a network observer captures (or an
    IdP-side bug/misconfiguration that redelivers one) stays valid and
    replayable for its entire signature-validity window, letting an
    attacker complete the same login again by simply resending the
    original request. Signature validation alone doesn't catch this: a
    replayed response is, cryptographically, exactly as valid the second
    time as the first.
    """

    def __init__(
        self,
        providers: dict[str, SamlProvider],
        *,
        replay_cache: Cache | None = None,
        replay_window: float = DEFAULT_REPLAY_WINDOW,
    ) -> None:
        self.providers = providers
        self.replay_cache = replay_cache if replay_cache is not None else InMemoryCache()
        self.replay_window = replay_window
        self._replay_locks: dict[str, asyncio.Lock] = {}

    def _provider(self, name: str) -> SamlProvider:
        provider = self.providers.get(name)
        if provider is None:
            raise NotFoundException(f"Unknown SAML provider: {name!r}.")
        return provider

    def _auth(self, request: Request, provider_name: str, *, post_data: dict[str, str] | None = None) -> Any:
        auth_class = _import_onelogin()
        provider = self._provider(provider_name)
        return auth_class(_request_data(request, post_data=post_data), provider.to_settings())

    def login_url(self, request: Request, provider_name: str) -> str:
        """The URL to send the browser to at ``provider_name``'s IdP."""
        return self._auth(request, provider_name).login()

    async def handle_acs(self, request: Request, provider_name: str) -> SamlUser:
        """Validate the IdP's POSTed assertion and return the identity it
        asserts. Raises :class:`~zeython.exceptions.BadRequestException`
        if the callback carried no ``SAMLResponse``, and
        :class:`~zeython.exceptions.ForbiddenException` if the response
        failed validation (bad/missing signature, expired, wrong
        audience/recipient, already used once before, ...).
        """
        form = await request.form()
        saml_response = form.get("SAMLResponse")
        if not isinstance(saml_response, str):
            raise BadRequestException("The IdP's callback did not include a SAMLResponse.")

        auth = self._auth(request, provider_name, post_data={"SAMLResponse": saml_response})
        auth.process_response()
        errors = auth.get_errors()
        if errors:
            raise ForbiddenException(
                f"SAML response validation failed ({', '.join(errors)}): {auth.get_last_error_reason()}"
            )
        if not auth.is_authenticated():
            raise ForbiddenException("SAML authentication was not successful.")

        assertion_id = auth.get_last_assertion_id()
        replay_key = f"saml:seen-assertion:{assertion_id}"
        # Locked (not just checked) so two requests racing to replay the
        # very same assertion can't both pass the has()-then-put() check
        # before either has written its own entry.
        lock = self._replay_locks.setdefault(replay_key, asyncio.Lock())
        try:
            async with lock:
                if await self.replay_cache.has(replay_key):
                    raise ForbiddenException("This SAML assertion has already been used.")
                await self.replay_cache.put(replay_key, True, ttl=self.replay_window)
        finally:
            self._replay_locks.pop(replay_key, None)

        provider = self._provider(provider_name)
        attributes: dict[str, list[str]] = auth.get_attributes()
        email = (
            attributes.get(provider.email_attribute, [None])[0]
            if provider.email_attribute
            else _first_present(attributes, _EMAIL_ATTRIBUTE_CANDIDATES)
        )
        name = (
            attributes.get(provider.name_attribute, [None])[0]
            if provider.name_attribute
            else _first_present(attributes, _NAME_ATTRIBUTE_CANDIDATES)
        )

        return SamlUser(
            name_id=auth.get_nameid(),
            email=email,
            name=name,
            attributes=attributes,
            session_index=auth.get_session_index(),
        )

    def metadata_xml(self, provider_name: str) -> str:
        """The SP metadata XML to hand your IdP admin when they ask for it,
        instead of entering entity ID/ACS URL/certificate by hand.

        Raises :class:`RuntimeError` if the generated metadata is invalid
        (a configuration error in the :class:`SamlProvider` -- this is a
        setup-time check, not something a real request can trigger).
        """
        from onelogin.saml2.settings import OneLogin_Saml2_Settings

        provider = self._provider(provider_name)
        settings = OneLogin_Saml2_Settings(provider.to_settings(), sp_validation_only=True)
        metadata = settings.get_sp_metadata()
        errors = settings.validate_metadata(metadata)
        if errors:
            raise RuntimeError(f"Invalid SAML SP metadata for provider {provider_name!r}: {', '.join(errors)}")
        return metadata  # type: ignore[no-any-return]


def saml_login(request: Request, provider: str) -> RedirectResponse:
    """Send the browser to ``provider``'s IdP login page -- call this from
    your ``GET /saml/{provider}/login`` route::

        async def saml_login(self, request):
            return saml_login(request, request.path_params["provider"])
    """
    manager: SamlManager = request.app.state.container.make(SamlManager)
    return RedirectResponse(manager.login_url(request, provider))


async def saml_acs(request: Request, provider: str) -> SamlUser:
    """Complete the login for ``provider`` and return the resulting
    identity -- call this from your ``POST /saml/{provider}/acs`` route
    (the Assertion Consumer Service URL registered at the IdP), then
    find-or-create your own ``User`` from it and call
    :func:`zeython.auth.login`::

        async def saml_acs(self, request):
            identity = await saml_acs(request, request.path_params["provider"])
            user = await User.first_where(email=identity.email)
            if user is None:
                user = await User.create(email=identity.email, name=identity.name)
            login(request, user)
            return RedirectResponse("/", status_code=303)
    """
    manager: SamlManager = request.app.state.container.make(SamlManager)
    return await manager.handle_acs(request, provider)


async def saml_metadata(request: Request, provider: str) -> Response:
    """Serve ``provider``'s SP metadata XML -- call this from a
    ``GET /saml/{provider}/metadata`` route and hand your IdP admin the
    URL, instead of entering entity ID/ACS URL/certificate by hand::

        async def saml_metadata(self, request):
            return await saml_metadata(request, request.path_params["provider"])
    """
    manager: SamlManager = request.app.state.container.make(SamlManager)
    return Response(manager.metadata_xml(provider), media_type="application/samlmetadata+xml")


class SamlServiceProvider(ServiceProvider):
    """Binds a :class:`SamlManager` configured with the given providers::

        app.register(SamlServiceProvider(app, providers=[
            saml_provider(
                name="okta",
                idp_entity_id="http://www.okta.com/exk...",
                idp_sso_url="https://your-org.okta.com/app/.../sso/saml",
                idp_x509_cert="-----BEGIN CERTIFICATE-----...",
                sp_entity_id="https://app.example.com/saml/okta/metadata",
                acs_url="https://app.example.com/saml/okta/acs",
            ),
        ]))

    Needs ``AuthServiceProvider`` registered too (for
    :func:`zeython.auth.login` your ACS route calls) -- registration order
    between the two doesn't matter. See docs/saml.md.

    Pass ``replay_cache`` (a :class:`~zeython.cache.RedisCache`) to share
    the used-assertion tracking across every process/machine instead of
    each one only remembering what it itself has seen -- see
    :class:`SamlManager` for why this tracking exists at all.
    """

    def __init__(
        self,
        app: Application,
        *,
        providers: list[SamlProvider],
        replay_cache: Cache | None = None,
        replay_window: float = DEFAULT_REPLAY_WINDOW,
    ) -> None:
        super().__init__(app)
        self.providers = providers
        self.replay_cache = replay_cache
        self.replay_window = replay_window

    def register(self) -> None:
        manager = SamlManager(
            {provider.name: provider for provider in self.providers},
            replay_cache=self.replay_cache,
            replay_window=self.replay_window,
        )
        self.container.singleton(SamlManager, lambda: manager)


__all__ = [
    "SamlManager",
    "SamlProvider",
    "SamlServiceProvider",
    "SamlUser",
    "saml_acs",
    "saml_login",
    "saml_metadata",
    "saml_provider",
]
