from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Generator
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.data.synthetic_fixture import DEMO_DATASET_ID, DEMO_TARGET_ID, build_demo_dataset
from app.db.models import (
    Base,
    DatasetStockSnapshotORM,
    DatasetVersionORM,
    IngredientNutrientORM,
    IngredientORM,
    IngredientPriceORM,
    NutritionTargetLimitORM,
    NutritionTargetORM,
    RecipeIngredientORM,
    RecipeVariantORM,
)

SERVICE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = SERVICE_ROOT / "gizioptima.db"


def get_database_url() -> str:
    env_url = os.getenv("GIZIOPTIMA_DATABASE_URL")
    if env_url:
        return env_url
    return f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"


def create_db_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_database_url()
    connect_args = {"check_same_thread": False, "timeout": 15} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if ":memory:" not in url:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def run_alembic_migrations(database_url: str | None = None) -> None:
    """Run Alembic upgrade head against the target database URL."""
    url = database_url or get_database_url()
    alembic_ini = SERVICE_ROOT / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def seed_demo_dataset_if_empty(session: Session) -> None:
    """Idempotently seed the DEMO_ONLY synthetic dataset & target inside a single transaction."""
    existing = session.get(DatasetVersionORM, str(DEMO_DATASET_ID))
    if existing is not None:
        return

    dataset, ingredients_by_code, prices_by_code, stock_by_code, recipes, target = (
        build_demo_dataset()
    )

    ds_row = DatasetVersionORM(
        id=str(dataset.id),
        name=dataset.name,
        source_type=dataset.source_type.value,
        source_url=dataset.source_url,
        is_synthetic=dataset.is_synthetic,
        is_active=True,
        review_status=dataset.review_status.value,
        ingestion_metadata_json={
            "seeded": True,
            "label": "DEMO_ONLY",
            "ingredient_count": len(ingredients_by_code),
            "recipe_count": len(recipes),
        },
        created_at=dataset.created_at,
    )
    session.add(ds_row)
    session.flush()

    ing_id_by_code: dict[str, str] = {}
    for code, ing in ingredients_by_code.items():
        ing_id = str(ing.id)
        ing_id_by_code[code] = ing_id
        session.add(
            IngredientORM(
                id=ing_id,
                dataset_version_id=str(dataset.id),
                code=ing.code,
                name=ing.name,
                category=ing.category,
                edible_fraction=ing.edible_fraction,
                allergens_json=list(ing.allergens),
                source_type=ing.source_type.value,
                source_ref=ing.source_ref,
                review_status=ing.review_status.value,
            )
        )
    session.flush()

    for code, ing in ingredients_by_code.items():
        ing_id = ing_id_by_code[code]
        session.add(
            IngredientNutrientORM(
                ingredient_id=ing_id,
                energy_kcal_100g=ing.nutrients.energy_kcal_100g,
                protein_g_100g=ing.nutrients.protein_g_100g,
                fat_g_100g=ing.nutrients.fat_g_100g,
                carb_g_100g=ing.nutrients.carb_g_100g,
                fiber_g_100g=ing.nutrients.fiber_g_100g,
                iron_mg_100g=ing.nutrients.iron_mg_100g,
            )
        )

    for code, pr in prices_by_code.items():
        session.add(
            IngredientPriceORM(
                id=str(pr.id),
                dataset_version_id=str(dataset.id),
                ingredient_id=ing_id_by_code[code],
                price_idr_per_g=pr.price_idr_per_g,
                original_value=pr.original_value,
                original_unit=pr.original_unit,
                region=pr.region,
                observed_at=pr.observed_at,
                source_type=pr.source_type.value,
            )
        )

    for code, st in stock_by_code.items():
        session.add(
            DatasetStockSnapshotORM(
                id=str(uuid4()),
                dataset_version_id=str(dataset.id),
                ingredient_id=ing_id_by_code[code],
                stock_raw_g=st.stock_raw_g,
            )
        )

    for rec in recipes:
        rec_id = str(rec.id)
        session.add(
            RecipeVariantORM(
                id=rec_id,
                dataset_version_id=str(dataset.id),
                code=rec.code,
                name=rec.name,
                slot=rec.slot.value,
                family=rec.family,
                review_status=rec.review_status.value,
                reviewer=rec.reviewer,
                reviewed_at=rec.reviewed_at,
                active=rec.active,
                allergen_tags_json=list(rec.allergen_tags),
            )
        )
    session.flush()

    for rec in recipes:
        rec_id = str(rec.id)
        for ri in rec.ingredients:
            session.add(
                RecipeIngredientORM(
                    recipe_id=rec_id,
                    ingredient_id=ing_id_by_code[ri.ingredient_code],
                    raw_g_per_serving=ri.raw_g_per_serving,
                    retention_factor=ri.retention_factor,
                )
            )

    if session.get(NutritionTargetORM, str(DEMO_TARGET_ID)) is None:
        session.add(
            NutritionTargetORM(
                id=str(target.id),
                cohort=target.cohort,
                meal_type=target.meal_type,
                source_ref=target.source_ref,
                version=target.version,
                review_status=target.review_status.value,
            )
        )
        session.flush()
        for lim in target.limits:
            session.add(
                NutritionTargetLimitORM(
                    target_id=str(target.id),
                    nutrient_key=lim.nutrient_key,
                    min_per_serving=lim.min_per_serving,
                    max_per_serving=lim.max_per_serving,
                    unit=lim.unit,
                )
            )

    session.commit()


class DatabaseManager:
    """Thread-safe SQLAlchemy engine/session manager supporting clean reconfiguration for tests/restarts."""

    def __init__(self, database_url: str | None = None, auto_init: bool = False) -> None:
        self._lock = threading.Lock()
        self.database_url: str = database_url or ""
        self.engine: Engine | None = None
        self.SessionLocal: sessionmaker[Session] | None = None
        if auto_init:
            self.configure(database_url or get_database_url())

    def ensure_initialized(self) -> None:
        if self.engine is not None and self.SessionLocal is not None:
            return
        with self._lock:
            if self.engine is None or self.SessionLocal is None:
                self.configure(self.database_url or get_database_url())

    def configure(self, database_url: str, run_migrations: bool = True) -> None:
        if self.engine is not None:
            self.engine.dispose()
        self.database_url = database_url
        self.engine = create_db_engine(database_url)
        self.SessionLocal = sessionmaker(
            bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        if run_migrations:
            if ":memory:" in database_url:
                Base.metadata.create_all(bind=self.engine)
            else:
                run_alembic_migrations(database_url)
        with self.SessionLocal() as session:
            seed_demo_dataset_if_empty(session)
            from app.auth.seed import (
                ensure_default_kitchen_and_migrate_legacy,
                seed_development_demo_accounts,
            )

            ensure_default_kitchen_and_migrate_legacy(session)
            production = os.getenv("GIZIOPTIMA_ENV", "").strip().lower() == "production"
            seed_demo = os.getenv("GIZIOPTIMA_SEED_DEMO_ACCOUNTS", "").strip().lower() in {"1", "true", "yes"}
            if seed_demo and not production:
                demo_pw = os.getenv("GIZIOPTIMA_DEMO_PASSWORD", "")
                if len(demo_pw) >= 8:
                    seed_development_demo_accounts(session, demo_password=demo_pw)

    def get_session(self) -> Generator[Session, None, None]:
        self.ensure_initialized()
        assert self.SessionLocal is not None
        session = self.SessionLocal()
        try:
            yield session
        finally:
            session.close()


db_manager = DatabaseManager(auto_init=False)
