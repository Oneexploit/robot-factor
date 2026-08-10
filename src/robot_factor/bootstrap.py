from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from robot_factor.config import Settings
from robot_factor.models import AdminUser, CompanyProfile


async def bootstrap_data(session: AsyncSession, settings: Settings) -> None:
    company = await session.get(CompanyProfile, 1)
    if company is None:
        session.add(CompanyProfile(id=1))

    configured = set(settings.admin_identities)
    existing = list((await session.scalars(select(AdminUser))).all())
    existing_map = {(admin.platform, admin.external_user_id): admin for admin in existing}

    for platform, external_id in configured:
        admin = existing_map.get((platform, external_id))
        if admin is None:
            session.add(
                AdminUser(
                    platform=platform,
                    external_user_id=external_id,
                    display_name=f"مدیر {platform}",
                    is_active=True,
                )
            )
        else:
            admin.is_active = True

    # In production the environment allow-list is authoritative. This closes access
    # after removing an identity from configuration without deleting its audit history.
    if settings.is_production:
        for identity, admin in existing_map.items():
            if identity not in configured:
                admin.is_active = False

    await session.commit()
