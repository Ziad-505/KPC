import os
import glob

db_files = glob.glob("*.db")

csv_file_name = input("Enter dataset csv file name: ")

os.system(f"python generate_uuids.py {csv_file_name} {"uuids_" + csv_file_name}")

os.system(f"python csv_to_sqlite.py {"uuids_" + csv_file_name} output.db")


host = input("Enter host/ip: ")
port = input("Enter port number: ")

os.system(f"python server.py output.db {port} {host}")



