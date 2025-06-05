import pandas as pd
import json
import re

# Path to your Excel file
excel_file = 'your_file.xlsx'  # Replace with your actual file name

# Read all sheets into a dictionary of DataFrames
sheets_dict = pd.read_excel(excel_file, sheet_name=None)

# Function to make safe filenames from sheet names
def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

# Loop through sheets and save each as a separate JSON file
for sheet_name, df in sheets_dict.items():
    safe_name = sanitize_filename(sheet_name)
    json_filename = f"{safe_name}.json"
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(df.to_dict(orient='records'), f, indent=4, ensure_ascii=False)
    print(f"Saved: {json_filename}")

print("All sheets have been converted to separate JSON files.")
