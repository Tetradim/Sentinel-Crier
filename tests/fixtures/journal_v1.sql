BEGIN TRANSACTION;
CREATE TABLE audit (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL
            );
CREATE TABLE executions (
                tenant_id TEXT NOT NULL,
                broker_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                price TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, broker_id, account_id, execution_id),
                FOREIGN KEY (tenant_id, client_order_id)
                    REFERENCES orders(tenant_id, client_order_id)
            );
CREATE TABLE groups (
                tenant_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                confirmed_at TEXT,
                PRIMARY KEY (tenant_id, group_id)
            );
CREATE TABLE orders (
                tenant_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL,
                broker_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                contract_id TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                limit_price TEXT NOT NULL,
                state TEXT NOT NULL,
                broker_order_id TEXT,
                cumulative_filled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tenant_id, client_order_id),
                FOREIGN KEY (tenant_id, group_id)
                    REFERENCES groups(tenant_id, group_id)
            );
CREATE UNIQUE INDEX one_account_per_group
                ON orders(tenant_id, group_id, broker_id, account_id);
DELETE FROM "sqlite_sequence";
COMMIT;