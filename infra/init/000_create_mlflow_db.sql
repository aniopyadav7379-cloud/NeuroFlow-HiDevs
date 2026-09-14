-- Runs before 001_schema.sql (docker-entrypoint-initdb.d executes files in
-- lexical order). MLflow's backend store needs its own database — the
-- docker-compose mlflow service points at postgresql://.../mlflow.
CREATE DATABASE mlflow OWNER neuroflow;
