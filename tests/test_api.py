from __future__ import annotations

import httpx

from robot_factor.main import create_app


async def test_health_and_admin_auth(app_context) -> None:
    settings, _ = app_context
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/healthz")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            unauthorized = await client.get("/api/v1/company")
            assert unauthorized.status_code == 401

            company = await client.patch(
                "/api/v1/company",
                headers={"X-Admin-Key": "test-admin-key"},
                json={"brand_name": "زغال تست", "money_unit": "تومان"},
            )
            assert company.status_code == 200
            assert company.json()["brand_name"] == "زغال تست"
