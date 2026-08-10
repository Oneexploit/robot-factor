from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from robot_factor.models import CompanyProfile, Customer, Invoice, Product
from robot_factor.schemas import (
    CompanyRead,
    CompanyUpdate,
    CustomerRead,
    InvoiceRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["admin"])


async def require_admin_key(
    request: Request,
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
) -> None:
    expected = request.app.state.settings.admin_api_key
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin key")


async def get_session(request: Request):
    async with request.app.state.database.session_factory() as session:
        yield session


AdminAuth = Depends(require_admin_key)
DbSession = Depends(get_session)


@router.get("/company", response_model=CompanyRead, dependencies=[AdminAuth])
async def get_company(session: AsyncSession = DbSession) -> CompanyProfile:
    company = await session.get(CompanyProfile, 1)
    if company is None:
        raise HTTPException(status_code=404, detail="company profile not found")
    return company


@router.patch("/company", response_model=CompanyRead, dependencies=[AdminAuth])
async def update_company(
    payload: CompanyUpdate, session: AsyncSession = DbSession
) -> CompanyProfile:
    company = await session.get(CompanyProfile, 1)
    if company is None:
        raise HTTPException(status_code=404, detail="company profile not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field_name, value)
    await session.commit()
    await session.refresh(company)
    return company


@router.get("/products", response_model=list[ProductRead], dependencies=[AdminAuth])
async def list_products(
    active_only: bool = True,
    session: AsyncSession = DbSession,
) -> list[Product]:
    statement = select(Product).order_by(Product.name)
    if active_only:
        statement = statement.where(Product.is_active.is_(True))
    return list((await session.scalars(statement)).all())


@router.post(
    "/products",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AdminAuth],
)
async def create_product(payload: ProductCreate, session: AsyncSession = DbSession) -> Product:
    product = Product(**payload.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductRead, dependencies=[AdminAuth])
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    session: AsyncSession = DbSession,
) -> Product:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field_name, value)
    await session.commit()
    await session.refresh(product)
    return product


@router.get("/customers", response_model=list[CustomerRead], dependencies=[AdminAuth])
async def list_customers(
    query: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = DbSession,
) -> list[Customer]:
    statement = select(Customer).order_by(Customer.updated_at.desc()).limit(limit)
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(Customer.display_name.ilike(pattern), Customer.phone.ilike(pattern))
        )
    return list((await session.scalars(statement)).all())


@router.get("/invoices", response_model=list[InvoiceRead], dependencies=[AdminAuth])
async def list_invoices(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = DbSession,
) -> list[Invoice]:
    statement = (
        select(Invoice)
        .options(selectinload(Invoice.items), selectinload(Invoice.customer))
        .order_by(Invoice.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(statement)).all())


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead, dependencies=[AdminAuth])
async def get_invoice(
    invoice_id: int, request: Request, session: AsyncSession = DbSession
) -> Invoice:
    try:
        return await request.app.state.invoice_service.get_invoice(session, invoice_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="invoice not found") from error


@router.post("/invoices/{invoice_id}/pdf", dependencies=[AdminAuth])
async def regenerate_invoice_pdf(
    invoice_id: int,
    request: Request,
    session: AsyncSession = DbSession,
) -> FileResponse:
    try:
        path = await request.app.state.pdf_service.render_invoice(session, invoice_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="invoice not found") from error
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)
