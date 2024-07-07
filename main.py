# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict
import httpx
import os
import re
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


class DetailedProductsResponse(BaseModel):
    products: List[ProductDetails]


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


async def fetch_inventory_levels(client: httpx.AsyncClient, variant_ids: List[int], headers: Dict[str, str]) -> Dict[int, Dict[str, int]]:
    inventory_url = f"{
        SHOPIFY_SHOP_URL}/admin/api/2023-04/inventory_levels.json?inventory_item_ids={','.join(map(str, variant_ids))}"
    inventory_response = await client.get(inventory_url, headers=headers)

    if inventory_response.status_code != 200:
        raise HTTPException(status_code=inventory_response.status_code,
                            detail="Failed to fetch inventory levels from Shopify")

    inventory_levels = {}
    for item in inventory_response.json()["inventory_levels"]:
        inventory_levels[item["inventory_item_id"]] = {
            "available": item["available"],
            "inventory_quantity": item["available"]
        }
    return inventory_levels


@app.get("/detailed-products", response_model=DetailedProductsResponse)
async def get_detailed_products():
    if not SHOPIFY_SHOP_URL or not SHOPIFY_ACCESS_TOKEN:
        raise HTTPException(
            status_code=500, detail="Shopify credentials not configured")

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    all_products = []
    next_url = f"{SHOPIFY_SHOP_URL}/admin/api/2023-04/products.json"

    async with httpx.AsyncClient() as client:
        while next_url:
            response = await client.get(next_url, headers=headers)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code, detail="Failed to fetch products from Shopify")

            products_data = response.json()["products"]

            # Collect all variant IDs
            all_variant_ids = [variant["inventory_item_id"]
                               for product in products_data for variant in product["variants"]]

            # Fetch inventory levels for all variants
            inventory_levels = await fetch_inventory_levels(client, all_variant_ids, headers)

            # Process each product
            for product in products_data:
                for variant in product["variants"]:
                    inventory_item_id = variant["inventory_item_id"]
                    inventory_info = inventory_levels.get(
                        inventory_item_id, {"available": 0, "inventory_quantity": 0})
                    quantity = inventory_info["inventory_quantity"] or 0

                    variant["available"] = quantity > 0
                    variant["inventory_quantity"] = quantity
                all_products.append(ProductDetails(**product))

            next_url = response.links.get("next", {}).get("url")

    return DetailedProductsResponse(products=all_products)


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
            inventory_level = inventory_levels.get(inventory_item_id) or 0
            variant["available"] = inventory_level > 0
            variant["inventory_quantity"] = inventory_level

        return ProductDetails(**product_data)


def extract_product_id_from_url(url: str) -> Optional[int]:
    # Pattern to match various forms of Shopify product URLs
    patterns = [
        r'/products/([^/]+)',  # Matches /products/product-handle
        # Matches /products/product-handle/1234567890
        r'/products/([^/]+)/(\d+)',
        r'variant=(\d+)',  # Matches variant query parameter
        r'product/(\d+)'  # Matches /product/1234567890
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            # If it's a numeric ID, return it
            if match.group(1).isdigit():
                return int(match.group(1))
            # If it's a handle, we need to query the API to get the ID
            else:
                return get_product_id_from_handle(match.group(1))

    return None


async def get_product_id_from_handle(handle: str) -> Optional[int]:
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }
    url = f"{SHOPIFY_SHOP_URL}/admin/api/2023-04/products.json?handle={handle}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            products = response.json().get("products", [])
            if products:
                return products[0]["id"]
    return None


@app.get("/product-by-url")
async def get_product_by_url(url: str):
    product_id = extract_product_id_from_url(url)
    if product_id is None:
        raise HTTPException(
            status_code=400, detail="Unable to extract product ID from URL")
    return await get_product_details(product_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
