CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS orders (
  id UUID PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO users (name, email) VALUES
  ('Ada Lovelace', 'ada@example.test'),
  ('Grace Hopper', 'grace@example.test'),
  ('Edsger Dijkstra', 'edsger@example.test')
ON CONFLICT (email) DO NOTHING;
