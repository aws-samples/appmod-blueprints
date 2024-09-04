import {v4 as uuidv4} from "uuid";
import {Menu, Page, Product, Category, Cart, CartProduct} from "./types";

const API_URL = "http://127.0.0.1:8000";

export async function createCart(): Promise<Cart> {
  return fetch(`${API_URL}/cart/create_cart`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(uuidv4()),
  }).then(async (res) => await res.json() as Cart);
}

export async function addToCart(cartId: string,  cartItems: String[]): Promise<Cart> {
  return fetch(`${API_URL}/cart/add_to_cart/${cartId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ cartItems }),
  }).then(async (res) => await res.json() as Cart);
}

export async function removeFromCart(cartId: string, cartItems: String[]): Promise<Cart> {
  return fetch(`${API_URL}/cart/remove_from_cart/${cartId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ cartItems }),
  }).then(async (res) => await res.json() as Cart);
}

export async function updateCart(cartItems: Product[]): Promise<Cart> {
  return await fetch(`${API_URL}/cart/update`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ cartItems }),
  }).then(async (res) => await res.json() as Cart);
}

export async function getCart(cartId: string): Promise<Cart> {
  return await fetch(`${API_URL}/cart/get_cart/${cartId}`).then(async (res) => await res.json() as Cart);
}

export async function getCategory(categoryName: string): Promise<Category> {
  return await fetch(`${API_URL}/category/${categoryName}`).then(async (res) => await res.json() as Category);
}

export async function getCollection(
  collectionName: string,
): Promise<Product[]> {
  const resp = await fetch(`${API_URL}/collection/${collectionName}`);
  if (!resp.ok) {
    throw new Error(`Response status: ${resp.status}`);
  }
  let res = await resp.json();
  console.log(res);

  return res.flatMap((item) => item as Product);
}

export async function getCategoryProducts(
  categoryId: string,
): Promise<Product[]> {
  const resp = await fetch(`${API_URL}/category/${categoryId}/products`);
  if (!resp.ok) {
    throw new Error(`Response status: ${resp.status}`);
  }
  const res = await resp.json();
  console.log("{} category, products: {}", categoryId, res);
  return res.flatMap((item) => item as Product);
}

export async function getCategories(): Promise<Category[]> {
  return fetch(`${API_URL}/categories`).then((res) => res.json());
}

export async function getMenu(menuId: string): Promise<Menu[]> {
  const resp = await fetch(`${API_URL}/menu/${menuId}`);
  if (!resp.ok) {
    throw new Error(`Response status: ${resp.status}`);
  }

  const res = await resp.json();

  return res.flatMap((item) => item as Menu);
}

export async function getPage(handle: string): Promise<Page> {
  return fetch(`${API_URL}/page/${handle}`).then((res) => res.json());
}

export async function getPages(): Promise<Page[]> {
  return fetch(`${API_URL}/pages`).then((res) => res.json());
}

export async function getProduct(id: string): Promise<Product> {
  const resp = await fetch(`${API_URL}/product/${id}`);
  if (!resp.ok) {
    throw new Error(`Response status: ${resp.status}`);
  }
  const res = await resp.json();
  console.log("{} product: {}", id, res)

  return res as Product;
}

export async function getProducts(searchVal: string): Promise<Product[]> {
  // post request contains the searchVAl
  const resp = await fetch(`${API_URL}/products`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(searchVal),
  });

  if (!resp.ok) {
    throw new Error(`Response status: ${resp.status}`);
  }

  const res = await resp.json();

  return res.flatMap((item) => item as Product);
}