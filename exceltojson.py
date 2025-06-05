import pandas as pd
import json

# Path to your Excel file
excel_file = 'your_file.xlsx'  # Replace with your actual file name

# Read all sheets into a dictionary of DataFrames
sheets_dict = pd.read_excel(excel_file, sheet_name=None)

# Convert each sheet to a list of records (dicts)
json_data = {sheet_name: df.to_dict(orient='records') for sheet_name, df in sheets_dict.items()}

# Write the JSON data to a file
with open('output.json', 'w', encoding='utf-8') as json_file:
    json.dump(json_data, json_file, indent=4, ensure_ascii=False)

print("All sheets converted to JSON and saved as 'output.json'.")
