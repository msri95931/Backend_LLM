import pandas as pd

# Load cleaned dataset from Task 2
df = pd.read_csv("flipkart_clean.csv")

print("Before Cleaning:")
print("Total Rows:", len(df))

# Remove rows with missing important values
df.dropna(subset=["product_name", "brand", "discounted_price"], inplace=True)

# Replace "No rating available" with 0
df["product_rating"] = df["product_rating"].replace("No rating available", 0)

# Convert rating column to numeric
df["product_rating"] = pd.to_numeric(df["product_rating"], errors="coerce")

# Fill missing ratings with 0
df["product_rating"].fillna(0, inplace=True)

print("\nAfter Cleaning:")
print("Total Rows:", len(df))

# Save final cleaned dataset
df.to_csv("flipkart_final.csv", index=False)

print("\n✅ Final cleaned dataset saved as flipkart_final.csv")
