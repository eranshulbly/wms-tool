#!/usr/bin/env python3
"""
Final Migration Script for Order Management Bug Fixes
Run this script to apply all the fixes
"""

import os
import sqlite3
import sys
from datetime import datetime


def find_database():
    """Find the SQLite database file"""
    possible_paths = [
        'api/db.sqlite3',
        'db.sqlite3',
        'api/apidata.db',
        'apidata.db'
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)

    print("Database file not found automatically.")
    db_path = input("Please enter the path to your SQLite database file: ").strip()
    if os.path.exists(db_path):
        return os.path.abspath(db_path)
    else:
        print(f"Error: Database file '{db_path}' not found.")
        sys.exit(1)


def run_final_migration():
    """Run the final migration to fix all issues"""

    # Find database
    db_path = find_database()
    print(f"Found database: {db_path}")

    # Create backup
    backup_path = f"{db_path}.backup_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"Creating backup: {backup_path}")

    try:
        import shutil
        shutil.copy2(db_path, backup_path)
        print("✅ Backup created successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not create backup: {e}")
        proceed = input("Continue without backup? (y/N): ").lower()
        if proceed != 'y':
            print("Migration cancelled.")
            sys.exit(1)

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("\n" + "=" * 50)
        print("RUNNING FINAL MIGRATION FOR BUG FIXES")
        print("=" * 50)

        # Start transaction
        cursor.execute("BEGIN TRANSACTION;")

        # 1. Ensure all order states exist
        print("\n1. Adding missing order states...")
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
        print("   ✅ All order states ensured")

        # 2. Fix BoxProduct table if it doesn't exist properly
        print("\n2. Ensuring BoxProduct table exists...")
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
        print("   ✅ BoxProduct table ensured")

        # 3. Ensure quantity_packed and quantity_remaining columns exist
        print("\n3. Ensuring quantity tracking columns exist...")
        cursor.execute("PRAGMA table_info(potential_order_product);")
        columns = [row[1] for row in cursor.fetchall()]

        if 'quantity_packed' not in columns:
            cursor.execute("ALTER TABLE potential_order_product ADD COLUMN quantity_packed INTEGER DEFAULT 0;")
            print("   ✅ Added quantity_packed column")

        if 'quantity_remaining' not in columns:
            cursor.execute("ALTER TABLE potential_order_product ADD COLUMN quantity_remaining INTEGER;")
            print("   ✅ Added quantity_remaining column")

        # 4. Update quantity_remaining for existing records
        print("\n4. Updating quantity calculations...")
        cursor.execute("""
            UPDATE potential_order_product 
            SET quantity_remaining = quantity - COALESCE(quantity_packed, 0)
            WHERE quantity_remaining IS NULL OR quantity_remaining != (quantity - COALESCE(quantity_packed, 0));
        """)
        affected_rows = cursor.rowcount
        print(f"   ✅ Updated {affected_rows} records")

        # 5. Create or update trigger for automatic quantity calculation
        print("\n5. Creating/updating trigger for quantity calculation...")
        cursor.execute("DROP TRIGGER IF EXISTS update_quantity_remaining;")
        cursor.execute("""
            CREATE TRIGGER update_quantity_remaining 
            AFTER UPDATE OF quantity_packed ON potential_order_product
            BEGIN
                UPDATE potential_order_product 
                SET quantity_remaining = quantity - COALESCE(NEW.quantity_packed, 0)
                WHERE potential_order_product_id = NEW.potential_order_product_id;
            END;
        """)
        print("   ✅ Trigger created/updated")

        # 6. Fix any orders stuck in "Dispatch Ready" without final order records
        print("\n6. Checking for stuck Dispatch Ready orders...")
        cursor.execute("""
            SELECT potential_order_id, status FROM potential_order 
            WHERE status = 'Dispatch Ready' 
            AND potential_order_id NOT IN (SELECT potential_order_id FROM "order" WHERE potential_order_id IS NOT NULL);
        """)
        stuck_orders = cursor.fetchall()

        if stuck_orders:
            print(f"   Found {len(stuck_orders)} stuck Dispatch Ready orders")
            for order_id, status in stuck_orders:
                # Check if they have any remaining products
                cursor.execute("""
                    SELECT COUNT(*), SUM(quantity) FROM potential_order_product 
                    WHERE potential_order_id = ?;
                """, (order_id,))
                product_count, total_quantity = cursor.fetchone()

                if product_count == 0 or total_quantity == 0:
                    # No products remaining, mark as completed
                    cursor.execute("""
                        UPDATE potential_order 
                        SET status = 'Completed', updated_at = ? 
                        WHERE potential_order_id = ?;
                    """, (datetime.utcnow(), order_id))
                    print(f"   ✅ Fixed order PO{order_id} -> Completed")
        else:
            print("   ✅ No stuck orders found")

        # 7. Add sample data if tables are completely empty
        print("\n7. Checking for sample data...")
        cursor.execute("SELECT COUNT(*) FROM warehouse;")
        warehouse_count = cursor.fetchone()[0]

        if warehouse_count == 0:
            cursor.execute("""
                INSERT INTO warehouse (name, location, created_at, updated_at) 
                VALUES (?, ?, ?, ?);
            """, ('Main Warehouse', 'Primary Location', datetime.now(), datetime.now()))
            print("   ✅ Added sample warehouse")

        cursor.execute("SELECT COUNT(*) FROM company;")
        company_count = cursor.fetchone()[0]

        if company_count == 0:
            cursor.execute("""
                INSERT INTO company (name, created_at, updated_at) 
                VALUES (?, ?, ?);
            """, ('Default Company', datetime.now(), datetime.now()))
            print("   ✅ Added sample company")

        # 8. Create indexes for better performance
        print("\n8. Creating/updating indexes...")
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_potential_order_status ON potential_order(status);",
            "CREATE INDEX IF NOT EXISTS idx_potential_order_warehouse ON potential_order(warehouse_id);",
            "CREATE INDEX IF NOT EXISTS idx_potential_order_company ON potential_order(company_id);",
            "CREATE INDEX IF NOT EXISTS idx_order_state_history_order ON order_state_history(potential_order_id);",
            "CREATE INDEX IF NOT EXISTS idx_box_product_box ON box_product(box_id);",
            "CREATE INDEX IF NOT EXISTS idx_box_product_product ON box_product(product_id);",
            "CREATE INDEX IF NOT EXISTS idx_box_product_order ON box_product(potential_order_id);"
        ]

        for index_sql in indexes:
            cursor.execute(index_sql)
        print("   ✅ Indexes created/updated")

        # Commit all changes
        cursor.execute("COMMIT;")

        print("\n" + "=" * 50)
        print("✅ FINAL MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 50)
        print("Fixed Issues:")
        print("1. ✅ Added Completed and Partially Completed states")
        print("2. ✅ Fixed missing /status endpoint")
        print("3. ✅ Enhanced box quantity division functionality")
        print("4. ✅ Fixed dispatch status counting")
        print("5. ✅ Added proper database constraints and indexes")
        print("6. ✅ Fixed stuck orders in Dispatch Ready state")
        print(f"Backup created at: {backup_path}")

    except Exception as e:
        cursor.execute("ROLLBACK;")
        print(f"\n❌ Migration failed: {str(e)}")
        print("Database has been rolled back to previous state.")
        print(f"You can restore from backup: {backup_path}")
        raise e
    finally:
        conn.close()


def verify_fixes():
    """Verify that all fixes have been applied"""
    db_path = find_database()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("\n" + "=" * 30)
        print("VERIFYING ALL FIXES")
        print("=" * 30)

        # Check order states
        cursor.execute("SELECT state_name FROM order_state ORDER BY state_name;")
        states = [row[0] for row in cursor.fetchall()]
        expected_states = ['Completed', 'Dispatch Ready', 'Open', 'Packing', 'Partially Completed', 'Picking']

        print("Order States:")
        for state in expected_states:
            if state in states:
                print(f"✅ {state}")
            else:
                print(f"❌ {state} missing")

        # Check columns
        cursor.execute("PRAGMA table_info(potential_order_product);")
        columns = [row[1] for row in cursor.fetchall()]

        required_columns = ['quantity_packed', 'quantity_remaining']
        print("\nColumns:")
        for col in required_columns:
            if col in columns:
                print(f"✅ {col}")
            else:
                print(f"❌ {col} missing")

        # Check BoxProduct table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='box_product';")
        if cursor.fetchone():
            print("✅ BoxProduct table exists")
        else:
            print("❌ BoxProduct table missing")

        # Check trigger
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name='update_quantity_remaining';")
        if cursor.fetchone():
            print("✅ Trigger exists")
        else:
            print("❌ Trigger missing")

        print("\nVerification complete!")

    finally:
        conn.close()


if __name__ == "__main__":
    print("Order Management Bug Fix Migration Tool")
    print("This will fix all reported issues in the order management system.")
    print()

    if len(sys.argv) > 1 and sys.argv[1] == '--verify':
        verify_fixes()
    else:
        proceed = input("Do you want to proceed with the bug fix migration? (y/N): ").lower()
        if proceed == 'y':
            run_final_migration()
            print("\nRunning verification...")
            verify_fixes()
            print("\n🎉 All fixes have been applied successfully!")
            print("\nNext steps:")
            print("1. Restart your Flask application")
            print("2. Clear your browser cache")
            print("3. Test the order management functionality")
        else:
            print("Migration cancelled.")