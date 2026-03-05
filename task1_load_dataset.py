import pandas as pd

# Load dataset with correct encoding
df = pd.read_csv("flipkart_com-ecommerce_sample.csv", encoding="ISO-8859-1")

# Rename wrong column name
df.rename(columns={"ï»¿uniq_id": "uniq_id"}, inplace=True)

# Show first 5 rows
print("Dataset Loaded Successfully!\n")
print(df.head())

# Show column names
print("\nColumns Available:\n")
print(df.columns)
