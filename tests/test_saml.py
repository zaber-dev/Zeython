"""Tests for zeython.saml -- SamlManager, SamlProvider, and SamlServiceProvider.

Builds a real self-signed IdP certificate (via the ``openssl`` CLI, always
available where this suite runs -- no new test dependency) and a real,
signed SAML Response XML to drive the actual python3-saml signature
validation path end-to-end, rather than mocking it -- signature
verification is the security-critical part of this module.
"""

import base64
import builtins
import datetime as dt
import subprocess
import uuid
from pathlib import Path

import pytest
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.cache import InMemoryCache
from zeython.config import Config
from zeython.saml import (
    SamlServiceProvider,
    SamlUser,
    saml_acs,
    saml_login,
    saml_metadata,
    saml_provider,
)
from zeython.testing import client

IDP_ENTITY_ID = "https://idp.example.com/entity"
IDP_SSO_URL = "https://idp.example.com/sso"
SP_ENTITY_ID = "https://app.example.com/saml/okta/metadata"
ACS_URL = "https://app.example.com/saml/okta/acs"


def test_saml_user_attribute_returns_the_first_value() -> None:
    user = SamlUser(name_id="ada@example.com", email=None, name=None, attributes={"role": ["admin", "editor"]})
    assert user.attribute("role") == "admin"


def test_saml_user_attribute_returns_none_when_absent() -> None:
    user = SamlUser(name_id="ada@example.com", email=None, name=None, attributes={})
    assert user.attribute("role") is None


@pytest.fixture(scope="module")
def idp_cert_and_key(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    directory = tmp_path_factory.mktemp("saml-idp")
    key_path = directory / "idp_key.pem"
    cert_path = directory / "idp_cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-subj",
            "/CN=idp.example.com",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path.read_text(), key_path.read_text()


def _saml_time(delta_seconds: float) -> str:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_signed_response(
    idp_cert: str,
    idp_key: str,
    *,
    name_id: str = "ada@example.com",
    attributes: dict[str, str] | None = None,
    not_on_or_after_delta: float = 300,
) -> bytes:
    attributes = attributes if attributes is not None else {"email": "ada@example.com", "name": "Ada Lovelace"}
    attribute_xml = "".join(
        f'<saml:Attribute Name="{key}" NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:basic">'
        f"<saml:AttributeValue>{value}</saml:AttributeValue></saml:Attribute>"
        for key, value in attributes.items()
    )
    now = _saml_time(0)
    not_before = _saml_time(-60)
    not_on_or_after = _saml_time(not_on_or_after_delta)
    response_id = "_" + uuid.uuid4().hex
    assertion_id = "_" + uuid.uuid4().hex

    xml = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{response_id}" Version="2.0" IssueInstant="{now}" Destination="{ACS_URL}">
  <saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  <saml:Assertion ID="{assertion_id}" IssueInstant="{now}" Version="2.0">
    <saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>
    <saml:Subject>
      <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{name_id}</saml:NameID>
      <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
        <saml:SubjectConfirmationData NotOnOrAfter="{not_on_or_after}" Recipient="{ACS_URL}"/>
      </saml:SubjectConfirmation>
    </saml:Subject>
    <saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}">
      <saml:AudienceRestriction><saml:Audience>{SP_ENTITY_ID}</saml:Audience></saml:AudienceRestriction>
    </saml:Conditions>
    <saml:AuthnStatement AuthnInstant="{now}" SessionIndex="_session123">
      <saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef></saml:AuthnContext>
    </saml:AuthnStatement>
    <saml:AttributeStatement>{attribute_xml}</saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>"""
    return OneLogin_Saml2_Utils.add_sign(xml, idp_key, idp_cert)  # type: ignore[no-any-return]


@pytest.fixture
def provider(idp_cert_and_key: tuple[str, str]):
    idp_cert, _ = idp_cert_and_key
    return saml_provider(
        name="okta",
        idp_entity_id=IDP_ENTITY_ID,
        idp_sso_url=IDP_SSO_URL,
        idp_x509_cert=idp_cert,
        sp_entity_id=SP_ENTITY_ID,
        acs_url=ACS_URL,
    )


async def _make_app(tmp_path: Path, provider) -> Application:
    app = Application(Config.load(tmp_path))
    app.register(SamlServiceProvider(app, providers=[provider]))

    @app.get("/saml/{provider}/login")
    async def login(request):
        return saml_login(request, request.path_params["provider"])

    @app.post("/saml/{provider}/acs")
    async def acs(request):
        identity = await saml_acs(request, request.path_params["provider"])
        return JSONResponse(
            {
                "name_id": identity.name_id,
                "email": identity.email,
                "name": identity.name,
                "attributes": identity.attributes,
                "session_index": identity.session_index,
            }
        )

    @app.get("/saml/{provider}/metadata")
    async def metadata(request):
        return await saml_metadata(request, request.path_params["provider"])

    return app


# -- login_url() ---------------------------------------------------------------------


async def test_login_redirects_to_the_idp_sso_url(tmp_path: Path, provider) -> None:
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.get(f"/saml/{provider.name}/login", follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert response.headers["location"].startswith(IDP_SSO_URL)
    assert "SAMLRequest=" in response.headers["location"]


async def test_login_for_an_unknown_provider_is_a_404(tmp_path: Path, provider) -> None:
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.get("/saml/unknown/login", follow_redirects=False)

    assert response.status_code == 404


# -- handle_acs() ----------------------------------------------------------------------


async def test_acs_accepts_a_validly_signed_response(
    tmp_path: Path, provider, idp_cert_and_key: tuple[str, str]
) -> None:
    idp_cert, idp_key = idp_cert_and_key
    app = await _make_app(tmp_path, provider)
    signed = _build_signed_response(idp_cert, idp_key)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(
            f"/saml/{provider.name}/acs",
            data={"SAMLResponse": base64.b64encode(signed).decode()},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name_id"] == "ada@example.com"
    assert body["email"] == "ada@example.com"
    assert body["name"] == "Ada Lovelace"
    assert body["session_index"] == "_session123"
    assert body["attributes"] == {"email": ["ada@example.com"], "name": ["Ada Lovelace"]}


async def test_acs_rejects_a_replayed_response(tmp_path: Path, provider, idp_cert_and_key: tuple[str, str]) -> None:
    idp_cert, idp_key = idp_cert_and_key
    app = await _make_app(tmp_path, provider)
    signed = _build_signed_response(idp_cert, idp_key)
    encoded = base64.b64encode(signed).decode()

    async with client(app, base_url="https://app.example.com") as http:
        first = await http.post(f"/saml/{provider.name}/acs", data={"SAMLResponse": encoded})
        second = await http.post(f"/saml/{provider.name}/acs", data={"SAMLResponse": encoded})

    assert first.status_code == 200
    assert second.status_code == 403


async def test_acs_accepts_two_independently_signed_responses(
    tmp_path: Path, provider, idp_cert_and_key: tuple[str, str]
) -> None:
    # Regression guard for the replay check itself: two *different*
    # assertions (each with their own generated ID) from the same IdP
    # must not collide with each other.
    idp_cert, idp_key = idp_cert_and_key
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        first = await http.post(
            f"/saml/{provider.name}/acs",
            data={"SAMLResponse": base64.b64encode(_build_signed_response(idp_cert, idp_key)).decode()},
        )
        second = await http.post(
            f"/saml/{provider.name}/acs",
            data={"SAMLResponse": base64.b64encode(_build_signed_response(idp_cert, idp_key)).decode()},
        )

    assert first.status_code == 200
    assert second.status_code == 200


async def test_replay_protection_uses_an_explicitly_shared_cache(
    tmp_path: Path, provider, idp_cert_and_key: tuple[str, str]
) -> None:
    idp_cert, idp_key = idp_cert_and_key
    shared_cache = InMemoryCache()
    app = Application(Config.load(tmp_path))
    app.register(SamlServiceProvider(app, providers=[provider], replay_cache=shared_cache))

    @app.post("/saml/{provider}/acs")
    async def acs(request):
        identity = await saml_acs(request, request.path_params["provider"])
        return JSONResponse({"email": identity.email})

    signed = _build_signed_response(idp_cert, idp_key)
    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(
            f"/saml/{provider.name}/acs", data={"SAMLResponse": base64.b64encode(signed).decode()}
        )

    assert response.status_code == 200
    # The assertion ID landed in the *caller's own* cache instance, not a
    # private one the manager built internally -- proving replay tracking
    # can be pointed at a real shared RedisCache in production.
    assert any(key.startswith("saml:seen-assertion:") for key in shared_cache._entries)


async def test_acs_rejects_a_tampered_response(tmp_path: Path, provider, idp_cert_and_key: tuple[str, str]) -> None:
    idp_cert, idp_key = idp_cert_and_key
    app = await _make_app(tmp_path, provider)
    signed = _build_signed_response(idp_cert, idp_key)
    tampered = signed.replace(b"ada@example.com", b"eve@evil.example")

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(
            f"/saml/{provider.name}/acs",
            data={"SAMLResponse": base64.b64encode(tampered).decode()},
        )

    assert response.status_code == 403


async def test_acs_rejects_a_response_signed_by_the_wrong_idp(tmp_path: Path, provider) -> None:
    # A different IdP's cert/key -- not the one configured on `provider` --
    # signs a response of its own; the SP must not accept it.
    directory = Path(subprocess.run(["mktemp", "-d"], check=True, capture_output=True, text=True).stdout.strip())
    key_path, cert_path = directory / "key.pem", directory / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-subj",
            "/CN=attacker.example.com",
        ],
        check=True,
        capture_output=True,
    )
    other_cert, other_key = cert_path.read_text(), key_path.read_text()
    signed = _build_signed_response(other_cert, other_key)
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(
            f"/saml/{provider.name}/acs",
            data={"SAMLResponse": base64.b64encode(signed).decode()},
        )

    assert response.status_code == 403


async def test_acs_rejects_an_expired_response(tmp_path: Path, provider, idp_cert_and_key: tuple[str, str]) -> None:
    idp_cert, idp_key = idp_cert_and_key
    signed = _build_signed_response(idp_cert, idp_key, not_on_or_after_delta=-60)
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(
            f"/saml/{provider.name}/acs",
            data={"SAMLResponse": base64.b64encode(signed).decode()},
        )

    assert response.status_code == 403


async def test_acs_without_a_saml_response_is_a_bad_request(tmp_path: Path, provider) -> None:
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(f"/saml/{provider.name}/acs", data={})

    assert response.status_code == 400


async def test_acs_recognizes_email_and_name_attributes_from_full_urns(
    tmp_path: Path, provider, idp_cert_and_key: tuple[str, str]
) -> None:
    idp_cert, idp_key = idp_cert_and_key
    signed = _build_signed_response(
        idp_cert,
        idp_key,
        attributes={
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress": "grace@example.com",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name": "Grace Hopper",
        },
    )
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(
            f"/saml/{provider.name}/acs",
            data={"SAMLResponse": base64.b64encode(signed).decode()},
        )

    body = response.json()
    assert body["email"] == "grace@example.com"
    assert body["name"] == "Grace Hopper"


async def test_email_attribute_override_takes_precedence(
    tmp_path: Path, idp_cert_and_key: tuple[str, str]
) -> None:
    idp_cert, idp_key = idp_cert_and_key
    provider_with_override = saml_provider(
        name="okta",
        idp_entity_id=IDP_ENTITY_ID,
        idp_sso_url=IDP_SSO_URL,
        idp_x509_cert=idp_cert,
        sp_entity_id=SP_ENTITY_ID,
        acs_url=ACS_URL,
        email_attribute="workEmail",
    )
    signed = _build_signed_response(
        idp_cert, idp_key, attributes={"email": "ignored@example.com", "workEmail": "real@example.com"}
    )
    app = await _make_app(tmp_path, provider_with_override)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.post(
            "/saml/okta/acs", data={"SAMLResponse": base64.b64encode(signed).decode()}
        )

    assert response.json()["email"] == "real@example.com"


# -- metadata_xml() --------------------------------------------------------------------


async def test_metadata_endpoint_serves_valid_sp_metadata(tmp_path: Path, provider) -> None:
    app = await _make_app(tmp_path, provider)

    async with client(app, base_url="https://app.example.com") as http:
        response = await http.get(f"/saml/{provider.name}/metadata")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/samlmetadata+xml"
    assert SP_ENTITY_ID in response.text
    assert ACS_URL in response.text


# -- ImportError hint ------------------------------------------------------------------


def test_import_onelogin_raises_a_clear_import_error_without_the_extra_installed() -> None:
    from zeython.saml import _import_onelogin

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name.startswith("onelogin"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match=r"pip install zeython\[saml\]"):
            _import_onelogin()
