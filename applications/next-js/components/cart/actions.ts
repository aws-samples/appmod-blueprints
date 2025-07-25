'use server';

import { TAGS } from 'lib/constants';
import { addToCart, createCart, getCart, removeFromCart, updateCart } from 'lib/dynamo';
import { revalidateTag } from 'next/cache';
import { cookies } from 'next/headers';
import { CartProduct, Product, ProductVariants } from '../../lib/dynamo/types';

export async function addItem(prevState: any, cartItem: CartProduct) {
  let cartId = (await cookies()).get('cartId')?.value;
  let cart;

  if (cartId) {
    cart = await getCart(cartId);
  }

  if (!cartId || !cart || cart instanceof Error) {
    const cartResult = await createCart();
    if (cartResult instanceof Error) {
      return 'Error creating cart';
    }
    cart = cartResult;
    cartId = cart.id;
    (await cookies()).set('cartId', cartId);
  }

  if (!cartItem) {
    return 'Missing product variant ID';
  }

  try {
    const result = await addToCart(cartId, cartItem);
    if (result instanceof Error) {
      return 'Error adding item to cart';
    }
    revalidateTag(TAGS.cart);
  } catch (e) {
    return 'Error adding item to cart';
  }
}

export async function removeItem(prevState: any, productId: string) {
  const cartId = (await cookies()).get('cartId')?.value;

  if (!cartId) {
    return 'Missing cart ID';
  }

  try {
    const result = await removeFromCart(cartId, productId);
    if (result instanceof Error) {
      return 'Error removing item from cart';
    }
    revalidateTag(TAGS.cart);
  } catch (e) {
    return 'Error removing item from cart';
  }
}

export async function updateItemQuantity(prevState: any, cartItem: CartProduct) {
  const cartId = (await cookies()).get('cartId')?.value;

  if (!cartId) {
    return 'Missing cart ID';
  }

  try {
    if (cartItem.quantity === 0) {
      const result = await removeFromCart(cartId, cartItem.product.id);
      if (result instanceof Error) {
        return 'Error removing item from cart';
      }
      revalidateTag(TAGS.cart);
      return;
    }

    const result = await updateCart(cartItem);
    if (result instanceof Error) {
      return 'Error updating item quantity';
    }
    revalidateTag(TAGS.cart);
  } catch (e) {
    return 'Error updating item quantity';
  }
}
