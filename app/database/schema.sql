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


-- One completed sale. Written only after the owner confirms, and always in the
-- same transaction as the stock reduction, so the books and the shelf can never
-- disagree.
CREATE TABLE IF NOT EXISTS sales (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The basket's own id. UNIQUE is what stops a double-tap on Confirm from
    -- recording the same sale twice.
    reference     TEXT    NOT NULL UNIQUE,
    total_cents   INTEGER NOT NULL CHECK (total_cents >= 0),
    paid_cents    INTEGER NOT NULL CHECK (paid_cents >= 0),
    change_cents  INTEGER NOT NULL CHECK (change_cents >= 0),
    cost_cents    INTEGER NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),
    profit_cents  INTEGER NOT NULL DEFAULT 0,
    item_count    INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    note          TEXT,
    sold_at       TEXT    NOT NULL DEFAULT (datetime('now')),

    CHECK (paid_cents >= total_cents)
);

CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales (sold_at);

-- The unit price and unit cost are copied in, not looked up later. A sale is a
-- historical record: if the shop reprices bread tomorrow, last week's profit
-- must not silently change.
CREATE TABLE IF NOT EXISTS sale_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id          INTEGER NOT NULL REFERENCES sales (id) ON DELETE CASCADE,
    product_id       INTEGER          REFERENCES products (id) ON DELETE SET NULL,
    product_name     TEXT    NOT NULL,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    unit_cost_cents  INTEGER NOT NULL DEFAULT 0 CHECK (unit_cost_cents >= 0),
    line_total_cents INTEGER NOT NULL CHECK (line_total_cents >= 0)
);

CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items (sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_product ON sale_items (product_id);
