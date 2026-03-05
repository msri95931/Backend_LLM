def search_products_from_db(query):
    cursor.execute(
        "SELECT product_name, brand, discounted_price, product_rating "
        "FROM products WHERE product_name LIKE %s LIMIT 5",
        ("%" + query + "%",)
    )

    rows = cursor.fetchall()

    products = []
    for row in rows:
        products.append({
            "product_name": row[0],
            "brand": row[1],
            "discounted_price": row[2],
            "product_rating": row[3],
        })

    return products
