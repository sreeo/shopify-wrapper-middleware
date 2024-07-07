# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

SHOPIFY_SHOP_URL = os.getenv("SHOPIFY_SHOP_URL")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")


class Image(BaseModel):
    src: HttpUrl
    alt: Optional[str] = None


class Variant(BaseModel):
    id: int
    title: str
    price: str
    sku: Optional[str] = None


class VariantDetails(BaseModel):
    id: int
    title: str
    price: str
    sku: Optional[str] = None
    available: bool
    inventory_quantity: int


class ProductDetails(BaseModel):
    id: int
    title: str
    body_html: Optional[str]
    vendor: str
    product_type: str
    created_at: str
    updated_at: str
    published_at: Optional[str] = None
    variants: List[VariantDetails]
    images: List[Image]


class Product(BaseModel):
    id: int
    title: str
    body_html: Optional[str]
    vendor: str
    product_type: str
    created_at: str
    updated_at: str
    published_at: Optional[str] = None
    variants: List[Variant]
    images: List[Image]


class ProductsResponse(BaseModel):
    products: List[Product]


@app.get("/products",)
async def get_products():
    if not SHOPIFY_SHOP_URL or not SHOPIFY_ACCESS_TOKEN:
        raise HTTPException(
            status_code=500, detail="Shopify credentials not configured")

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{SHOPIFY_SHOP_URL}/admin/api/2023-04/products.json", headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code,
                            detail="Failed to fetch products from Shopify")
# return response.json()
    return ProductsResponse(**response.json())


@app.get("/products/{product_id}", response_model=ProductDetails)
async def get_product_details(product_id: int):
    if not SHOPIFY_SHOP_URL or not SHOPIFY_ACCESS_TOKEN:
        raise HTTPException(
            status_code=500, detail="Shopify credentials not configured")

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    url = f"{SHOPIFY_SHOP_URL}/admin/api/2023-04/products/{product_id}.json"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code,
                                detail="Failed to fetch product details from Shopify")

        product_data = response.json()["product"]

        # Fetch inventory levels for each variant
        variant_ids = [variant["id"] for variant in product_data["variants"]]
        inventory_item_ids = [variant["inventory_item_id"]
                              for variant in product_data["variants"]]
        inventory_url = f"{
            SHOPIFY_SHOP_URL}/admin/api/2023-04/inventory_levels.json?inventory_item_ids={','.join(map(str, inventory_item_ids))}"
        inventory_response = await client.get(inventory_url, headers=headers)

        if inventory_response.status_code != 200:
            raise HTTPException(status_code=inventory_response.status_code,
                                detail="Failed to fetch inventory levels from Shopify")

        inventory_levels = {item["inventory_item_id"]: item["available"]
                            for item in inventory_response.json()["inventory_levels"]}

        # Update variants with availability and inventory quantity
        for variant in product_data["variants"]:
            inventory_item_id = variant["inventory_item_id"]
            variant["available"] = inventory_levels.get(
                inventory_item_id, 0) > 0
            variant["inventory_quantity"] = inventory_levels.get(
                inventory_item_id, 0)

        return ProductDetails(**product_data)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
