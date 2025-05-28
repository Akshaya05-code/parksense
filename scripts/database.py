from pymongo import MongoClient
from datetime import datetime

class Database:
    def __init__(self, mongo_uri="mongodb://localhost:27017", db_name="rover_db", collection_name="number_plates"):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]

    def upsert_number_plate(self, number_plate):
        """Upsert number plate with timestamp."""
        result = self.collection.update_one(
            {"number_plate": number_plate},
            {
                "$set": {
                    "number_plate": number_plate,
                    "timestamp": datetime.utcnow()
                }
            },
            upsert=True
        )
        return result.modified_count > 0 or result.upserted_id is not None

    def check_number_plate(self, number_plate):
        """Check if number plate exists in the database."""
        return self.collection.find_one({"number_plate": number_plate}) is not None

    def close(self):
        """Close MongoDB connection."""
        self.client.close()