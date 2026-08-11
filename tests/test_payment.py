"""
VocalizeBot Payment Service - Unit Tests
=========================================

Regression suite for ``src.services.payment``.

What this covers
----------------
The pure helpers and the credential-aware service constructor. The highest-
impact bugs the diagnostic pass found are:

1. ``_fallback_paypal_url`` previously built ``paypal.me/talhatil/{int(amount)}``:
   * Wrong handle — ``talhatil`` was a legacy alias; the operator's real
     PayPal.me is ``talderie`` (consistent with ``auto_renewal.py`` and
     ``lead_hunt.py``).
   * ``int(amount)`` silently dropped fractional cents ($29.50 became $29).

2. ``datetime.utcnow()`` is deprecated on Python 3.12+ and removed on 3.13
   (this codebase runs on 3.13). The new ``_utcnow`` helper is fully
   timezone-aware so Pydantic v2 datetime validation does not reject the
   values as naive.

What we deliberately *don't* cover
----------------------------------
* Live PayPal API calls — gated by credentials, rate-limited.
* DB roundtrips through ``get_db_context`` — needs an async sqlite engine;
  indirectly covered by ``test_agent.py``.

Running
-------
::

    pytest vocalize/tests/test_payment.py -v
"""
import os
from datetime import datetime, timedelta
from unittest.mock import patch

# Force a minimal, deterministic env so the test doesn't accidentally pull
# any real Pydantic ``Settings`` defaults that need an async DB session.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-import-only")


class TestFallbackPaypalUrl:
    """Verify the PayPal.me fallback URL matches the operator's handle
    and preserves cents (the historical bug truncated $29.50 to $29)."""

    def _import(self):
        from src.services.payment import (
            _fallback_paypal_url,
            DEFAULT_PAYPAL_ME_HANDLE,
        )
        return _fallback_paypal_url, DEFAULT_PAYPAL_ME_HANDLE

    def test_default_handle_is_talderie_not_talhatil(self):
        _, handle = self._import()
        # Regression guard: the old build used ``talhatil`` (typo / legacy
        # handle) which led to 404s on PayPal.me. ``auto_renewal.py`` and
        # ``lead_hunt.py`` both reference ``talderie`` — that's the real
        # operator account.
        assert handle == "talderie"

    def test_integer_amount(self):
        url, _ = self._import()
        assert url(29) == "https://www.paypal.me/talderie/29.00"

    def test_decimal_amount_preserves_cents(self):
        url, _ = self._import()
        # Critical regression — $29.50 used to round to just "29".
        assert url(29.5) == "https://www.paypal.me/talderie/29.50"
        assert url(29.99) == "https://www.paypal.me/talderie/29.99"

    def test_rounds_to_two_decimals(self):
        url, _ = self._import()
        # ``round(half_even)`` halves make the 3rd decimal vanish — that's
        # exactly what PayPal.me expects.
        assert url(0.1 + 0.2) == "https://www.paypal.me/talderie/0.30"

    def test_url_is_https_and_uses_www_paypal_me(self):
        url, _ = self._import()
        out = url(1)
        assert out.startswith("https://www.paypal.me/")


class TestUtcNowHelper:
    """``_utcnow`` must be timezone-aware so Pydantic v2 datetime validators
    don't reject the value as naive."""

    def test_returns_timezone_aware_datetime(self):
        from src.services.payment import _utcnow
        now = _utcnow()
        assert isinstance(now, datetime)
        assert now.tzinfo is not None
        # ``timezone.utc.utcoffset(None)`` returns ``timedelta(0)`` — using
        # the public ``utcoffset()`` of a ``timezone`` instance without an
        # argument is rejected (``TypeError``) on Python 3.13+.
        assert now.utcoffset() == timedelta(0)

    def test_does_not_use_deprecated_datetime_utcnow_in_code(self):
        # ``datetime.utcnow`` was deprecated in 3.12 + raises/breaks in 3.13.
        # The string may legitimately appear in a docstring describing the
        # fix, but never as a callable expression. We tokenize the AST and
        # walk every Name ``datetime`` reference to assert none of the call
        # names inside payment.py is ``utcnow``.
        import ast
        import src.services.payment as payment_module

        with open(payment_module.__file__, "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, payment_module.__file__)

        offenders = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "utcnow"
            ):
                value = node.func.value
                if isinstance(value, ast.Name) and value.id == "datetime":
                    offenders.append((node.lineno, ast.unparse(node)))
        assert not offenders, (
            "payment.py still calls datetime.utcnow(): "
            + ", ".join(f"line {ln} -> {code}" for ln, code in offenders)
            + ". Use the _utcnow() helper instead."
        )


class TestPaymentServiceConstruction:
    """Verify the service constructs cleanly under a few credential shapes
    WITHOUT making any PayPal network calls. ``PaymentService`` reads
    ``settings.paypal_*`` via a module-level binding, so we patch
    ``src.services.payment.settings`` rather than the global Settings class.
    """

    def test_no_credentials_yields_no_base_url(self):
        import src.services.payment as payment_module
        # Pretend the operator forgot to set PayPal creds.
        with patch.object(payment_module, "settings") as fake_settings:
            fake_settings.paypal_client_id = None
            fake_settings.paypal_client_secret = None
            fake_settings.paypal_mode = "sandbox"
            svc = payment_module.PaymentService()
        assert svc.paypal_base_url is None
        assert svc.paypal_mode == "sandbox"

    def test_live_credentials_pick_live_endpoint(self):
        import src.services.payment as payment_module
        with patch.object(payment_module, "settings") as fake_settings:
            fake_settings.paypal_client_id = "fake-id"
            fake_settings.paypal_client_secret = "fake-secret"
            fake_settings.paypal_mode = "live"
            svc = payment_module.PaymentService()
        assert svc.paypal_base_url == "https://api-m.paypal.com"
        assert svc.paypal_mode == "live"

    def test_sandbox_credentials_pick_sandbox_endpoint(self):
        import src.services.payment as payment_module
        with patch.object(payment_module, "settings") as fake_settings:
            fake_settings.paypal_client_id = "fake-id"
            fake_settings.paypal_client_secret = "fake-secret"
            fake_settings.paypal_mode = "sandbox"
            svc = payment_module.PaymentService()
        assert svc.paypal_base_url == "https://api-m.sandbox.paypal.com"


class TestNoStaleTalhatilHandle:
    """Regression guard against copy-paste of the legacy handle back into
    payment.py. A real revert (e.g., ``f"https://paypal.me/talhatil/{x}"``)
    would trip this test immediately.
    """

    def test_no_talhatil_in_active_paypal_urls(self):
        import ast
        import src.services.payment as payment_module

        with open(payment_module.__file__, "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, payment_module.__file__)

        offenders = []
        for node in ast.walk(tree):
            # Only flag string *literal* values that look like URL paths
            # — docstring prose describing the historical bug is fine.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if "paypal.me" in value and "talhatil" in value:
                    offenders.append((node.lineno, value[:80]))
        assert not offenders, (
            "payment.py still references the legacy talhatil handle in a "
            "constructed URL: "
            + ", ".join(f"line {ln}: {s!r}" for ln, s in offenders)
        )
