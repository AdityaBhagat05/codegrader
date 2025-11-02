# test_db.py
from db_manager import insert_result, fetch_all_results, fetch_result_by_reg

# Insert a sample record
insert_result("23BCT0011", "Archit", 10, "Pass")

# Fetch and display all rows
print("\nAll Results:")
for row in fetch_all_results():
    print(row)

# Fetch a specific record
print("\nSingle Record (by reg_no):")
print(fetch_result_by_reg("23BCT0011"))
