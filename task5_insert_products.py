import pandas as pd
import mysql.connector

# Load your final cleaned dataset
df = pd.read_csv("flipkart_final.csv")
df = df.fillna("")
df["retail_price"] = pd.to_numeric(df["retail_price"], errors="coerce").fillna(0)
df["discounted_price"] = pd.to_numeric(df["discounted_price"], errors="coerce").fillna(0)
df["product_rating"] = pd.to_numeric(df["product_rating"], errors="coerce").fillna(0)


print("CSV Loaded Successfully!")
print("Total Rows:", len(df))

# Connect to MySQL Database
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="Msri@1602",
    database="flipkart_ai"
)

cursor = db.cursor()

# Insert products one by one
for _, row in df.iterrows():
    cursor.execute("""
        INSERT INTO products
        (product_name, brand, description,
         retail_price, discounted_price,
         product_rating, category, specifications)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        row["product_name"],
        row["brand"],
        row["description"],
        row["retail_price"],
        row["discounted_price"],
        row["product_rating"],
        row["product_category_tree"],
        row["product_specifications"]
    ))

# Save changes
db.commit()

print("✅ All Products Inserted Successfully!")
