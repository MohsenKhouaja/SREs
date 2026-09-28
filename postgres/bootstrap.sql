DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user LOGIN PASSWORD 'app_user';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lab_controller') THEN
    CREATE ROLE lab_controller LOGIN PASSWORD 'lab_controller';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE incident_db TO app_user, lab_controller;
GRANT USAGE ON SCHEMA public TO app_user, lab_controller;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
GRANT SELECT, UPDATE, DELETE, TRUNCATE ON TABLE users TO lab_controller;
GRANT pg_monitor, pg_signal_backend TO lab_controller;
