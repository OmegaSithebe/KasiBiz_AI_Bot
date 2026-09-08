-- KasiBiz stock database schema (SQLite).
--
-- Money is stored in CENTS as INTEGER, never as a decimal/float.
-- R15.50 is stored as 1550. This guarantees a shop owner's totals, profit and
-- change are always exact -- floating point silently loses cents when summed.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    category            TEXT    NOT NULL DEFAULT 'General',
    unit                TEXT    NOT NULL DEFAULT 'each',
    cost_price_cents    INTEGER NOT NULL CHECK (cost_price_cents >= 0),
    selling_price_cents INTEGER NOT NULL CHECK (selling_price_cents >= 0),
    quantity            INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    low_stock_threshold INTEGER NOT NULL DEFAULT 5 CHECK (low_stock_threshold >= 0),
    barcode             TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),

    CHECK (length(trim(name)) > 0)
);

-- Case-insensitive uniqueness so "Bread", "bread" and "BREAD" cannot coexist.
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_name_unique
    ON products (lower(trim(name)));

CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);

CREATE INDEX IF NOT EXISTS idx_products_barcode
    ON products (barcode) WHERE barcode IS NOT NULL;

-- Keeps updated_at honest without every caller having to remember it.
CREATE TRIGGER IF NOT EXISTS trg_products_updated_at
AFTER UPDATE ON products
FOR EACH ROW
BEGIN
    UPDATE products
       SET updated_at = datetime('now')
     WHERE id = OLD.id;
END;

CREATE VIEW IF NOT EXISTS low_stock_products AS
    SELECT *
      FROM products
     WHERE quantity <= low_stock_threshold
     ORDER BY quantity ASC, name ASC;
