import { v4 as uuidv4 } from 'uuid';
import {
  Menu,
  Page,
  Product,
  Category,
  Cart,
  CartProduct,
  ProductVariants,
  Wishlist
} from './types';

const API_URL = process.env.API_BASE_URL ?? 'http://rust-backend.team-rust-test.svc.cluster.local';

// Helper function to handle fetch requests with error handling
async function fetchWithErrorHandling<T>(url: string, options?: RequestInit): Promise<T | Error> {
  try {
    const response = await fetch(url, options);

    if (!response.ok) {
      return new Error(`API error: ${response.status} ${response.statusText}`);
    }

    return (await response.json()) as T;
  } catch (error) {
    return new Error(`Fetch error for ${url} ${error}`);
  }
}

export async function createCart(): Promise<Cart | Error> {
  return fetchWithErrorHandling<Cart>(`${API_URL}/cart/create_cart`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(uuidv4())
  });
}

export async function addToCart(cartId: string, cartItem: CartProduct): Promise<Cart | Error> {
  return fetchWithErrorHandling<Cart>(`${API_URL}/cart/add_to_cart/${cartId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(cartItem)
  });
}

export async function removeFromCart(cartId: string, cartItem: String): Promise<Cart | Error> {
  return fetchWithErrorHandling<Cart>(`${API_URL}/cart/remove_from_cart/${cartId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ cartItem })
  });
}

export async function updateCart(cartItems: CartProduct): Promise<Cart | Error> {
  return fetchWithErrorHandling<Cart>(`${API_URL}/cart/update`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ cartItems })
  });
}

export async function getCart(cartId: string): Promise<Cart | Error> {
  return fetchWithErrorHandling<Cart>(`${API_URL}/cart/get_cart/${cartId}`);
}

export async function createWishlist(): Promise<Wishlist | Error> {
  return fetchWithErrorHandling<Wishlist>(`${API_URL}/wishlist/new`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(uuidv4())
  });
}

export async function getWishlist(wishlistId: string): Promise<Wishlist | Error> {
  return fetchWithErrorHandling<Wishlist>(`${API_URL}/wishlist/${wishlistId}`);
}

export async function removeFromWishlist(
  wishlistId: string,
  wishlistItem: String
): Promise<Wishlist | Error> {
  return fetchWithErrorHandling<Wishlist>(`${API_URL}/wishlist/${wishlistId}/remove/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ wishlistItem })
  });
}

export async function addToWishlist(
  wishlistId: string,
  wishlistItem: CartProduct
): Promise<Wishlist | Error> {
  return fetchWithErrorHandling<Wishlist>(`${API_URL}/wishlist/${wishlistId}/add`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(wishlistItem)
  });
}

export async function getCategory(categoryName: string): Promise<Category | Error> {
  return fetchWithErrorHandling<Category>(`${API_URL}/category/${categoryName}`);
}

export async function getCollection(collectionName: string): Promise<Product[] | Error> {
  const data = await fetchWithErrorHandling<any>(`${API_URL}/collection/${collectionName}`);
  if (data instanceof Error) {
    return data;
  }
  return data.flatMap((item: Product) => item as Product);
}

export async function getCategoryProducts(categoryId: string): Promise<Product[] | Error> {
  const data = await fetchWithErrorHandling<any>(`${API_URL}/category/${categoryId}/products`);
  if (data instanceof Error) {
    return data;
  }
  return data.flatMap((item: Product) => item as Product);
}

export async function getCategories(): Promise<Category[] | Error> {
  return fetchWithErrorHandling<Category[]>(`${API_URL}/categories`);
}

export async function getMenu(menuId: string): Promise<Menu[] | Error> {
  const data = await fetchWithErrorHandling<any>(`${API_URL}/menu/${menuId}`);
  if (data instanceof Error) {
    return data;
  }
  return data.flatMap((item: Menu) => item as Menu);
}

export async function getPage(handle: string): Promise<Page | Error> {
  return fetchWithErrorHandling<Page>(`${API_URL}/page/${handle}`);
}

export async function getPages(): Promise<Page[] | Error> {
  return fetchWithErrorHandling<Page[]>(`${API_URL}/pages`);
}

export async function getProduct(id: string): Promise<Product | Error> {
  return fetchWithErrorHandling<Product>(`${API_URL}/product/${id}`);
}

export async function getProducts(searchVal: string): Promise<Product[] | Error> {
  const data = await fetchWithErrorHandling<any>(`${API_URL}/products`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(searchVal)
  });

  if (data instanceof Error) {
    return data;
  }
  return data.flatMap((item: Product) => item as Product);
}
