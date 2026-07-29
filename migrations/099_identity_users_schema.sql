-- Canonical root-runner ownership for identity-service persistence.
-- Compatible with databases previously initialized by identity Alembic
-- revision 20260309_0001; it never creates users or credentials.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_type t
          JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname = 'public' AND t.typname = 'user_role'
    ) THEN
        CREATE TYPE public.user_role AS ENUM ('admin', 'user');
    END IF;
END $$;

ALTER TYPE public.user_role ADD VALUE IF NOT EXISTS 'admin';
ALTER TYPE public.user_role ADD VALUE IF NOT EXISTS 'user';

CREATE TABLE IF NOT EXISTS public.users (
    email VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL,
    role public.user_role NOT NULL,
    id VARCHAR(36) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT users_pkey PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON public.users (email);

DO $$
DECLARE
    incompatible_count INTEGER;
BEGIN
    SELECT count(*) INTO incompatible_count
      FROM (VALUES
        ('email', 'character varying', 255, 'NO', NULL, NULL),
        ('hashed_password', 'character varying', 255, 'NO', NULL, NULL),
        ('display_name', 'character varying', 128, 'NO', NULL, NULL),
        ('is_active', 'boolean', NULL, 'NO', NULL, NULL),
        ('role', 'USER-DEFINED', NULL, 'NO', 'public', 'user_role'),
        ('id', 'character varying', 36, 'NO', NULL, NULL),
        ('created_at', 'timestamp with time zone', NULL, 'NO', NULL, NULL),
        ('updated_at', 'timestamp with time zone', NULL, 'NO', NULL, NULL)
      ) AS expected(
        column_name, data_type, character_maximum_length, is_nullable,
        udt_schema, udt_name
      )
      LEFT JOIN information_schema.columns actual
        ON actual.table_schema = 'public'
       AND actual.table_name = 'users'
       AND actual.column_name = expected.column_name
     WHERE actual.column_name IS NULL
        OR actual.data_type <> expected.data_type
        OR actual.character_maximum_length IS DISTINCT FROM expected.character_maximum_length
        OR actual.is_nullable <> expected.is_nullable
        OR (
          expected.udt_name IS NOT NULL
          AND (actual.udt_schema <> expected.udt_schema OR actual.udt_name <> expected.udt_name)
        );

    IF incompatible_count <> 0 THEN
        RAISE EXCEPTION 'existing public.users schema is incompatible with identity contract';
    END IF;
END $$;

-- Bootstrap is deliberately separate and explicit:
--   python services/identity-service/scripts/bootstrap_admin.py --email ... --display-name ...
-- No default identity or credential is ever inserted by migrations.
