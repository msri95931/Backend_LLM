import pandas as pd

# Load dataset
df = pd.read_csv("flipkart_com-ecommerce_sample.csv", encoding="ISO-8859-1")

# Rename column
df.rename(columns={"ï»¿uniq_id": "uniq_id"}, inplace=True)

# Keep only required columns
df = df[
    [
        "product_name",
        "brand",
        "description",
        "retail_price",
        "discounted_price",
        "product_rating",
        "product_category_tree",
        "product_specifications"
    ]
]

# Show dataset after filtering
print("Filtered Dataset Preview:\n")
print(df.head())

print("\nTotal Rows:", len(df))
print("Total Columns:", len(df.columns))

# Save filtered dataset
df.to_csv("flipkart_clean.csv", index=False)

print("\n✅ Clean dataset saved as flipkart_clean.csv")
