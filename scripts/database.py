# from pymongo import MongoClient
# from pymongo.errors import ConnectionFailure
# from datetime import datetime

# class Database:
#     def __init__(self, mongo_uri="mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac", 
#                  db_name="parksense", collection_name="car_logs"):
#         try:
#             self.client = MongoClient(mongo_uri)
#             self.db = self.client[db_name]
#             self.collection = self.db[collection_name]
#             self.client.admin.command('ping')  # Test the connection
#             print("MongoDB Atlas connection successful!")
#         except ConnectionFailure:
#             print("MongoDB Atlas connection failed! Please check the connection string or network.")
#             exit(1)

#     def upsert_number_plate(self, number_plate):
#         """Upsert number plate with timestamp."""
#         result = self.collection.update_one(
#             {"number_plate": number_plate},
#             {
#                 "$set": {
#                     "number_plate": number_plate,
#                     "timestamp": datetime.utcnow()
#                 }
#             },
#             upsert=True
#         )
#         return result.modified_count > 0 or result.upserted_id is not None

#     def check_number_plate(self, number_plate):
#         """Check if number plate exists in the database."""
#         return self.collection.find_one({"number_plate": number_plate}) is not None

#     def close(self):
#         """Close MongoDB connection."""
#         self.client.close()

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from datetime import datetime

class Database:
    def __init__(self, mongo_uri="mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac", 
                 db_name="parksense", collection_name="car_logs"):
        try:
            # Jetson Nano may have limited resources, reduce connection timeout
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)  # 5-second timeout
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            self.client.admin.command('ping')  # Test the connection
            print("MongoDB Atlas connection successful!")
        except ConnectionFailure as e:
            print(f"MongoDB Atlas connection failed! Error: {e}")
            print("Please check the connection string, network, or MongoDB Atlas status.")
            exit(1)
        except Exception as e:
            print(f"Unexpected error during MongoDB connection: {e}")
            exit(1)

    def upsert_number_plate(self, number_plate):
        """Upsert number plate with timestamp."""
        try:
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
        except Exception as e:
            print(f"Failed to upsert number plate {number_plate}: {e}")
            return False

    def check_number_plate(self, number_plate):
        """Check if number plate exists in the database."""
        try:
            return self.collection.find_one({"number_plate": number_plate}) is not None
        except Exception as e:
            print(f"Failed to check number plate {number_plate}: {e}")
            return False

    def close(self):
        """Close MongoDB connection."""
        try:
            self.client.close()
            print("MongoDB connection closed.")
        except Exception as e:
            print(f"Error closing MongoDB connection: {e}")

if __name__ == "__main__":
    try:
        print("trying")
        # Initialize the database
        db = Database(
            mongo_uri="mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac",
            db_name="parksense",
            collection_name="car_logs"
        )
        
        # Test upserting a sample number plate
        test_plate = "TEST1234"
        print(f"\nTesting upsert for number plate: {test_plate}")
        upsert_result = db.upsert_number_plate(test_plate)
        if upsert_result:
            print(f"Successfully upserted number plate: {test_plate}")
        else:
            print(f"Failed to upsert number plate: {test_plate}")
        
        # Test checking if the number plate exists
        print(f"\nChecking if number plate {test_plate} exists")
        exists = db.check_number_plate(test_plate)
        if exists:
            print(f"Number plate {test_plate} found in database.")
        else:
            print(f"Number plate {test_plate} not found in database.")
        
        # Test checking a non-existent number plate
        test_plate_nonexistent = "FAKE9999"
        print(f"\nChecking if number plate {test_plate_nonexistent} exists")
        exists = db.check_number_plate(test_plate_nonexistent)
        if exists:
            print(f"Number plate {test_plate_nonexistent} found in database.")
        else:
            print(f"Number plate {test_plate_nonexistent} not found in database.")
        
    except Exception as e:
        print(f"Test failed: {e}")
    finally:
        # Close the database connection
        db.close()