DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qto_app') THEN
    CREATE ROLE qto_app LOGIN PASSWORD 'qto_app';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qto_infisical') THEN
    CREATE ROLE qto_infisical LOGIN PASSWORD 'qto_infisical';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qto_mlflow') THEN
    CREATE ROLE qto_mlflow LOGIN PASSWORD 'qto_mlflow';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qto_langfuse') THEN
    CREATE ROLE qto_langfuse LOGIN PASSWORD 'qto_langfuse';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qto_temporal') THEN
    CREATE ROLE qto_temporal LOGIN PASSWORD 'qto_temporal';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qto_superset') THEN
    CREATE ROLE qto_superset LOGIN PASSWORD 'qto_superset';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qto_monitor') THEN
    CREATE ROLE qto_monitor LOGIN PASSWORD 'qto_monitor';
  END IF;
END $$;

ALTER DATABASE quant_team_os OWNER TO qto_app;
CREATE DATABASE qto_infisical OWNER qto_infisical;
CREATE DATABASE qto_mlflow OWNER qto_mlflow;
CREATE DATABASE qto_langfuse OWNER qto_langfuse;
CREATE DATABASE qto_temporal OWNER qto_temporal;
CREATE DATABASE qto_temporal_visibility OWNER qto_temporal;
CREATE DATABASE qto_superset OWNER qto_superset;
GRANT pg_monitor TO qto_monitor;
