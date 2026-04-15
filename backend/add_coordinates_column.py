"""
Migration script to add coordinates column to room_locations table
Run this script once to update your database schema
"""
from sqlalchemy import create_engine, text
from database import DATABASE_URL
import os
from dotenv import load_dotenv

load_dotenv()

def add_coordinates_column():
    """Add coordinates JSON column to room_locations table"""
    engine = create_engine(os.getenv("DATABASE_URL"))
    
    try:
        with engine.connect() as conn:
            # Check if column already exists
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='room_locations' 
                AND column_name='coordinates'
            """)
            result = conn.execute(check_query)
            
            if result.fetchone():
                print("✓ Column 'coordinates' already exists in room_locations table")
                return
            
            # Add the coordinates column
            alter_query = text("""
                ALTER TABLE room_locations 
                ADD COLUMN coordinates JSONB NULL
            """)
            conn.execute(alter_query)
            conn.commit()
            
            print("✓ Successfully added 'coordinates' column to room_locations table")
            print("  Column type: JSONB (allows storing JSON data like {x: 1.0, y: 2.0, z: 3.0})")
            
    except Exception as e:
        print(f"❌ Error adding column: {str(e)}")
        raise
    finally:
        engine.dispose()

if __name__ == "__main__":
    print("Adding coordinates column to room_locations table...")
    add_coordinates_column()
    print("\n✓ Migration completed successfully!")