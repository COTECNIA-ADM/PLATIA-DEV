from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# Nombres de restricciones predecibles: sin ellos MySQL inventa nombres
# (contacts_ibfk_1...) y las migraciones futuras no pueden borrarlas con fiabilidad.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
# Migraciones multi-bind: una revisión con funciones por esquema (ADR-008)
migrate = Migrate(directory="migrations", compare_type=True)
jwt = JWTManager()
