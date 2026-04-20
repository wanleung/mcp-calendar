Now let me verify the tests can run:
The issue is that the `oauth_manager.py` imports the `settings` singleton at module load time, so patching `Settings.__init__` doesn't work. I need to patch the module-level `settings` object directly.
Now I need to fix the tests that patch `settings` — since `settings` is a module-level singleton, I should patch `src.auth.oauth_manager.settings` instead.
The failing tests need `settings.google_client_id`/`settings.google_client_secret` to be non-empty. I need to patch `src.auth.oauth_manager.settings` in the refresh tests.
Now fix the `get_credentials` tests that trigger refresh — they also need settings patched:
All 40 tests pass. Created:

- **`tests/integration/test_oauth_manager.py`** — Integration tests (40 test cases) covering:
  - **Token initialization** — empty cache, set/update Google/Outlook tokens, preserve existing refresh tokens
  - **Get credentials** — valid token return, auto-refresh expired Google/Outlook tokens, unconfigured provider error, missing refresh token error, near-expiry refresh trigger
  - **Token refresh** — successful Google/Outlook refresh, missing credentials errors, unsupported provider, HTTP errors (invalid_grant), network errors, refresh token preservation, concurrent refresh lock prevention
  - **Token validation** — valid/invalid Google tokens, valid/invalid Outlook tokens, unknown provider, network errors, correct endpoint URLs, auth header verification
  - **Token info/expiry** — expired/valid/unconfigured checks, metadata retrieval without exposing access tokens, refresh token presence
  - **AuthenticationError** — provider context, no-provider mode, exception inheritance

- **`src/auth/__init__.py`** — Package init exporting `OAuthManager` and `AuthenticationError`

- **`src/auth/oauth_manager.py`** — Copied from `calendar-mcp-service/` to the main `src/` directory