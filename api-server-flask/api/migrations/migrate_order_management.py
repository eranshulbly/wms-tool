# Method 1: Create a migration script file
# Create: api/migrations/migrate_order_management.py

import os
import sqlite3
from datetime import datetime


def run_migration():
    """
    Run the order management database migration
    """
    # Get the database path
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(BASE_DIR, 'db.sqlite3')

    print(f"Running migration on database: {db_path}")

    # Connect to SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Start transaction
        cursor.execute("BEGIN TRANSACTION;")

        print("1. Adding new columns to potential_order_product table...")
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(potential_order_product);")
        columns = [row[1] for row in cursor.fetchall()]

        if 'quantity_packed' not in columns:
            cursor.execute("ALTER TABLE potential_order_product ADD COLUMN quantity_packed INTEGER DEFAULT 0;")
            print("   - Added quantity_packed column")

        if 'quantity_remaining' not in columns:
            cursor.execute("ALTER TABLE potential_order_product ADD COLUMN quantity_remaining INTEGER;")
            print("   - Added quantity_remaining column")

        print("2. Creating box_product junction table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS box_product (
                box_product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                potential_order_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (box_id) REFERENCES box(box_id),
                FOREIGN KEY (product_id) REFERENCES product(product_id),
                FOREIGN KEY (potential_order_id) REFERENCES potential_order(potential_order_id)
            );
        """)
        print("   - Created box_product table")

        print("3. Creating indexes...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_box_product_box_id ON box_product(box_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_box_product_product_id ON box_product(product_id);")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_box_product_potential_order_id ON box_product(potential_order_id);")
        print("   - Created indexes")

        print("4. Adding order states...")
        order_states = [
            ('Open', 'Order is open and ready for processing'),
            ('Picking', 'Order is being picked from inventory'),
            ('Packing', 'Order items are being packed'),
            ('Dispatch Ready', 'Order is ready for dispatch'),
            ('Completed', 'Order has been fully processed and dispatched'),
            ('Partially Completed', 'Order has been partially completed with remaining items')
        ]

        for state_name, description in order_states:
            cursor.execute("""
                INSERT OR IGNORE INTO order_state (state_name, description) 
                VALUES (?, ?);
            """, (state_name, description))
        print("   - Added order states")

        print("5. Creating trigger for quantity_remaining...")
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_quantity_remaining 
            AFTER UPDATE OF quantity_packed ON potential_order_product
            BEGIN
                UPDATE potential_order_product 
                SET quantity_remaining = quantity - COALESCE(NEW.quantity_packed, 0)
                WHERE potential_order_product_id = NEW.potential_order_product_id;
            END;
        """)
        print("   - Created trigger")

        print("6. Initializing quantity_remaining for existing records...")
        cursor.execute("""
            UPDATE potential_order_product 
            SET quantity_remaining = quantity - COALESCE(quantity_packed, 0)
            WHERE quantity_remaining IS NULL;
        """)
        affected_rows = cursor.rowcount
        print(f"   - Updated {affected_rows} existing records")

        print("7. Adding sample data...")
        # Add warehouses if they don't exist
        cursor.execute("""
            INSERT OR IGNORE INTO warehouse (name, location, created_at, updated_at) 
            VALUES (?, ?, ?, ?);
        """, ('Main Warehouse', 'Primary Location', datetime.now(), datetime.now()))

        # Add companies if they don't exist
        cursor.execute("""
            INSERT OR IGNORE INTO company (name, created_at, updated_at) 
            VALUES (?, ?, ?);
        """, ('Default Company', datetime.now(), datetime.now()))

        print("   - Added sample warehouses and companies")

        # Commit transaction
        cursor.execute("COMMIT;")
        print("\n✅ Migration completed successfully!")

    except Exception as e:
        cursor.execute("ROLLBACK;")
        print(f"\n❌ Migration failed: {str(e)}")
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()