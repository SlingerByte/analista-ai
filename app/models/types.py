import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
BigIntType = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
