import sqlite3
# Database file name
db_file = r"C:\Users\iniga\OneDrive\Programming\P2P Storage\PeersP2PStorage.db"

def display_table_contents(table_name):
    """Fetch and display all records from the given table."""
    try:
        # Connect to the database
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # Execute query to fetch all data
        cursor.execute(f"SELECT * FROM {table_name}")

        # Fetch column names
        columns = [description[0] for description in cursor.description]

        # Fetch all rows
        rows = cursor.fetchall()

        # Display table contents
        print(f"\n=== Contents of {table_name} ===")
        print(" | ".join(columns))  # Print column names
        print("-" * 50) 
        for row in rows:
            print(" | ".join(map(str, row)))

    except sqlite3.Error as e:
        print(f"Error reading {table_name}: {e}")

    finally:
        # Close the connection
        conn.close()

# List of tables to display
tables = ["peers"]

for table in tables:
    display_table_contents(table)
