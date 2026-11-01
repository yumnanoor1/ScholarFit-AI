"""
Adds users.google_sub, the link between an account and a Google identity.
create_all() does not alter existing tables, so this script is needed once per schema.

Usage:
    python migrate_google_accounts.py --schema NAME           prints the SQL, connects to nothing
    python migrate_google_accounts.py --schema NAME --apply   changes the database

--schema is required and has no default, so this can never fall back to public on its own.

WARNING: --apply changes the database in DATABASE_URL. It runs only if that connection's current_schema()
already equals --schema. This script never changes the search path to make a mismatch pass.

Everything runs in one transaction: any failed check rolls back both statements, and success is printed only
after the commit. Rerunning is safe only when the existing column and index match the expected definitions.
IF NOT EXISTS alone proves nothing, so a same-named column or index with another definition stops the
migration and is left as it was.

The API selects this column in every user query. Never run the API against a schema without google_sub:
it starts normally, then sign-in and every authenticated request fail.

Rollback, replacing NAME with the schema:
    DROP INDEX IF EXISTS "NAME".ix_users_google_sub;
    ALTER TABLE "NAME".users DROP COLUMN IF EXISTS google_sub;
WARNING: rollback permanently deletes every stored Google identity link in that schema, and the API must
then stay off that schema until the column is restored or the code is reverted.
"""
import argparse
import re

SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
INDEX_NAME = "ix_users_google_sub"

COLUMN_DEFINITION = """
    SELECT data_type, is_nullable, character_maximum_length
    FROM information_schema.columns
    WHERE table_schema = :schema AND table_name = 'users' AND column_name = 'google_sub'
"""

INDEX_DEFINITION = """
    SELECT table_namespace.nspname AS table_schema, table_class.relname AS table_name,
           attribute.attname AS column_name, ix.indnatts AS column_count,
           ix.indisunique AS is_unique, ix.indisvalid AS is_valid, ix.indpred IS NULL AS covers_all_rows,
           ix.indexprs IS NULL AS plain_columns, ix.indnullsnotdistinct AS nulls_conflict,
           access_method.amname AS access_method,
           operator_class.opcdefault AND operator_class.opcmethod = index_class.relam
               AND operator_class.opcintype = CAST('text' AS regtype) AS default_operator_class
    FROM pg_index ix
    JOIN pg_class index_class ON index_class.oid = ix.indexrelid
    JOIN pg_namespace namespace ON namespace.oid = index_class.relnamespace
    JOIN pg_class table_class ON table_class.oid = ix.indrelid
    JOIN pg_namespace table_namespace ON table_namespace.oid = table_class.relnamespace
    JOIN pg_am access_method ON access_method.oid = index_class.relam
    JOIN pg_opclass operator_class ON operator_class.oid = ix.indclass[0]
    LEFT JOIN pg_attribute attribute ON attribute.attrelid = ix.indrelid AND attribute.attnum = ix.indkey[0]
    WHERE namespace.nspname = :schema AND index_class.relname = :index_name
"""


class MigrationRefused(Exception):
    """Raised inside the transaction, so nothing is committed"""


def schema_name(value):
    name = value.strip()
    if not SCHEMA_NAME.fullmatch(name):
        raise argparse.ArgumentTypeError("use a lowercase schema name: letters, digits and underscores, at most 63 characters")
    return name


def quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def statements_for(schema):
    table = f"{quoted(schema)}.users"
    return (
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS google_sub VARCHAR",
        # The name create_all() gives a unique indexed column. NULLs don't conflict, so unlinked accounts are unaffected
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} ON {table} (google_sub)",
    )


def verify_column(conn, text, schema):
    column = conn.execute(text(COLUMN_DEFINITION), {"schema": schema}).mappings().one_or_none()
    if column is None:
        raise MigrationRefused(f"{schema}.users has no google_sub column")
    if column["data_type"] != "character varying" or column["character_maximum_length"] is not None:
        raise MigrationRefused(f"{schema}.users.google_sub has the wrong type")
    if column["is_nullable"] != "YES":
        raise MigrationRefused(f"{schema}.users.google_sub must be nullable")


def verify_index(conn, text, schema):
    index = conn.execute(text(INDEX_DEFINITION), {"schema": schema, "index_name": INDEX_NAME}).mappings().one_or_none()
    if index is None:
        raise MigrationRefused(f"{schema}.{INDEX_NAME} does not exist")
    if index["table_schema"] != schema or index["table_name"] != "users":
        raise MigrationRefused(f"{schema}.{INDEX_NAME} belongs to another table")
    if index["column_name"] != "google_sub" or index["column_count"] != 1 or not index["plain_columns"]:
        raise MigrationRefused(f"{schema}.{INDEX_NAME} does not index only google_sub")
    if index["access_method"] != "btree":
        raise MigrationRefused(f"{schema}.{INDEX_NAME} is not a B-tree index")
    # A varchar column's default B-tree class is the one for text
    if not index["default_operator_class"]:
        raise MigrationRefused(f"{schema}.{INDEX_NAME} uses a custom operator class")
    if not index["is_unique"] or not index["is_valid"]:
        raise MigrationRefused(f"{schema}.{INDEX_NAME} is not a valid unique index")
    if not index["covers_all_rows"]:
        raise MigrationRefused(f"{schema}.{INDEX_NAME} covers only some rows")
    if index["nulls_conflict"]:
        raise MigrationRefused(f"{schema}.{INDEX_NAME} would allow only one unlinked account")


def apply_migration(schema):
    from sqlalchemy import text

    from app.database import engine

    with engine.begin() as conn:
        connected_to = conn.execute(text("SELECT current_schema()")).scalar_one()
        if connected_to != schema:
            raise MigrationRefused(f"the connection's current schema is {connected_to}, not {schema}")
        for statement in statements_for(schema):
            conn.execute(text(statement))
        verify_column(conn, text, schema)
        verify_index(conn, text, schema)


def main():
    parser = argparse.ArgumentParser(description="Adds users.google_sub to one explicitly chosen schema.", allow_abbrev=False)
    parser.add_argument("--schema", required=True, type=schema_name, help="the schema to change; there is no default")
    parser.add_argument("--apply", action="store_true", help="change the database; without this, only print the SQL")
    args = parser.parse_args()

    if not args.apply:
        for statement in statements_for(args.schema):
            print(statement)
        print("Nothing was changed. Add --apply to run these statements.")
        return

    try:
        apply_migration(args.schema)
    except MigrationRefused as refused:
        raise SystemExit(f"Refused, nothing was changed: {refused}")
    print(f"Committed and verified: {args.schema}.users.google_sub and {args.schema}.{INDEX_NAME}")


if __name__ == "__main__":
    main()
