"""SQL Server connections and catalog browsing."""

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto, models, schemas
from app.db import get_session
from app.services import presenters
from app.services.catalog import (
    Catalog,
    CatalogError,
    ConnectionConfig,
    ObjectQuery,
    get_catalog,
    is_system_database,
    resolve_address,
)

router = APIRouter(prefix="/api/connections", tags=["connections"])


def _get_connection(session: Session, connection_id: int) -> models.Connection:
    conn = session.get(models.Connection, connection_id)
    if conn is None:
        raise HTTPException(404, "Bağlantı bulunamadı.")
    return conn


def _validate(
    session: Session, body: schemas.ConnectionInput, connection_id: int | None
) -> None:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Bağlantı adı zorunludur.")
    if len(name) > 100:
        raise HTTPException(422, "Bağlantı adı en fazla 100 karakter olabilir.")
    try:
        resolve_address(body.server, body.port, aliases={})
    except CatalogError as error:
        raise HTTPException(422, str(error)) from None
    if not 1 <= body.port <= 65535:
        raise HTTPException(422, "Port 1 ile 65535 arasında olmalıdır.")
    if not body.username.strip():
        raise HTTPException(422, "Kullanıcı adı zorunludur.")
    existing = session.scalar(select(models.Connection).where(models.Connection.name == name))
    if existing is not None and existing.id != connection_id:
        raise HTTPException(409, f"'{name}' adlı bir bağlantı zaten var.")


def _apply(conn: models.Connection, body: schemas.ConnectionInput) -> None:
    conn.name = body.name.strip()
    conn.server = body.server.strip()
    conn.port = body.port
    conn.username = body.username.strip()
    conn.encrypt = body.encrypt
    conn.trust_server_certificate = body.trust_server_certificate
    if body.password:
        conn.password_enc = crypto.encrypt(body.password)


async def _call(function, *args):  # type: ignore[no-untyped-def]
    """Run a blocking catalog call in the thread pool; failures become 502."""
    try:
        return await run_in_threadpool(function, *args)
    except CatalogError as error:
        raise HTTPException(502, str(error)) from None


@router.get("", response_model=list[schemas.ConnectionOut])
def list_connections(session: Session = Depends(get_session)) -> list[schemas.ConnectionOut]:
    rows = session.scalars(select(models.Connection).order_by(models.Connection.name))
    return [presenters.connection_out(conn) for conn in rows]


@router.post("", response_model=schemas.ConnectionOut, status_code=201)
def create_connection(
    body: schemas.ConnectionInput, session: Session = Depends(get_session)
) -> schemas.ConnectionOut:
    _validate(session, body, None)
    if not body.password:
        raise HTTPException(422, "Parola zorunludur.")
    conn = models.Connection()
    _apply(conn, body)
    session.add(conn)
    session.commit()
    return presenters.connection_out(conn)


@router.post("/test", response_model=schemas.ConnectionTestResult)
async def test_connection(
    body: schemas.ConnectionTestInput,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> schemas.ConnectionTestResult:
    password = body.password or None
    if password is None and body.id is not None:
        stored = session.get(models.Connection, body.id)
        if stored is not None:
            password = crypto.decrypt(stored.password_enc)
    if not body.server.strip() or not body.username.strip():
        return schemas.ConnectionTestResult(ok=False, message="Sunucu ve kullanıcı adı zorunludur.")
    if not password:
        return schemas.ConnectionTestResult(ok=False, message="Parola girilmemiş.")
    config = ConnectionConfig(
        server=body.server,
        port=body.port,
        username=body.username,
        password=password,
        encrypt=body.encrypt,
        trust_server_certificate=body.trust_server_certificate,
    )
    try:
        result = await run_in_threadpool(catalog.probe, config)
    except CatalogError as error:
        return schemas.ConnectionTestResult(ok=False, message=str(error))
    return schemas.ConnectionTestResult(
        ok=True,
        message="Bağlantı başarılı.",
        server_version=result.server_version,
        database_count=result.database_count,
    )


@router.put("/{connection_id}", response_model=schemas.ConnectionOut)
def update_connection(
    connection_id: int, body: schemas.ConnectionInput, session: Session = Depends(get_session)
) -> schemas.ConnectionOut:
    conn = _get_connection(session, connection_id)
    _validate(session, body, connection_id)
    _apply(conn, body)
    session.commit()
    return presenters.connection_out(conn)


@router.delete("/{connection_id}", status_code=204)
def delete_connection(connection_id: int, session: Session = Depends(get_session)) -> Response:
    conn = _get_connection(session, connection_id)
    used = session.scalar(
        select(models.ScheduledAnalysis.name).where(models.ScheduledAnalysis.connection_id == connection_id)
    )
    if used is not None:
        raise HTTPException(409, f"Bu bağlantı '{used}' zamanlanmış analizinde kullanılıyor; önce onu silin veya değiştirin.")
    for analysis in session.scalars(
        select(models.Analysis).where(models.Analysis.connection_id == connection_id)
    ):
        analysis.connection_id = None
    session.delete(conn)
    session.commit()
    return Response(status_code=204)


@router.get("/{connection_id}/databases", response_model=list[str])
async def list_databases(
    connection_id: int,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> list[str]:
    config = presenters.connection_config(_get_connection(session, connection_id))
    return await _call(catalog.list_databases, config)


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@router.get("/{connection_id}/schemas", response_model=list[schemas.SchemaInfo])
async def list_schemas(
    connection_id: int,
    databases: str | None = None,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> list[schemas.SchemaInfo]:
    config = presenters.connection_config(_get_connection(session, connection_id))
    selected = [db for db in _split(databases) if not is_system_database(db)]
    if not selected:
        selected = await _call(catalog.list_databases, config)
    rows = await _call(catalog.list_schemas, config, selected)
    return [
        schemas.SchemaInfo(database=db, schema_=schema, object_count=count)
        for db, schema, count in rows
    ]


@router.post("/{connection_id}/objects", response_model=schemas.ObjectListResponse)
async def list_objects(
    connection_id: int,
    body: schemas.ObjectFilter,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> schemas.ObjectListResponse:
    config = presenters.connection_config(_get_connection(session, connection_id))
    databases = list(dict.fromkeys(db.strip() for db in body.databases if db.strip()))
    if not databases:
        raise HTTPException(422, "En az bir veritabanı seçilmelidir.")
    if any(is_system_database(db) for db in databases):
        raise HTTPException(422, "Sistem veritabanları incelenemez.")
    for start, end in (
        (body.created_from, body.created_to),
        (body.modified_from, body.modified_to),
    ):
        if start and end and start > end:
            raise HTTPException(422, "Başlangıç tarihi bitiş tarihinden sonra olamaz.")
    query = ObjectQuery(
        databases=databases,
        schemas=body.schemas,
        types=body.types,
        created_from=body.created_from,
        created_to=body.created_to,
        modified_from=body.modified_from,
        modified_to=body.modified_to,
        search=body.search,
    )
    found = await _call(catalog.list_objects, config, query)
    found.sort(key=lambda o: (o.database.lower(), o.schema.lower(), o.name.lower()))
    items = [
        schemas.DbObject(
            database=o.database,
            schema_=o.schema,
            name=o.name,
            type=o.type,  # type: ignore[arg-type]
            create_date=o.create_date,
            modify_date=o.modify_date,
        )
        for o in found
    ]
    return schemas.ObjectListResponse(items=items, total=len(items))
